import asyncio
import json
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from server.ai_analytics import constrain_request,execute_plan
from server.ai_models import AIQuestion,QueryPlan
from server.app import app
from server.gemini import GeminiPool,ModelUnavailable

REF={q['id']:q['expected'] for q in json.loads((Path(__file__).parents[1]/'docs/reference-questions.json').read_text(encoding='utf-8'))['questions']}


def generated(plan=None):
    return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(plan or {'metric':'count','year':2024})}]}}]})


def test_quota_immediately_switches_model():
    calls=[]
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(429,headers={'retry-after':'60'}) if len(calls)==1 else generated()
    pool=GeminiPool(keys=['test-primary'],models=['first','second'],transport=httpx.MockTransport(handler),discover=False)
    value,meta=asyncio.run(pool.generate('system','question',QueryPlan.model_validate_json))
    assert value.year==2024 and meta=={'model':'second','attempts':2,'used_backup':True}
    assert 'first:' in calls[0] and 'second:' in calls[1]


def test_invalid_primary_key_uses_backup_without_repeating_bad_key():
    calls=[]
    def handler(request):
        key=request.headers['x-goog-api-key'];calls.append(key)
        return httpx.Response(401) if key=='test-primary' else generated()
    pool=GeminiPool(keys=['test-primary','test-backup'],models=['first','second'],transport=httpx.MockTransport(handler),discover=False)
    _,meta=asyncio.run(pool.generate('system','question',QueryPlan.model_validate_json))
    assert calls==['test-primary','test-backup'] and meta['used_backup']


def test_google_invalid_key_400_uses_backup():
    calls=[]
    def handler(request):
        key=request.headers['x-goog-api-key'];calls.append(key)
        if key=='test-primary':return httpx.Response(400,json={'error':{'status':'INVALID_ARGUMENT','details':[{'reason':'API_KEY_INVALID'}]}})
        return generated()
    pool=GeminiPool(keys=['test-primary','test-backup'],models=['first','second'],transport=httpx.MockTransport(handler),discover=False)
    _,meta=asyncio.run(pool.generate('system','question',QueryPlan.model_validate_json))
    assert calls==['test-primary','test-backup'] and meta['used_backup']


def test_timeout_switches_model():
    calls=[]
    def handler(request):
        calls.append(request.url.path)
        if len(calls)==1: raise httpx.ReadTimeout('simulated timeout',request=request)
        return generated()
    pool=GeminiPool(keys=['test-only'],models=['first','second'],transport=httpx.MockTransport(handler),discover=False)
    _,meta=asyncio.run(pool.generate('system','question',QueryPlan.model_validate_json))
    assert meta['model']=='second' and meta['attempts']==2


def test_invalid_model_json_switches_model():
    count=0
    def handler(request):
        nonlocal count
        count+=1
        if count==1: return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'not json'}]}}]})
        return generated()
    pool=GeminiPool(keys=['test-only'],models=['first','second'],transport=httpx.MockTransport(handler),discover=False)
    _,meta=asyncio.run(pool.generate('system','question',QueryPlan.model_validate_json))
    assert meta['model']=='second'


def test_all_models_exhausted_and_cooldown_prevents_retry_storm():
    calls=[]
    def handler(request):
        calls.append(request.url.path);return httpx.Response(429)
    pool=GeminiPool(keys=['test-only'],models=['first','second'],transport=httpx.MockTransport(handler),discover=False)
    for _ in range(2):
        with pytest.raises(ModelUnavailable): asyncio.run(pool.generate('s','q',QueryPlan.model_validate_json))
    assert len(calls)==2


def test_whole_request_has_deadline():
    async def handler(request):
        await asyncio.sleep(60)
        return generated()
    pool=GeminiPool(keys=['test-only'],models=['first','second'],transport=httpx.MockTransport(handler),discover=False,budget=1)
    before=time.monotonic()
    with pytest.raises(ModelUnavailable) as exc: asyncio.run(pool.generate('s','q',QueryPlan.model_validate_json))
    assert exc.value.reason=='deadline' and time.monotonic()-before<3


