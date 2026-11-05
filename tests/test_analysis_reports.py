"""General aggregate reports: independent references, varied scopes and adversarial plans."""
import json
import httpx
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from server.ai_models import AIQuestion,AnalysisSpec,QueryPlan
from server.ai_analytics import constrain_request,execute_plan
from server.analysis_reports import local_analysis_plan,period_for_question
from server.app import app
from server.question_checks import QuestionMismatch,validate_question
from server.gemini import GeminiPool

ROOT=Path(__file__).parents[1]
REF=json.loads((ROOT/'docs/analysis-report-reference.json').read_text(encoding='utf-8'))
MATRIX=json.loads((ROOT/'docs/analysis-matrix-reference.json').read_text(encoding='utf-8'))['cases']
QUESTION='2025-yilning 4-choragida (oktabr–dekabr) paxta xom ashyosi, 1-sort, spot bitimlari orasidan (bekor qilinganlarsiz) eng ko’p hajmda xarid qilgan kompaniyani toping. Uning STIR raqami va nomini, xarid hajmini tonnada, nechta bitim va nechta turli sotuvchidan xarid qilganini, brokeri kimligini hamda uning ulushi shu davrdagi umumiy hajmning necha foizini tashkil qilishini ayting.'


@pytest.mark.parametrize('question,lang',[
    (QUESTION,'uz'),
    (QUESTION.replace(' (oktabr–dekabr)',''),'uz'),
    (QUESTION.replace('eng ko’p','top-1'),'uz'),
    ('За 4 квартал 2025 года найди покупателя хлопка 1-сорт спот без аннулированных с наибольшим объемом. Покажи ИНН и название, объем в тоннах, количество сделок и число разных продавцов, брокера и долю объема.','ru'),
])
def test_general_report_answers_all_requested_fields_against_independent_csv(monkeypatch,question,lang):
    def forbidden():raise AssertionError('Supported aggregate report must not require a model response')
    monkeypatch.setattr('server.ai.get_pool',forbidden)
    response=TestClient(app).post('/api/ai/ask',json={'question':question,'lang':lang,'scope':{'year':2026}})
    body=response.json()
    assert response.status_code==200 and body['status']=='answer'
    assert body['provider']['model']=='verified-analysis'
    row=body['rows'][0];expected=REF['top5'][0]
    assert row['id']==expected['inn'] and row['label']==expected['name']
    assert Decimal(row['quantity'])==Decimal(expected['quantity_tonnes'])
    assert row['deals']==364 and row['distinct_sellers']==33
    assert Decimal(row['share_pct']).quantize(Decimal('.000000000001'))==Decimal(expected['share_pct']).quantize(Decimal('.000000000001'))
    assert body['provenance']['row_count']==7119
    assert Decimal(body['provenance']['denominator']['value'])==Decimal(REF['total_quantity_tonnes'])
    assert body['plan']['date_from']=='2025-10-01' and body['plan']['date_to']=='2025-12-31'
    assert body['plan']['include_cancelled'] is False
    brokers=body['sections'][1]['rows']
    assert {r['broker_code'] for r in brokers}=={'BK017'}
    assert brokers[0]['broker_name']=='FIPI BROKER MCHJ'
    assert '4,7797%' in body['answer']


