"""Question-to-result audit, including deliberately wrong model proposals.

Model outputs are scripted; expected facts were computed independently from the
source CSVs. These checks do not establish live Gemini interpretation accuracy.
"""
import asyncio
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from server.ai_analytics import constrain_request, execute_plan
from server.ai_models import AIQuestion, QueryPlan, preflight
from server.app import app
from server.gemini import GeminiPool, ModelUnavailable
from server.question_checks import QuestionMismatch


REFERENCES = json.loads((Path(__file__).parents[1]/'docs/reference-questions.json').read_text(encoding='utf-8'))['questions']
CANCELLED = 'Аннулирован(Не оплачен)'
PLANS = {
    'count_2024': {'metric':'count'},
    'cancelled_2024': {'metric':'count','statuses':[CANCELLED]},
    'forms_2024': {'metric':'count','group':'form'},
    'export_2024': {'metric':'amount','contract_type':'Экспортный'},
    'largest_domestic_buyer_2024': {'metric':'amount','group':'buyer','contract_type':'Внутренний','include_cancelled':False,'limit':1},
    'late_fulfilled_2024': {'metric':'late_delivery','statuses':['Исполнен']},
    'weighted_diesel_price_2024': {'metric':'weighted_price','commodity':'diesel','contract_type':'Внутренний','include_cancelled':False,'physical_unit':'килограмм'},
    'nonunit_lot_volume': {'metric':'detail','deal_id':100007},
    'usd_rate_snapshot': {'metric':'rate','date_from':'2026-10-30'},
    'export_deal_conversion': {'metric':'detail','deal_id':100024},
    'count_2025': {'metric':'count'},
    'cancelled_2025': {'metric':'count','statuses':[CANCELLED]},
    'export_2025': {'metric':'amount','contract_type':'Экспортный'},
    'all_years_count': {'metric':'count'},
    'all_years_registered_amount': {'metric':'amount'},
    'broker_unique_deals_2025': {'metric':'count','broker_code':'BK001'},
}
AUDIT_ROWS = []


@pytest.fixture(scope='module',autouse=True)
def save_question_audit():
    yield
    target=Path(__file__).parents[1]/'test-results/question-audit.json'
    target.parent.mkdir(exist_ok=True)
    report={'run_at':datetime.now(ZoneInfo('Asia/Tashkent')).isoformat(),
            'method':'Scripted model plans; real HTTP handler, independent constraint checks and real DuckDB results compared against CSV references. NOT a live Gemini or unseen-question evaluation.',
            'questions':len(AUDIT_ROWS),'passed':sum(item['passed'] for item in AUDIT_ROWS),'results':AUDIT_ROWS}
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


@pytest.mark.parametrize('item',REFERENCES,ids=lambda item:item['id'])
@pytest.mark.parametrize('lang',['ru','uz'])
def test_question_to_result_matches_independent_csv_reference(monkeypatch,item,lang):
    class ScriptedPool:
        async def generate(self,system,question,validate):
            assert item['id'] in PLANS, 'Absent facts must be rejected before any model call'
            return validate(json.dumps(PLANS[item['id']])), {'model':'scripted-test-plan','attempts':1,'used_backup':False}
    monkeypatch.setattr('server.ai.get_pool',lambda:ScriptedPool())
    response = TestClient(app).post('/api/ai/ask',json={'question':item['question_'+lang],'lang':lang})
    assert response.status_code==200
    body = response.json()
    entry={'id':item['id'],'language':lang,'question':item['question_'+lang],
           'expected':item['expected'],'status':body['status'],'actual_rows':body['rows'],
           'actual_answer':body['answer'],'passed':False}
    AUDIT_ROWS.append(entry)
    if item['id'] not in PLANS:
        assert body['status']=='no_data' and body['rows']==[]
        entry['passed']=True
        return
    assert body['status']=='answer',body
    rows,expected = body['rows'],item['expected']
    key = item['id']
    if key=='forms_2024':
        assert {row['id']:row['deals'] for row in rows}==expected
    elif key=='largest_domestic_buyer_2024':
        assert rows[0]['id']==expected['inn'] and rows[0]['label']==expected['name']
        assert Decimal(rows[0]['amount'])==Decimal(expected['amount_uzs'])
    elif key=='weighted_diesel_price_2024':
        assert rows[0]['deals']==expected['matched_deals']
        assert Decimal(rows[0]['quantity'])==Decimal(expected['quantity_kg'])
        assert Decimal(rows[0]['price']).quantize(Decimal('.01'))==Decimal(expected['price_uzs_per_kg_2dp'])
    elif key=='nonunit_lot_volume':
        assert Decimal(rows[0]['quantity'])==Decimal(expected['physical_volume'])
        assert rows[0]['unit']==expected['unit']
    elif key=='usd_rate_snapshot':
        assert Decimal(rows[0]['usd_rate'])==Decimal(expected['rate_uzs_per_usd'])
    elif key=='export_deal_conversion':
        assert Decimal(rows[0]['amount'])==Decimal(expected['amount_uzs_exact'])
    elif key=='broker_unique_deals_2025':
        assert rows[0]['deals']==expected['distinct_deals']
    else:
        if 'count' in expected: assert rows[0]['deals']==expected['count']
        if 'amount_uzs_exact' in expected: assert Decimal(rows[0]['amount'])==Decimal(expected['amount_uzs_exact'])
    entry['passed']=True


