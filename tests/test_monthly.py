"""Compound monthly FX/export questions, checked against independent CSV totals."""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from server.ai_analytics import constrain_request, execute_plan
from server.ai_models import AIQuestion, MonthComparison, QueryPlan
from server.app import app
from server.monthly import local_monthly_plan
from server.question_checks import QuestionMismatch, validate_question

REF = json.loads((Path(__file__).parents[1]/'docs/monthly-export-reference.json').read_text(encoding='utf-8'))
QUESTION = 'Какой был курс доллара в июне 2026 года и на сколько выросла сумма экспорта хлопка относительно мая'


def calculate(question=QUESTION, **scope):
    request=AIQuestion(question=question,scope=scope)
    return execute_plan(constrain_request(request,local_monthly_plan(request)),request)


@pytest.mark.parametrize('question,lang',[
    (QUESTION,'ru'),
    ('Какой был курс доллара в июне 2026 года и на сколько изменилась сумма экспорта хлопка по сравнению с маем?','ru'),
    ('2026-yil iyun oyida dollar kursi qanday bo‘lgan va paxta eksporti summasi mayga nisbatan qanchaga o‘zgargan?','uz'),
])
def test_compound_user_question_answers_rate_and_absent_cotton_exports(monkeypatch,question,lang):
    def forbidden(): raise AssertionError('Known monthly arithmetic must not require a model response')
    monkeypatch.setattr('server.ai.get_pool',forbidden)
    response=TestClient(app).post('/api/ai/ask',json={'question':question,'lang':lang})
    body=response.json()
    assert response.status_code==200 and body['status']=='answer'
    assert body['provider']['model']=='verified-monthly-report'
    assert body['plan']['commodity']=='cotton'
    assert [r['id'] for r in body['rows']]==['2026-05','2026-06']
    assert all(r['deals']==0 and Decimal(r['amount'])==0 for r in body['rows'])
    assert body['provenance']['comparison']['relative_percent'] is None
    assert '13\u202f162,58' in body['answer']
    assert ('не найдены' if lang=='ru' else 'topilmadi') in body['answer']
    assert not ('+0,00%' in body['answer'] or 'Хлопковая пряжа' in body['answer'])
    for row,m in zip(body['rows'],['5','6']):
        expected=REF['rates'][m]
        assert row['rate_days']==expected['days']
        assert Decimal(row['rate_sum'])==Decimal(expected['sum'])
        assert Decimal(row['rate_mean']).quantize(Decimal('.00000001'))==Decimal(expected['mean']).quantize(Decimal('.00000001'))
        for key in ['min','max']: assert Decimal(row['rate_'+key])==Decimal(expected[key])


@pytest.mark.parametrize('product,code,sign', [('хлопковой пряжи','520512','-'),('меди','740311','+')])
def test_real_increase_and_decrease_match_independent_csv_reference(product,code,sign):
    body=calculate(QUESTION.replace('хлопка',product))
    expected=REF['products'][code]
    for row,m in zip(body['rows'],['5','6']):
        assert row['deals']==expected[m]['deals']
        assert Decimal(row['amount'])==Decimal(expected[m]['amount_uzs'])
    change=body['provenance']['comparison']
    assert Decimal(change['difference'])==Decimal(expected['difference_uzs'])
    assert Decimal(change['relative_percent']).quantize(Decimal('.00000001'))==Decimal(expected['relative_percent']).quantize(Decimal('.00000001'))
    assert sign+('16,85%' if code=='520512' else '66,30%') in body['answer']


def test_monthly_compiler_converts_each_deal_at_its_own_rate_not_monthly_average():
    body=calculate(QUESTION.replace('хлопка','хлопковой пряжи'))
    for row,m in zip(body['rows'],['5','6']):
        expected=REF['products']['520512'][m]
        assert Decimal(row['amount'])!=Decimal(expected['amount_usd'])*Decimal(REF['rates'][m]['mean'])
    assert 'не используется вместо дневного курса' in body['provenance']['method']


def test_cancelled_filter_and_explicit_year_override_ui_scope():
    body=calculate(QUESTION.replace('хлопка','хлопковой пряжи')+' без аннулированных',year=2024)
    assert body['plan']['year']==2026
    assert body['plan']['include_cancelled'] is False
    for row,m in zip(body['rows'],['5','6']):
        expected=REF['products']['520512'][m]
        assert row['deals']==expected['active_deals']
        assert Decimal(row['amount'])==Decimal(expected['active_amount_uzs'])


def test_rate_usd_label_does_not_change_requested_trade_reporting_currency():
    body=calculate(QUESTION.replace('доллара','USD').replace('хлопка','хлопковой пряжи'))
    assert body['plan']['report_currency']=='UZS'
    assert Decimal(body['rows'][0]['amount'])==Decimal(REF['products']['520512']['5']['amount_uzs'])


def test_explicit_usd_trade_reporting_remains_separate_from_exchange_rate():
    body=calculate(QUESTION.replace('хлопка','хлопковой пряжи в долларах'))
    assert body['plan']['report_currency']=='USD'
    assert Decimal(body['rows'][0]['amount'])==Decimal(REF['products']['520512']['5']['amount_usd'])
    assert Decimal(body['rows'][1]['rate_mean'])>13000


def test_plain_month_comparison_does_not_claim_user_requested_rates():
    body=calculate('На сколько изменилась сумма экспорта меди в июне 2026 года по сравнению с маем')
    assert body['plan']['month_comparison']['include_usd_rate'] is False
    assert 'Курс доллара' not in body['answer']
    assert not any(c['key']=='rate_mean' for c in body['columns'])