@pytest.mark.parametrize('case',MATRIX,ids=[c['id'] for c in MATRIX])
def test_composable_plan_across_products_periods_roles_and_measures(case):
    commodity={'520100':'cotton','252329':'cement','100199':'wheat','170199':'sugar','271019':'diesel'}[case['tnved']]
    noun={'cotton':'хлопка','cement':'цемента','wheat':'пшеницы','sugar':'сахара','diesel':'дизельного топлива'}[commodity]
    counter='distinct_sellers' if case['role']=='buyer' else 'distinct_buyers'
    role='покупателя' if case['role']=='buyer' else 'продавца'
    filters=(' 1-сорт' if case.get('grade') else '')+(' спот' if case.get('form') else '')+(' без аннулированных' if case.get('exclude_cancelled') else '')
    measure='объемом в '+('литрах' if case['unit']=='литр' else 'тоннах') if case['rank']=='quantity' else 'суммой'
    q=f"За период {case['from']} — {case['to']} найди {role} {noun}{filters} с наибольшим {measure}. Покажи количество сделок, число разных "+('продавцов' if case['role']=='buyer' else 'покупателей')+', брокера и долю '+('объема' if case['rank']=='quantity' else 'суммы')+'.'
    request=AIQuestion(question=q)
    plan=QueryPlan(metric='analysis',analysis=AnalysisSpec(measures=[case['rank'],'deals',counter],sort_by=case['rank'],share_by=case['rank'],broker_details=True),
                   group=case['role'],year=case['year'],date_from=case['from'],date_to=case['to'],commodity=commodity,
                   grade='1' if case.get('grade') else None,form=case.get('form'),include_cancelled=not case.get('exclude_cancelled',False),
                   physical_unit=case['unit'] if case['rank']=='quantity' else None,limit=1)
    body=execute_plan(constrain_request(request,plan),request)
    expected=case['expected']
    if expected['total_deals']==0:
        assert body['status']=='no_data' and body['rows']==[]
        return
    assert body['status']=='answer'
    row=body['rows'][0];winner=expected['top5'][0]
    assert row['id']==winner['inn'] and row['label']==winner['name']
    assert Decimal(row[case['rank']])==Decimal(winner[case['rank']])
    assert row['deals']==winner['deals'] and row[counter]==winner[counter]
    assert body['provenance']['row_count']==expected['total_deals']
    assert Decimal(body['provenance']['denominator']['value'])==Decimal(expected['total_'+case['rank']])
    assert Decimal(row['share_pct']).quantize(Decimal('.000000001'))==Decimal(winner['share_pct']).quantize(Decimal('.000000001'))
    assert {r['broker_code'] for r in body['sections'][1]['rows'] if r['company_inn']==row['id']}==set(winner['brokers'])


def test_multiple_brokers_and_top_n_do_not_shrink_the_share_denominator():
    request=AIQuestion(question=QUESTION)
    plan=constrain_request(request,local_analysis_plan(request));plan.limit=5
    body=execute_plan(plan,request)
    assert [r['id'] for r in body['rows']]==[r['inn'] for r in REF['top5']]
    assert Decimal(body['provenance']['denominator']['value'])==Decimal(REF['total_quantity_tonnes'])
    second=REF['top5'][1]
    actual=[r for r in body['sections'][1]['rows'] if r['company_inn']==second['inn']]
    assert {r['broker_code'] for r in actual}=={'BK034','BK119'}
    assert sum(r['deals'] for r in actual)==149


@pytest.mark.parametrize('field', ['quarter','form','grade','cancelled','commodity','unit','group','measure','rank','share','broker'])
def test_independent_guard_rejects_a_plan_that_drops_or_changes_requested_information(field):
    request=AIQuestion(question=QUESTION)
    plan=local_analysis_plan(request)
    if field=='quarter':plan.date_from=date(2025,1,1)
    elif field=='form':plan.form='Форвард'
    elif field=='grade':plan.grade=None
    elif field=='cancelled':plan.include_cancelled=True
    elif field=='commodity':plan.commodity='yarn'
    elif field=='unit':plan.physical_unit='килограмм'
    elif field=='group':plan.group='seller'
    elif field=='measure':plan.analysis.measures=['quantity','deals']
    elif field=='rank':plan.analysis.sort_by='deals'
    elif field=='share':plan.analysis.share_by='deals'
    else:plan.analysis.broker_details=False
    with pytest.raises(QuestionMismatch):validate_question(request,plan)


def test_old_single_aggregate_cannot_silently_omit_distinct_counterparties():
    with pytest.raises(QuestionMismatch):
        validate_question(AIQuestion(question=QUESTION),QueryPlan(metric='volume',group='buyer',commodity='cotton'))


@pytest.mark.parametrize('extra',[' и первую сделку',' и минимальную цену',' и поставки с опозданием'])
def test_additional_unrepresented_operations_are_not_silently_dropped(extra):
    base='За 4 квартал 2025 года найди покупателя хлопка с наибольшим объемом в тоннах'
    plan=local_analysis_plan(AIQuestion(question=base))
    with pytest.raises(QuestionMismatch):validate_question(AIQuestion(question=base+extra),plan)