BAD_PLANS = [
    ('Сколько экспортных сделок в 2024 году?',{'metric':'count'}),
    ('2024-yilda nechta eksport bitimi bor?',{'metric':'count'}),
    ('Сумма внутренних сделок за 2024 год',{'metric':'amount','contract_type':'Экспортный'}),
    ('Сколько сделок аннулировано из-за неоплаты в 2024 году?',{'metric':'count'}),
    ('Сумма сделок за 2024 год без аннулированных',{'metric':'amount'}),
    ('Сумма сделок компании «Global Super Trade» за 2024 год',{'metric':'amount'}),
    ('Сколько сделок по дизельному топливу в 2024 году?',{'metric':'count'}),
    ('Объём пшеницы за 2024 год в тоннах',{'metric':'volume','commodity':'wheat'}),
    ('Сколько сделок оплачено в 2024 году?',{'metric':'count'}),
    ('Топ-5 покупателей по сумме сделок за 2024 год',{'metric':'count'}),
    ('Покажи контракт 100001',{'metric':'detail','deal_id':100001}),
    ('Сумма сделок со склада в Самаркандской области за 2024 год',{'metric':'amount'}),
    ('Сумма сделок за январь 2024 года',{'metric':'amount'}),
    ('Сумма сделок за 2024 год',{'metric':'amount','date_from':'2024-05-01','date_to':'2024-05-31'}),
    ('Сумма сделок с 01.01.2024 по 31.03.2024',{'metric':'amount','date_from':'2024-02-01','date_to':'2024-03-31'}),
    ('Сумма экспортных сделок за 2024 год в USD',{'metric':'amount','contract_type':'Экспортный'}),
    ('Топ-5 покупателей по сумме сделок за 2024 год',{'metric':'amount','group':'buyer','limit':10}),
    ('Сколько сделок по пшенице первого сорта?',{'metric':'count','commodity':'wheat'}),
    ('Цена бензина АИ-92 за 2024 год',{'metric':'max_price','commodity':'gasoline'}),
    ('Сумма сделок компании «Global Super Trade»',{'metric':'participant','company_name':'Global Super Trade'}),
    ('Объём пшеницы',{'metric':'count','commodity':'wheat'}),
    ('100007-raqamli bitim hajmi qancha?',{'metric':'volume'}),
    ('Сумма сделок более 1000 USD',{'metric':'amount'}),
    ('Первые 5 экспортных сделок',{'metric':'records','contract_type':'Экспортный','order':'desc','limit':5}),
    ('Первая оплата',{'metric':'first_deal','date_field':'deal_date'}),
    ('Сколько тонн пшеницы продано в 2024 году?',{'metric':'count','commodity':'wheat','physical_unit':'тонна'}),
]