def test_comparison_direction_follows_question_even_when_target_is_earlier():
    body=calculate('На сколько изменилась сумма экспорта меди в мае 2026 года относительно июня')
    assert [r['id'] for r in body['rows']]==['2026-06','2026-05']
    expected=REF['products']['740311']
    assert Decimal(body['provenance']['comparison']['difference'])==-Decimal(expected['difference_uzs'])


@pytest.mark.parametrize('qualifier',[
    ' компании «Global Trade»',' со склада в Самарканде',' первого сорта',
    ' больше 1000000 сумов',' и наша прибыль',' и экспортной цены',
])
def test_local_month_parser_does_not_discard_unhandled_constraints(qualifier):
    assert local_monthly_plan(AIQuestion(question=QUESTION+qualifier)) is None


@pytest.mark.parametrize('mutation', ['omit_rate','reverse_direction','wrong_product','omit_baseline','unexpected_rate'])
def test_independent_guard_rejects_incomplete_or_changed_compound_plans(mutation):
    request=AIQuestion(question=QUESTION)
    plan=local_monthly_plan(request)
    if mutation=='omit_rate': plan.month_comparison.include_usd_rate=False
    elif mutation=='reverse_direction':
        plan.month_comparison.baseline,plan.month_comparison.target=plan.month_comparison.target,plan.month_comparison.baseline
    elif mutation=='wrong_product': plan.commodity='yarn'
    elif mutation=='omit_baseline': plan.month_comparison=None
    else:
        request.question='На сколько изменилась сумма экспорта хлопка в июне 2026 года относительно мая'
    with pytest.raises(QuestionMismatch): validate_question(request,plan)


def test_profit_is_reported_as_missing_field_before_any_provider_call(monkeypatch):
    def forbidden(): raise AssertionError('Profit cannot be computed from transaction amounts')
    monkeypatch.setattr('server.ai.get_pool',forbidden)
    body=TestClient(app).post('/api/ai/ask',json={'question':QUESTION+' и насколько выросла наша прибыль'}).json()
    assert body['status']=='no_data' and body['reason']=='unsupported_field'
    assert 'Сумма сделки не является прибылью' in body['answer']
    assert body['rows']==[]


def test_missing_year_is_not_guessed_when_ui_has_all_years():
    assert local_monthly_plan(AIQuestion(question=QUESTION.replace('2026 года',''),scope={'year':None})) is None
    plan=local_monthly_plan(AIQuestion(question=QUESTION.replace('2026 года',''),scope={'year':2025}))
    assert plan.month_comparison.target==date(2025,6,1)


def test_absent_future_month_is_not_reported_as_zero_export():
    body=calculate(QUESTION.replace('июне','декабре'))
    assert body['status']=='no_data' and body['reason']=='out_of_period' and body['rows']==[]


@pytest.fixture
def small_months(tmp_path,monkeypatch):
    path=tmp_path/'months.duckdb'
    with duckdb.connect(str(path)) as con:
        con.execute('''CREATE TABLE trades AS SELECT * FROM (VALUES
            (DATE '2026-04-01','Экспортный','cotton','Исполнен',10::DECIMAL(30,8)),
            (DATE '2026-05-01','Экспортный','cotton','Исполнен',999::DECIMAL(30,8)),
            (DATE '2026-06-01','Экспортный','cotton','Исполнен',20::DECIMAL(30,8))
        ) t(deal_date,contract_type,commodity,status,amount_uzs)''')
        con.execute('''CREATE TABLE usd_rates AS SELECT * FROM (VALUES
            (DATE '2026-04-01',10::DECIMAL(10,2)),(DATE '2026-06-01',20::DECIMAL(10,2))
        ) r(rate_date,usd_rate)''')
    monkeypatch.setenv('UZEX_DB_PATH',str(path))


def test_nonadjacent_months_exclude_the_intervening_month_from_totals(small_months):
    body=calculate(QUESTION.replace('мая','апреля'))
    assert body['provenance']['row_count']==2
    assert [Decimal(r['amount']) for r in body['rows']]==[10,20]
    assert body['provenance']['comparison']['relative_percent']=='100'


def test_a_zero_baseline_never_becomes_a_numeric_growth_percent(small_months):
    body=calculate(QUESTION.replace('мая','марта'))
    assert body['rows'][0]['deals']==0 and body['rows'][1]['deals']==1
    assert Decimal(body['provenance']['comparison']['difference'])==20
    assert body['provenance']['comparison']['relative_percent'] is None


def test_missing_target_rate_does_not_substitute_other_month_rate(small_months):
    body=calculate(QUESTION.replace('июне','июле').replace('мая','апреля'))
    assert body['rows'][1]['rate_mean'] is None
    assert 'нет курса за целевой месяц' in body['answer']


def test_invalid_month_comparison_shape_is_not_accepted():
    with pytest.raises(ValueError): MonthComparison(baseline='2026-05-02',target='2026-06-01')
    with pytest.raises(ValueError): QueryPlan(metric='records',group='month',comparison=True,month_comparison={'baseline':'2026-05-01','target':'2026-06-01'})


@pytest.mark.parametrize('extra', [' и среднюю цену',' и физический объем'])
def test_model_cannot_drop_additional_measures_from_monthly_report(extra):
    request=AIQuestion(question=QUESTION+extra)
    plan=local_monthly_plan(AIQuestion(question=QUESTION))
    with pytest.raises(QuestionMismatch): validate_question(request,plan)