def test_quarter_and_parenthesized_months_must_agree():
    with pytest.raises(QuestionMismatch):
        period_for_question(AIQuestion(question=QUESTION.replace('oktabr–dekabr','yanvar–mart')))


@pytest.mark.parametrize('wording',['4-й квартал','4-м квартале','IV квартал','четвёртый квартал',"to‘rtinchi choragida"])
def test_calendar_quarters_have_same_boundaries_across_common_ru_uz_forms(wording):
    assert period_for_question(AIQuestion(question='2025 '+wording))==(date(2025,10,1),date(2025,12,31))


def test_model_can_build_general_report_and_wrong_partial_plan_falls_back(monkeypatch):
    question=QUESTION+' Со склада в Самарканде.'
    request=AIQuestion(question=question)
    assert local_analysis_plan(request) is None
    payload=local_analysis_plan(AIQuestion(question=QUESTION)).model_dump(mode='json')
    payload['year']=2025;payload['region']='samarkand'
    calls=[]
    def handler(req):
        calls.append(req.url.path)
        plan=json.loads(json.dumps(payload))
        if len(calls)==1:plan['analysis']['measures']=['quantity','deals']
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(plan)}]}}]})
    pool=GeminiPool(keys=['test-only'],models=['partial','complete'],transport=httpx.MockTransport(handler),discover=False)
    monkeypatch.setattr('server.ai.get_pool',lambda:pool)
    body=TestClient(app).post('/api/ai/ask',json={'question':question}).json()
    assert body['status']=='answer' and len(calls)==2
    assert body['provider']['used_backup'] and body['provider']['model']=='complete'
    assert body['plan']['region']=='samarkand'
    assert all('samarkand' in part['parameters'] for part in body['provenance']['operations'])


@pytest.mark.parametrize('extra',[' компании «Global Trade»',' с поставкой позже срока',' со средней температурой',' больше 1000000 сумов'])
def test_local_analysis_never_discards_unrepresented_qualifiers(extra):
    assert local_analysis_plan(AIQuestion(question=QUESTION+extra)) is None


@pytest.fixture
def small_analytics(tmp_path,monkeypatch):
    path=tmp_path/'general.duckdb'
    with duckdb.connect(str(path)) as con:
        con.execute('''CREATE TABLE trades AS SELECT * FROM (VALUES
          (1,DATE '2025-11-01','111111111','Buyer A','444444444','Seller X','BK001','BK002','wheat','Исполнен',10::DECIMAL(30,8),100::DECIMAL(30,8),'килограмм'),
          (2,DATE '2025-11-02','111111111','Buyer A','444444444','Seller X','BK002','BK002','wheat','Исполнен',20::DECIMAL(30,8),200::DECIMAL(30,8),'килограмм'),
          (3,DATE '2025-11-03','111111111','Buyer A','555555555','Seller Y','BK001','BK001','wheat','Исполнен',30::DECIMAL(30,8),300::DECIMAL(30,8),'килограмм'),
          (4,DATE '2025-11-04','222222222','Buyer B','666666666','Seller Z','BK002','BK001','wheat','Исполнен',60::DECIMAL(30,8),1200::DECIMAL(30,8),'килограмм'),
          (5,DATE '2025-11-05','333333333','Buyer C','444444444','Seller X','BK001','BK002','wheat','Исполнен',30::DECIMAL(30,8),200::DECIMAL(30,8),'килограмм'),
          (6,DATE '2025-11-06','111111111','Buyer A','444444444','Seller X','BK001','BK002','wheat','Аннулирован(Не оплачен)',900::DECIMAL(30,8),9000::DECIMAL(30,8),'килограмм')
        ) t(deal_id,deal_date,buyer_inn,buyer_name,seller_inn,seller_name,buyer_broker,seller_broker,commodity,status,quantity,amount_uzs,unit)''')
        con.execute("CREATE TABLE brokers(code VARCHAR,name VARCHAR)")
        con.execute("INSERT INTO brokers VALUES ('BK001','Broker One'),('BK002','Broker Two')")
    monkeypatch.setenv('UZEX_DB_PATH',str(path))
    return path


