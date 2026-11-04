"""Regressions for answering temporal questions rather than listing newest rows."""
from datetime import date

import duckdb
import pytest
from fastapi.testclient import TestClient

from server.ai_analytics import constrain_request, execute_plan
from server.ai_models import AIQuestion, QueryPlan, chronological_metric, local_chronology_plan
from server.app import app
from server.gemini import ModelUnavailable


# Expected exports were found independently by streaming all five source CSVs
# and comparing parsed trade dates and source trade times.
@pytest.mark.parametrize('question,scope_year,expected_id,expected_day', [
    ('когда был первый экспорт?', 2026, 504726, '02.01.2026'),
    ('когда был первый экспорт за весь период?', 2026, 100024, '03.01.2022'),
    ('Первая экспортная сделка в 2022 году', 2026, 100024, '03.01.2022'),
])
def test_first_export_corrects_newest_first_model_plan(monkeypatch, question, scope_year, expected_id, expected_day):
    class Pool:
        async def generate(self, system, question, validate):
            # The old response in the screenshot selected records with descending order.
            plan = validate('{"metric":"records","contract_type":"Экспортный","year":2026,"order":"desc","limit":1}')
            return plan, {'model':'test-model','attempts':1,'used_backup':False}
    monkeypatch.setattr('server.ai.get_pool', lambda: Pool())
    response = TestClient(app).post('/api/ai/ask', json={'question':question,'scope':{'year':scope_year}})
    assert response.status_code == 200
    body = response.json()
    assert body['plan']['metric'] == 'first_deal'
    assert body['rows'][0]['deal_id'] == expected_id
    assert expected_day in body['answer']
    assert 'Найдено' not in body['answer']


@pytest.mark.parametrize('question,lang,expected_metric,expected_id', [
    ('когда был первый экспорт за весь период?', 'ru', 'first_deal', 100024),
    ('Последний экспорт за весь период', 'ru', 'last_deal', 604875),
    ('birinchi eksport qachon bo‘lgan?', 'uz', 'first_deal', 100024),
    ('oxirgi eksport qachon bo‘lgan?', 'uz', 'last_deal', 604875),
])
def test_exact_chronology_has_grounded_local_reserve(monkeypatch, question, lang, expected_metric, expected_id):
    class Pool:
        async def generate(self, *args):
            raise ModelUnavailable('all_unavailable')
    monkeypatch.setattr('server.ai.get_pool', lambda: Pool())
    # The language is detected from the question, even with the Russian UI default.
    response = TestClient(app).post('/api/ai/ask', json={'question':question,'scope':{'year':None}})
    assert response.status_code == 200
    body = response.json()
    assert body['plan']['metric'] == expected_metric
    assert body['rows'][0]['deal_id'] == expected_id
    assert body['provider']['kind'] == 'local'
    assert body['provider']['model'] == 'verified-chronology'
    assert ('bitim' in body['answer']) == (lang == 'uz')


@pytest.mark.parametrize('question', [
    'Пшеница первого сорта', 'Сделки первого сорта', 'Топ первых пяти покупателей',
    'Birinchi navli paxta narxi qancha?',
])
def test_grades_and_rankings_are_not_temporal_extremes(question):
    assert chronological_metric(question) is None


@pytest.mark.parametrize('question', [
    'Первый экспорт компании Foo', 'Первый экспорт без аннулированных за весь период',
    'Первый экспорт цемента в 2024 году',
])
def test_exact_local_reserve_does_not_discard_unparsed_conditions(question):
    assert local_chronology_plan(AIQuestion(question=question)) is None