@pytest.mark.parametrize('question,plan',BAD_PLANS)
def test_mismatched_model_plan_is_blocked_before_calculation(monkeypatch,question,plan):
    class WrongPool:
        async def generate(self,system,prompt,validate):
            return validate(json.dumps(plan)),{'model':'deliberately-wrong','attempts':1,'used_backup':False}
    def forbidden(*args):
        raise AssertionError('A mismatched plan must never reach SQL execution')
    monkeypatch.setattr('server.ai.get_pool',lambda:WrongPool())
    monkeypatch.setattr('server.ai.execute_plan',forbidden)
    body=TestClient(app).post('/api/ai/ask',json={'question':question}).json()
    assert body['status']=='clarify' and body['reason']=='question_mismatch'
    assert body['rows']==[] and body['provenance'] is None


@pytest.mark.parametrize('question,plan',[
    ('Сравни дизель и мазут за 2024 год',{'metric':'amount','commodity':'diesel'}),
    ('Сумма сделок покупателей из Самаркандской области',{'metric':'amount','region':'samarkand'}),
    ('Сумма сделок с опозданием',{'metric':'amount'}),
    ('Сравни компанию «Aaa Trade» и компанию «Bbb Trade»',{'metric':'amount','company_name':'Aaa Trade'}),
])
def test_unrepresentable_compound_condition_is_not_silently_dropped(question,plan):
    with pytest.raises(QuestionMismatch): constrain_request(AIQuestion(question=question),QueryPlan(**plan))


def test_request_constraints_trigger_real_adapter_model_failover():
    calls=[]
    request=AIQuestion(question='Сумма экспортных сделок за 2024 год')
    def handler(http_request):
        calls.append(http_request.url.path)
        plan={'metric':'amount'} if len(calls)==1 else {'metric':'amount','contract_type':'Экспортный'}
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(plan)}]}}]})
    pool=GeminiPool(keys=['test-only-key'],models=['model-a','model-b'],transport=httpx.MockTransport(handler),discover=False)
    plan,provider=asyncio.run(pool.generate('system','question',lambda raw:constrain_request(request,QueryPlan.model_validate_json(raw))))
    assert len(calls)==2 and provider['used_backup'] is True
    assert plan.contract_type=='Экспортный'
    assert pool._ready(0,'model-a'), 'A question mismatch is not a global outage of a model'


def test_all_semantically_wrong_models_produce_clarification(monkeypatch):
    def handler(request):
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"metric":"amount"}'}]}}]})
    pool=GeminiPool(keys=['test-only-key'],models=['model-a','model-b'],transport=httpx.MockTransport(handler),discover=False)
    monkeypatch.setattr('server.ai.get_pool',lambda:pool)
    body=TestClient(app).post('/api/ai/ask',json={'question':'Сумма экспортных сделок за 2024 год'}).json()
    assert body['status']=='clarify' and body['reason']=='question_mismatch'
    assert body['rows']==[] and body['provenance'] is None


def test_quoted_company_name_is_not_a_year_or_a_product():
    request=AIQuestion(question='Сумма сделок компании «Dizel 2027 Trade» за 2024 год')
    assert preflight(request) is None
    plan=constrain_request(request,QueryPlan(metric='amount',company_name='Dizel 2027 Trade'))
    assert plan.year==2024 and plan.commodity is None


def test_explicit_identifier_overrides_implicit_ui_scope():
    request=AIQuestion(question='Покажи сделку №100007',scope={'year':2026,'commodity':'diesel','region':'tashkent_city','status':'active'})
    plan=constrain_request(request,QueryPlan(metric='detail',deal_id=100007,year=2026))
    result=execute_plan(plan,request)
    assert result['status']=='answer' and result['rows'][0]['deal_id']==100007
    assert plan.year is None and plan.commodity is None and plan.region is None


def test_explicit_year_is_preserved_even_with_all_period_wording():
    request=AIQuestion(question='Сумма сделок за весь период 2024 года')
    plan=constrain_request(request,QueryPlan(metric='amount'))
    assert plan.year==2024


