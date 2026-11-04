"""Ratio arithmetic and the user's percentage-comparison question."""
import json
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from server.ai_analytics import constrain_request, execute_plan
from server.ai_models import AIQuestion, QueryPlan, ShareTarget, local_ratio_plan, money, share_intent
from server.app import app
from server.ratios import changes, percentage
from server.question_checks import QuestionMismatch

REF=json.loads((Path(__file__).parents[1]/'docs/export-share-reference.json').read_text(encoding='utf-8'))
QUESTION='процент экспорта 2025 и 2026 и разница в процентах'
EXPORT=ShareTarget(dimension='contract_type',value='Экспортный')


@pytest.mark.parametrize('question,lang',[
    (QUESTION,'ru'),
    ('Доля экспорта за 2025 и 2026 годы и разница','ru'),
    ('2025 va 2026 yillarda eksport ulushi va foizlardagi farqi','uz'),
])
def test_user_question_returns_both_shares_and_changes_without_model_guessing(monkeypatch,question,lang):
    def forbidden(): raise AssertionError('Unambiguous arithmetic must not depend on an API response')
    monkeypatch.setattr('server.ai.get_pool',forbidden)
    response=TestClient(app).post('/api/ai/ask',json={'question':question,'lang':lang})
    assert response.status_code==200
    body=response.json()
    assert body['status']=='answer' and body['provider']['kind']=='local'
    assert [r['id'] for r in body['rows']]==[2025,2026]
    for actual,expected in zip(body['rows'],REF['scopes']['all']['rows']):
        for field in ['deals','target_deals']: assert actual[field]==expected[field]
        for field in ['amount','target_amount']: assert Decimal(actual[field])==Decimal(expected[field])
        for field in ['amount_share_pct','count_share_pct']:
            assert Decimal(actual[field]).quantize(Decimal('.000000000001'))==Decimal(expected[field]).quantize(Decimal('.000000000001'))
    for actual in body['provenance']['comparison']:
        expected=REF['scopes']['all']['comparison'][actual['basis']]
        for field in ['difference_pp','relative_change_pct']:
            assert Decimal(actual[field]).quantize(Decimal('.000000000001'))==Decimal(expected[field]).quantize(Decimal('.000000000001'))
    assert '30.10.2026' in body['answer']
    assert '4,8963%' in body['answer'] and '6,3547%' in body['answer']
    assert '1,4584' in body['answer'] and '29,79%' in body['answer']


def test_share_without_cancelled_matches_independent_csv_scan():
    request=AIQuestion(question=QUESTION+' без аннулированных')
    plan=constrain_request(request,local_ratio_plan(request))
    body=execute_plan(plan,request)
    for actual,expected in zip(body['rows'],REF['scopes']['without_cancelled']['rows']):
        assert actual['deals']==expected['deals'] and actual['target_deals']==expected['target_deals']
        assert Decimal(actual['target_amount'])==Decimal(expected['target_amount'])
        assert Decimal(actual['amount'])==Decimal(expected['amount'])


@pytest.mark.parametrize('basis,words', [('amount','по сумме'),('count','по количеству сделок'),('amount','в сумах'),('amount','so‘mda')])
def test_explicit_share_basis_is_preserved(basis,words):
    request=AIQuestion(question=QUESTION+' '+words)
    plan=constrain_request(request,local_ratio_plan(request))
    assert plan.share_basis==basis
    result=execute_plan(plan,request)
    keys={c['key'] for c in result['columns']}
    assert basis+'_share_pct' in keys
    assert ('count' if basis=='amount' else 'amount')+'_share_pct' not in keys


@pytest.mark.parametrize('question',[
    QUESTION+' по цементу', QUESTION+' компании «Global Trade»',
    QUESTION+' со склада в Самарканде', QUESTION+' до 30 октября',
])
def test_local_ratio_parser_never_discards_unknown_qualifiers(question):
    assert local_ratio_plan(AIQuestion(question=question)) is None


def test_export_growth_is_not_replaced_by_export_market_share():
    question='рост экспорта 2025 и 2026 в процентах'
    assert share_intent(question) is False
    request=AIQuestion(question=question)
    plan=constrain_request(request,local_ratio_plan(request))
    assert plan.metric=='amount' and plan.comparison is True
    body=execute_plan(plan,request)
    assert '+'+money(REF['export_amount_change_pct'])+'%' in body['answer']
    assert 'п.п.' not in body['answer']
    assert '30.10.2026' in body['answer']


def test_only_named_nonconsecutive_years_are_compared():
    request=AIQuestion(question='процент экспорта 2022 и 2026 и разница в процентах')
    plan=constrain_request(request,local_ratio_plan(request))
    result=execute_plan(plan,request)
    assert [row['id'] for row in result['rows']]==[2022,2026]
    assert result['rows'][0]['deals']==84299


def test_absent_future_year_does_not_become_a_zero_share():
    response=TestClient(app).post('/api/ai/ask',json={'question':'процент экспорта 2026 и 2027'})
    assert response.json()['status']=='no_data' and response.json()['rows']==[]