def test_discovery_avoids_retired_model_identifiers():
    def handler(request):
        if request.method=='GET':
            return httpx.Response(200,json={'models':[{'name':'models/available-flash','supportedGenerationMethods':['generateContent']}]})
        assert '/available-flash:' in request.url.path
        return generated()
    pool=GeminiPool(keys=['test-only'],models=['retired-flash'],transport=httpx.MockTransport(handler))
    _,meta=asyncio.run(pool.generate('s','q',QueryPlan.model_validate_json))
    assert meta['model']=='available-flash'


def test_model_discovery_can_use_backup_key():
    def handler(request):
        if request.headers['x-goog-api-key']=='test-primary':return httpx.Response(401)
        if request.method=='GET':return httpx.Response(200,json={'models':[{'name':'models/available-flash','supportedGenerationMethods':['generateContent']}]})
        assert '/available-flash:' in request.url.path
        return generated()
    pool=GeminiPool(keys=['test-primary','test-backup'],models=['retired-flash'],transport=httpx.MockTransport(handler))
    _,meta=asyncio.run(pool.generate('s','q',QueryPlan.model_validate_json))
    assert meta['model']=='available-flash' and meta['used_backup']


@pytest.mark.parametrize('model,budget',[
    ('gemini-2.5-flash',0),('gemini-2.5-flash-lite',0),('gemini-2.5-pro',128),
])
def test_thinking_budget_preserves_space_for_json_output(model,budget):
    def handler(request):
        settings=json.loads(request.content)['generationConfig']
        assert settings['thinkingConfig']['thinkingBudget']==budget
        assert settings['maxOutputTokens']==4096
        return generated()
    pool=GeminiPool(keys=['test-only'],models=[model],transport=httpx.MockTransport(handler),discover=False)
    asyncio.run(pool.generate('s','q',QueryPlan.model_validate_json))


@pytest.mark.parametrize('question',[
    'Сколько всего сделок было в 2027 году?',
    '2027-yilda jami nechta bitim bo‘lgan?',
    'Сколько всего сделок было в 2021 году?',
    'Какова чистая прибыль продавца по сделке №100001?',
])
def test_known_missing_period_or_field_never_calls_model(question,monkeypatch):
    def forbidden(): raise AssertionError('Model must not be called')
    monkeypatch.setattr('server.ai.get_pool',forbidden)
    response=TestClient(app).post('/api/ai/ask',json={'question':question})
    assert response.status_code==200 and response.json()['status']=='no_data'
    assert response.json()['rows']==[] and response.json()['provenance'] is None


def test_explicit_requested_year_cannot_be_ignored(monkeypatch):
    class Pool:
        async def generate(self,system,question,validate):
            return validate('{"metric":"count","year":null}'),{'model':'test-model','attempts':1,'used_backup':False}
    monkeypatch.setattr('server.ai.get_pool',lambda:Pool())
    response=TestClient(app).post('/api/ai/ask',json={'question':'Сколько всего сделок в 2024 году?','scope':{'year':2026}})
    assert response.status_code==200
    body=response.json()
    assert body['rows'][0]['deals']==REF['count_2024']['count']
    assert body['plan']['year']==2024


def test_empty_model_json_cannot_turn_into_default_statistics(monkeypatch):
    class Pool:
        async def generate(self,system,question,validate):
            return validate('{}'),{'model':'test-model','attempts':1,'used_backup':False}
    monkeypatch.setattr('server.ai.get_pool',lambda:Pool())
    response=TestClient(app).post('/api/ai/ask',json={'question':'Какие сведения доступны по этой компании?'})
    assert response.json()['status']=='clarify' and response.json()['rows']==[]


def test_model_error_is_not_missing_data(monkeypatch):
    class Pool:
        async def generate(self,*args): raise ModelUnavailable('all_unavailable')
    monkeypatch.setattr('server.ai.get_pool',lambda:Pool())
    response=TestClient(app).post('/api/ai/ask',json={'question':'Покажи крупнейших покупателей цемента за 2024 год'})
    assert response.status_code==503 and response.json()['status']=='unavailable'
    assert 'не означает' in response.json()['answer']


def test_simple_count_remains_correct_when_all_models_fail(monkeypatch):
    class Pool:
        async def generate(self,*args): raise ModelUnavailable('all_unavailable')
    monkeypatch.setattr('server.ai.get_pool',lambda:Pool())
    response=TestClient(app).post('/api/ai/ask',json={'question':'Сколько всего сделок в 2024 году?'})
    assert response.status_code==200
    assert response.json()['rows'][0]['deals']==106647
    assert response.json()['provider']['kind']=='local'