def test_whole_multi_year_period_reaches_snapshot_without_becoming_missing_data():
    request=AIQuestion(question='Сумма всех сделок за 2022–2026 годы')
    plan=constrain_request(request,QueryPlan(metric='amount',year=2024))
    result=execute_plan(plan,request)
    assert result['status']=='answer' and result['rows'][0]['deals']==500000
    assert Decimal(result['rows'][0]['amount'])==Decimal('220477157554431.7867')
    assert result['provenance']['period']['to']=='2026-10-30'


@pytest.mark.parametrize('field,value',[
    ('commodity','diesel'),('region','tashkent_city'),('statuses',['Исполнен']),
    ('form','Форвард'),('brand','M400'),('product_text','Премиум'),
    ('grade','1'),('quality_class','2'),('physical_unit','литр'),('delivered_only',True),('group','buyer'),
])
def test_unrequested_narrowing_filters_are_rejected(field,value):
    with pytest.raises(QuestionMismatch):
        constrain_request(AIQuestion(question='Сумма всех сделок за 2024 год'),QueryPlan(metric='amount',**{field:value}))


def test_company_name_cannot_override_a_conflicting_explicit_inn():
    result=execute_plan(QueryPlan(metric='amount',company_name='Zoket Invest',participant_inn='953758401'),AIQuestion(question='Проверка противоречивых реквизитов'))
    assert result['status']=='clarify' and result['rows']==[]


def test_invalid_local_fallback_scope_does_not_become_server_error(monkeypatch):
    class Pool:
        async def generate(self,*args): raise ModelUnavailable('all_unavailable')
    monkeypatch.setattr('server.ai.get_pool',lambda:Pool())
    response=TestClient(app).post('/api/ai/ask',json={'question':'Сколько сделок в 2024 году?','scope':{'commodity':'not-a-product'}})
    assert response.status_code==200 and response.json()['status']=='clarify'


@pytest.mark.parametrize('question',[
    'Когда начался экспорт?', 'С какой даты идёт экспорт?', 'Когда впервые был экспорт?',
    'Eksport qachon boshlangan?',
])
def test_first_export_rephrasings_cannot_revert_to_newest_records(question):
    request=AIQuestion(question=question,scope={'year':None})
    plan=constrain_request(request,QueryPlan(metric='records',contract_type='Экспортный',order='desc'))
    result=execute_plan(plan,request)
    assert result['rows'][0]['deal_id']==100024 and '03.01.2022' in result['answer']


@pytest.mark.parametrize('question',[
    'Первая и последняя экспортная сделка', 'Birinchi va oxirgi eksport bitimi',
])
def test_two_chronological_operations_are_not_replaced_with_one(question):
    with pytest.raises(QuestionMismatch):
        constrain_request(AIQuestion(question=question),QueryPlan(metric='records',contract_type='Экспортный'))


def test_amount_of_first_export_is_answered_in_text():
    request=AIQuestion(question='Какая сумма первой экспортной сделки за весь период?')
    plan=constrain_request(request,QueryPlan(metric='records',contract_type='Экспортный',order='desc'))
    result=execute_plan(plan,request)
    assert '467\u202f992\u202f896,26 UZS' in result['answer']


@pytest.mark.parametrize('lang',['ru','uz'])
def test_visible_calculation_context_uses_the_answer_language(lang):
    request=AIQuestion(question='Проверка',lang=lang)
    result=execute_plan(QueryPlan(metric='amount',year=2024,contract_type='Экспортный',include_cancelled=False),request)
    tags=result['interpretation']
    assert ('Eksport' if lang=='uz' else 'Экспортный') in tags
    assert ('Bekor qilinganlarsiz' if lang=='uz' else 'Без аннулированных') in tags
    assert any('2024' in tag for tag in tags)


def test_explicit_all_statuses_overrides_active_ui_filter():
    request=AIQuestion(question='Сумма сделок за 2024 год, включая все состояния',scope={'status':'active'})
    plan=constrain_request(request,QueryPlan(metric='amount',include_cancelled=True))
    assert plan.include_cancelled is True and plan.statuses==[]