def test_zero_denominator_and_zero_baseline_are_not_reported_as_zero_percent():
    assert percentage(0,0) is None
    assert changes(0,20)=={'difference':'20','relative_percent':None}
    assert changes(None,20)=={'difference':None,'relative_percent':None}
    assert changes(20,0)=={'difference':'-20','relative_percent':'-100'}


@pytest.fixture
def small_market(tmp_path,monkeypatch):
    path=tmp_path/'shares.duckdb'
    con=duckdb.connect(str(path))
    con.execute('''CREATE TABLE trades AS SELECT * FROM (VALUES
        (1,DATE '2025-01-03','Экспортный',10::DECIMAL(30,8),'wheat','samarkand','Исполнен'),
        (2,DATE '2025-01-03','Экспортный',10::DECIMAL(30,8),'sugar','samarkand','Аннулирован(Не оплачен)'),
        (3,DATE '2025-01-03','Внутренний',80::DECIMAL(30,8),'wheat','tashkent_city','Исполнен'),
        (4,DATE '2026-01-02','Экспортный',30::DECIMAL(30,8),'wheat','samarkand','Исполнен'),
        (5,DATE '2026-01-02','Внутренний',70::DECIMAL(30,8),'sugar','tashkent_city','Исполнен')
    ) t(deal_id,deal_date,contract_type,amount_uzs,commodity,region,status)''')
    con.close()
    monkeypatch.setenv('UZEX_DB_PATH',str(path))
    return path


def ratio_plan(**updates):
    return QueryPlan(metric='share',share_target=EXPORT,group='year',comparison=True,years=[2025,2026],**updates)


def test_export_numerator_does_not_filter_the_denominator_to_exports(small_market):
    body=execute_plan(ratio_plan(contract_type='Экспортный'),AIQuestion(question='Проверка знаменателя'))
    a,b=body['rows']
    assert Decimal(a['amount_share_pct'])==20 and Decimal(b['amount_share_pct'])==30
    assert Decimal(a['count_share_pct'])>Decimal(b['count_share_pct'])
    assert body['provenance']['comparison'][0]['difference_pp']=='10'
    assert body['provenance']['comparison'][0]['relative_change_pct']=='50'


def test_commodity_share_removes_the_same_implicit_ui_product_filter(small_market):
    request=AIQuestion(question='доля пшеницы 2025 и 2026',scope={'commodity':'wheat'})
    plan=constrain_request(request,QueryPlan(metric='share',share_target=ShareTarget(dimension='commodity',value='wheat')))
    result=execute_plan(plan,request)
    assert Decimal(result['rows'][0]['amount_share_pct'])==90
    assert result['rows'][0]['deals']==3


def test_zero_initial_export_share_has_percentage_points_but_no_relative_growth(small_market):
    con=duckdb.connect(str(small_market))
    con.execute("UPDATE trades SET contract_type='Внутренний' WHERE year(deal_date)=2025")
    con.close()
    body=execute_plan(ratio_plan(),AIQuestion(question='Проверка нулевой базы'))
    change=body['provenance']['comparison'][0]
    assert Decimal(change['difference_pp'])==30 and change['relative_change_pct'] is None
    assert 'исходная доля равна 0' in body['answer']


def test_a_period_with_no_denominator_has_undefined_share(small_market):
    con=duckdb.connect(str(small_market))
    con.execute("DELETE FROM trades WHERE year(deal_date)=2025")
    con.close()
    result=execute_plan(ratio_plan(),AIQuestion(question='Проверка пустого периода'))
    assert result['rows'][0]['amount_share_pct'] is None
    assert result['provenance']['comparison'][0]['difference_pp'] is None


@pytest.mark.parametrize('dimension,value,expected',[
    ('region','samarkand',20),('status','Исполнен',90),
])
def test_same_share_operation_supports_warehouse_regions_and_statuses(small_market,dimension,value,expected):
    plan=ratio_plan()
    plan.share_target=ShareTarget(dimension=dimension,value=value)
    result=execute_plan(plan,AIQuestion(question='Проверка структуры'))
    assert Decimal(result['rows'][0]['amount_share_pct'])==expected


@pytest.mark.parametrize('question',['Доля экспорта по объёму','Доля экспорта с опозданием'])
def test_share_cannot_silently_ignore_an_unrepresented_measure_or_condition(question):
    with pytest.raises(QuestionMismatch):
        constrain_request(AIQuestion(question=question),QueryPlan(metric='share',share_target=EXPORT))


def test_negative_fractional_percent_preserves_its_sign():
    assert money(Decimal('-0.198713'),4)=='-0,1987'
    assert money(Decimal('-0.22'))=='-0,22'
    assert money(Decimal('-0.0001'),2)=='0,00'


def test_small_share_decrease_is_not_rendered_as_a_positive_difference(small_market):
    con=duckdb.connect(str(small_market))
    con.execute("UPDATE trades SET amount_uzs=CASE WHEN contract_type='Экспортный' THEN 19.8 ELSE 80.2 END WHERE year(deal_date)=2026")
    con.close()
    body=execute_plan(ratio_plan(),AIQuestion(question='Проверка снижения доли'))
    assert '-0,2000 п.п.' in body['answer']