@pytest.fixture
def chronological_database(tmp_path, monkeypatch):
    path = tmp_path/'chronology.duckdb'
    con = duckdb.connect(str(path))
    con.execute('''CREATE TABLE trades AS SELECT * FROM (VALUES
        (100,DATE '2024-01-03',TIME '13:00:00',DATE '2024-01-07'),
        (200,DATE '2024-01-03',TIME '10:00:00',DATE '2024-01-09'),
        (300,DATE '2024-01-03',TIME '12:00:00',NULL::DATE)
    ) t(deal_id,deal_date,deal_time,payment_date)''')
    con.execute('''ALTER TABLE trades ADD COLUMN product_label VARCHAR DEFAULT 'Test product';
        ALTER TABLE trades ADD COLUMN quantity DECIMAL(18,4) DEFAULT 1;
        ALTER TABLE trades ADD COLUMN unit VARCHAR DEFAULT 'тонна';
        ALTER TABLE trades ADD COLUMN amount_uzs DECIMAL(18,4) DEFAULT 10;
        ALTER TABLE trades ADD COLUMN status VARCHAR DEFAULT 'Исполнен';
        ALTER TABLE trades ADD COLUMN seller_name VARCHAR DEFAULT 'Seller';
        ALTER TABLE trades ADD COLUMN buyer_name VARCHAR DEFAULT 'Buyer';''')
    con.close()
    monkeypatch.setenv('UZEX_DB_PATH', str(path))


@pytest.mark.parametrize('metric,expected', [('first_deal',200),('last_deal',100)])
def test_chronology_uses_actual_time_before_deal_id(chronological_database, metric, expected):
    result = execute_plan(QueryPlan(metric=metric), AIQuestion(question='Проверка хронологии'))
    assert result['rows'][0]['deal_id'] == expected
    assert result['rows'][0]['deal_time'] in result['answer']


@pytest.mark.parametrize('order,expected', [('asc',200),('desc',100)])
def test_record_list_honours_chronological_direction(chronological_database, order, expected):
    result = execute_plan(QueryPlan(metric='records',order=order,limit=1), AIQuestion(question='Покажи сделки'))
    assert result['rows'][0]['deal_id'] == expected


@pytest.mark.parametrize('metric,expected,day', [('first_deal',100,'07.01.2024'),('last_deal',200,'09.01.2024')])
def test_payment_chronology_uses_payment_date_and_skips_absent_events(chronological_database, metric, expected, day):
    result = execute_plan(QueryPlan(metric=metric,date_field='payment_date'), AIQuestion(question='Проверка даты оплаты'))
    assert result['rows'][0]['deal_id'] == expected
    assert day in result['answer'] and 'дата оплаты' in result['answer']
    assert result['provenance']['row_count'] == 2


def test_exact_question_does_not_accept_invented_model_filters():
    request = AIQuestion(question='Когда был первый экспорт?',scope={'year':2026})
    plan = constrain_request(request, QueryPlan(metric='count',commodity='diesel',year=2024,form='Форвард'))
    assert plan.metric == 'first_deal' and plan.year == 2026
    assert plan.commodity is None and plan.form is None


def test_exact_question_keeps_selected_product_region_and_status():
    request = AIQuestion(question='Когда был первый экспорт?',scope={'year':2024,'commodity':'diesel','region':'tashkent_city','status':'active'})
    plan = constrain_request(request, QueryPlan(metric='records'))
    assert plan.year == 2024 and plan.commodity == 'diesel' and plan.region == 'tashkent_city'
    assert plan.include_cancelled is False


def test_ranking_answer_names_the_leading_buyer_and_amount():
    result = execute_plan(QueryPlan(metric='amount',group='buyer',year=2024,include_cancelled=False,contract_type='Внутренний',limit=5), AIQuestion(question='Крупнейшие покупатели'))
    assert 'Zoket Invest' in result['answer'] and '983531029' in result['answer']
    assert '1\u202f127\u202f417\u202f344\u202f173,29 UZS' in result['answer']
    assert len(result['rows']) == 5


def test_largest_export_answer_contains_the_result_before_the_table():
    result = execute_plan(QueryPlan(metric='max_amount',contract_type='Экспортный',report_currency='USD',limit=1), AIQuestion(question='Крупнейший экспорт'))
    assert '547500' in result['answer'] and '24.06.2026' in result['answer']
    assert '1\u202f683\u202f554,25 USD' in result['answer']


def test_exchange_rate_answer_states_the_actual_rate():
    result = execute_plan(QueryPlan(metric='rate',date_from=date(2026,10,30)), AIQuestion(question='Курс на 30 октября 2026'))
    assert '1 USD = 13\u202f369,54 UZS' in result['answer']
    assert 'usd_rates.csv' in result['answer']
    assert 'не текущая котировка' in result['answer']