@pytest.mark.parametrize('metric',['amount','participant'])
def test_conflicting_company_identifiers_never_get_silently_replaced(metric):
    result=execute_plan(QueryPlan(metric=metric,company_name='Zoket Invest',participant_inn='953758401'),AIQuestion(question='Проверка реквизитов'))
    assert result['status']=='clarify' and result['rows']==[]


def test_ai_92_brand_is_canonicalized_before_source_search():
    request=AIQuestion(question='Сколько сделок по бензину АИ92 в 2024 году?')
    plan=constrain_request(request,QueryPlan(metric='count',commodity='gasoline',brand='AI92'))
    result=execute_plan(plan,request)
    assert plan.brand=='АИ-92'
    assert result['rows'][0]['deals']>0


@pytest.mark.parametrize('question,commodity',[
    ('Сумма сделок по полиэтиленовым трубам','pipe'),
    ('Paxta yog‘i bitimlarining summasi','cotton_oil'),
    ('Сумма сделок по арматурной проволоке','wire'),
    ('Bug‘doy unining summasi','flour'),
])
def test_compound_product_names_are_not_confused_with_their_ingredients(question,commodity):
    plan=constrain_request(AIQuestion(question=question),QueryPlan(metric='amount',commodity=commodity))
    assert plan.commodity==commodity


def test_model_cannot_invent_a_year_when_ui_year_is_selected():
    plan=constrain_request(AIQuestion(question='Сумма сделок',scope={'year':2026}),QueryPlan(metric='amount',year=2024))
    assert plan.year==2026


def test_model_cannot_add_a_date_window_when_none_was_requested():
    with pytest.raises(QuestionMismatch):
        constrain_request(AIQuestion(question='Сумма сделок'),QueryPlan(metric='amount',date_from='2026-03-01',date_to='2026-03-31'))


def test_month_without_year_uses_selected_year():
    plan=constrain_request(AIQuestion(question='Сумма сделок за январь',scope={'year':2026}),QueryPlan(metric='amount',date_from='2026-01-01',date_to='2026-01-31'))
    assert plan.year==2026
    with pytest.raises(QuestionMismatch):
        constrain_request(AIQuestion(question='Сумма сделок за январь',scope={'year':2026}),QueryPlan(metric='amount',date_from='2024-01-01',date_to='2024-01-31'))


def test_rate_day_without_year_can_use_selected_year():
    plan=constrain_request(AIQuestion(question='Курс доллара на 30 октября',scope={'year':2026}),QueryPlan(metric='rate',date_from='2026-10-30'))
    assert plan.date_from==date(2026,10,30)


def test_monthly_first_deal_answer_does_not_claim_to_cover_the_entire_year():
    request=AIQuestion(question='Первый экспорт в марте 2024 года')
    plan=constrain_request(request,QueryPlan(metric='first_deal',contract_type='Экспортный',year=2024,date_from='2024-03-01',date_to='2024-03-31'))
    result=execute_plan(plan,request)
    assert '01.03.2024–31.03.2024' in result['answer']


@pytest.mark.parametrize('field,value',[
    ('commodity','diesel'),('region','samarkand'),('form','Форвард'),
    ('grade','1'),('physical_unit','литр'),('contract_type','Экспортный'),('group','buyer'),
])
def test_unrelated_history_does_not_authorize_new_filters(field,value):
    request=AIQuestion(question='Сумма всех сделок за 2024 год',history=['Когда был первый экспорт?'])
    with pytest.raises(QuestionMismatch): constrain_request(request,QueryPlan(metric='amount',**{field:value}))


def test_followup_can_retain_an_actually_mentioned_product():
    request=AIQuestion(question='А за 2025 год?',history=['Сумма сделок по дизельному топливу за 2024 год'])
    plan=constrain_request(request,QueryPlan(metric='amount',commodity='diesel'))
    assert plan.commodity=='diesel' and plan.year==2025


def test_followup_still_cannot_invent_a_form_absent_from_history():
    request=AIQuestion(question='А за 2025 год?',history=['Сумма сделок за 2024 год'])
    with pytest.raises(QuestionMismatch): constrain_request(request,QueryPlan(metric='amount',form='Форвард'))