def small_plan(**updates):
    values=dict(metric='analysis',analysis=AnalysisSpec(measures=['quantity','deals','distinct_sellers'],sort_by='quantity',share_by='quantity',broker_details=True),
                group='buyer',year=2025,date_from='2025-10-01',date_to='2025-12-31',commodity='wheat',physical_unit='тонна',include_cancelled=False,limit=1)
    values.update(updates);return QueryPlan(**values)


def test_ties_distinct_sellers_all_actual_brokers_and_common_denominator(small_analytics):
    body=execute_plan(small_plan(),AIQuestion(question='test'))
    assert [r['id'] for r in body['rows']]==['111111111','222222222']
    assert [r['deals'] for r in body['rows']]==[3,1]
    assert [r['distinct_sellers'] for r in body['rows']]==[2,1]
    assert all(Decimal(r['quantity'])==Decimal('.06') and Decimal(r['share_pct'])==40 for r in body['rows'])
    assert Decimal(body['provenance']['denominator']['value'])==Decimal('.15')
    assert {r['broker_code'] for r in body['sections'][1]['rows'] if r['company_inn']=='111111111'}=={'BK001','BK002'}


def test_amount_and_deal_count_are_independent_ranking_choices(small_analytics):
    for metric,expected in [('amount','222222222'),('deals','111111111')]:
        spec=AnalysisSpec(measures=[metric],sort_by=metric,share_by=metric)
        body=execute_plan(small_plan(analysis=spec,physical_unit=None),AIQuestion(question='test'))
        assert body['rows'][0]['id']==expected
        assert body['rows'][0]['quantity'] is None


def test_zero_volume_has_no_invented_percentage(small_analytics):
    with duckdb.connect(str(small_analytics)) as con:con.execute('UPDATE trades SET quantity=0')
    body=execute_plan(small_plan(),AIQuestion(question='test'))
    assert all(row['share_pct'] is None for row in body['rows'])
    assert 'знаменатель равен 0' in body['answer']


def test_missing_broker_name_preserves_observed_code_without_inventing_identity(small_analytics):
    with duckdb.connect(str(small_analytics)) as con:con.execute("DELETE FROM brokers WHERE code='BK001'")
    body=execute_plan(small_plan(),AIQuestion(question='test'))
    assert 'BK001 (название отсутствует в справочнике)' in body['answer']
    assert any(r['broker_code']=='BK001' and r['broker_name']=='' for r in body['sections'][1]['rows'])


def test_mixed_physical_units_are_not_summed_for_volume_rankings(small_analytics):
    with duckdb.connect(str(small_analytics)) as con:con.execute("UPDATE trades SET unit='литр' WHERE deal_id=5")
    body=execute_plan(small_plan(physical_unit=None),AIQuestion(question='test'))
    assert body['status']=='clarify' and body['rows']==[]


def test_generic_summary_supports_distinct_counterparties_without_a_ranking(small_analytics):
    request=AIQuestion(question='Сколько разных продавцов пшеницы было за 2025 год без аннулированных?')
    plan=QueryPlan(metric='analysis',analysis=AnalysisSpec(measures=['distinct_sellers'],sort_by='distinct_sellers'),group='none',year=2025,commodity='wheat',include_cancelled=False)
    body=execute_plan(constrain_request(request,plan),request)
    assert body['rows'][0]['distinct_sellers']==3


def test_verified_local_top_n_uses_the_requested_amount_instead_of_a_model_plan(small_analytics,monkeypatch):
    def forbidden():raise AssertionError('A verified local ranking must not depend on a model proposal')
    monkeypatch.setattr('server.ai.get_pool',forbidden)
    body=TestClient(app).post('/api/ai/ask',json={'question':'Топ-5 покупателей по сумме сделок за 2025 год'}).json()
    assert body['status']=='answer' and body['provider']['model']=='verified-analysis'
    assert body['plan']['limit']==5 and body['plan']['analysis']['sort_by']=='amount'
    assert [row['id'] for row in body['rows']]==['111111111','222222222','333333333']
    assert [Decimal(row['amount']) for row in body['rows']]==[9600,1200,200]