@pytest.mark.parametrize('field,value',[('deal_id',100007),('participant_inn','983531029'),('broker_code','BK001')])
def test_model_cannot_invent_identifiers(field,value):
    request=AIQuestion(question='Покажи статистику рынка')
    with pytest.raises(ValueError):constrain_request(request,QueryPlan(**{field:value}))


def run(plan):
    return execute_plan(QueryPlan(**plan),AIQuestion(question='Проверка точных данных'))


def test_compiled_all_period_amount_matches_csv():
    result=run({'metric':'amount'})
    assert Decimal(result['rows'][0]['amount'])==Decimal(REF['all_years_registered_amount']['amount_uzs_exact'])
    assert result['provenance']['row_count']==500000


def test_compiled_weighted_price_and_mass_units():
    result=run({'metric':'weighted_price','year':2024,'commodity':'diesel','include_cancelled':False,'contract_type':'Внутренний','physical_unit':'килограмм'})
    row=result['rows'][0]
    assert Decimal(row['quantity'])==Decimal(REF['weighted_diesel_price_2024']['quantity_kg'])
    assert Decimal(row['amount'])==Decimal(REF['weighted_diesel_price_2024']['amount_uzs'])
    assert Decimal(row['price']).quantize(Decimal('.01'))==Decimal(REF['weighted_diesel_price_2024']['price_uzs_per_kg_2dp'])


def test_compiled_largest_domestic_buyer():
    result=run({'metric':'amount','group':'buyer','year':2024,'include_cancelled':False,'contract_type':'Внутренний','limit':1})
    assert result['rows'][0]['id']==REF['largest_domestic_buyer_2024']['inn']
    assert Decimal(result['rows'][0]['amount'])==Decimal(REF['largest_domestic_buyer_2024']['amount_uzs'])


def test_broker_on_both_sides_is_counted_once():
    result=run({'metric':'count','year':2025,'broker_code':'BK001'})
    assert result['rows'][0]['deals']==REF['broker_unique_deals_2025']['distinct_deals']


def test_unknown_company_does_not_return_unrelated_statistics():
    result=run({'metric':'amount','company_name':'Global Super Trade'})
    assert result['status']=='no_data' and result['rows']==[]


def test_volume_never_adds_different_units():
    result=run({'metric':'volume'})
    assert len(result['rows'])==7
    assert len({r['unit'] for r in result['rows']})==7


def test_rate_uses_fictional_dataset_and_correct_date():
    result=run({'metric':'rate','date_from':'2026-10-30'})
    assert Decimal(result['rows'][0]['usd_rate'])==Decimal(REF['usd_rate_snapshot']['rate_uzs_per_usd'])


def test_future_explicit_interval_cannot_produce_zero():
    result=run({'metric':'count','date_from':'2027-01-01','date_to':'2027-02-01'})
    assert result['status']=='no_data' and result['rows']==[]


def test_largest_export_uses_total_amount_not_unit_price():
    result=run({'metric':'max_amount','contract_type':'Экспортный','report_currency':'USD','limit':1})
    row=result['rows'][0]
    assert row['deal_id']==547500
    assert Decimal(row['amount'])==Decimal('1683554.25')
    assert row['deal_date']=='2026-06-24'


def test_payment_year_is_not_confused_with_deal_year():
    result=run({'metric':'count','year':2024,'date_field':'payment_date'})
    # Independently counted by streaming Дата оплаты in all five original CSVs.
    assert result['rows'][0]['deals']==99351
    assert 'year(payment_date)=?' in result['provenance']['sql']


@pytest.mark.parametrize('metric,field,value',[
    ('participant','participant_inn','953758401'),
    ('broker','broker_code','BK001'),
    ('contract','contract_id','100001'),
])
def test_reference_cards_preserve_exact_lookup_evidence(metric,field,value):
    result=run({'metric':metric,field:value})
    assert result['status']=='answer'
    assert result['provenance']['parameters']==[value]
    assert any(r['value']==value for r in result['rows'])
