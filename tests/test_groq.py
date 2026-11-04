"""Official Groq fallback behind Gemini; transports are simulated."""
import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from server.ai_analytics import constrain_request
from server.ai_models import AIQuestion, QueryPlan
from server.gemini import GeminiPool, ModelUnavailable
from server.groq import GroqPool
from server.app import app


def gemini_response():
    return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"metric":"count"}'}]}}]})


def groq_response(plan=None):
    return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(plan or {'metric':'count'})}}]})


def test_gemini_is_always_tried_before_groq():
    calls=[]
    def handler(request):
        calls.append(request.url.host)
        return gemini_response()
    pool=GeminiPool(keys=['test-gemini'],models=['test-model'],groq_key='test-groq',groq_models=['fallback'],discover=False,transport=httpx.MockTransport(handler))
    result,provider=asyncio.run(pool.generate('system','question',json.loads))
    assert calls==['generativelanguage.googleapis.com'] and provider.get('kind','gemini')=='gemini'


def test_gemini_quota_switches_to_groq_with_same_validator():
    calls=[]
    request=AIQuestion(question='Сумма экспортных сделок за 2024 год')
    def handler(http_request):
        calls.append(http_request.url.host)
        if http_request.url.host=='generativelanguage.googleapis.com':return httpx.Response(429)
        assert http_request.headers['Authorization'].startswith('Bearer ')
        return groq_response({'metric':'amount','contract_type':'Экспортный'})
    pool=GeminiPool(keys=['test-gemini'],models=['gemini-test'],groq_key='test-groq',groq_models=['fallback'],discover=False,transport=httpx.MockTransport(handler))
    plan,provider=asyncio.run(pool.generate('system','question',lambda raw:constrain_request(request,QueryPlan.model_validate_json(raw))))
    assert calls==['generativelanguage.googleapis.com','api.groq.com']
    assert provider['kind']=='groq' and provider['used_backup'] and provider['attempts']==2
    assert plan.contract_type=='Экспортный'


def test_slow_gemini_cannot_consume_time_reserved_for_groq():
    calls=[]
    async def handler(request):
        calls.append(request.url.host)
        if request.url.host=='generativelanguage.googleapis.com':
            await asyncio.sleep(3)
            return gemini_response()
        return groq_response()
    pool=GeminiPool(keys=['test-gemini'],models=['slow'],groq_key='test-groq',groq_models=['fast'],discover=False,transport=httpx.MockTransport(handler),budget=1)
    started=time.monotonic()
    _,provider=asyncio.run(pool.generate('system','question',json.loads))
    assert provider['kind']=='groq' and time.monotonic()-started<1.3
    assert calls==['generativelanguage.googleapis.com','api.groq.com']


def test_groq_quota_moves_to_next_available_model():
    calls=[]
    def handler(request):
        calls.append(json.loads(request.content)['model'])
        return httpx.Response(429,headers={'retry-after':'60'}) if len(calls)==1 else groq_response()
    pool=GroqPool(key='test-only',models=['model-a','model-b'],discover=False,transport=httpx.MockTransport(handler))
    _,provider=asyncio.run(pool.generate('system','question',json.loads))
    assert calls==['model-a','model-b'] and provider['model']=='model-b'
    assert pool.ready('model-a') is False


def test_groq_cannot_bypass_question_constraints():
    calls=[]
    request=AIQuestion(question='Сумма экспортных сделок за 2024 год')
    def handler(http_request):
        calls.append(http_request.url.path)
        return groq_response({'metric':'amount'} if len(calls)==1 else {'metric':'amount','contract_type':'Экспортный'})
    pool=GroqPool(key='test-only',models=['bad','good'],discover=False,transport=httpx.MockTransport(handler))
    plan,provider=asyncio.run(pool.generate('system','question',lambda raw:constrain_request(request,QueryPlan.model_validate_json(raw))))
    assert plan.contract_type=='Экспортный' and provider['model']=='good'


def test_groq_bad_key_is_not_repeated_for_each_model():
    calls=[]
    def handler(request):calls.append(request.url.path);return httpx.Response(401)
    pool=GroqPool(key='test-only',models=['model-a','model-b'],discover=False,transport=httpx.MockTransport(handler))
    for _ in range(2):
        with pytest.raises(ModelUnavailable):asyncio.run(pool.generate('system','question',json.loads))
    assert len(calls)==1


def test_groq_model_discovery_drops_unavailable_and_audio_models():
    calls=[]
    def handler(request):
        if request.url.path.endswith('/models'):
            return httpx.Response(200,json={'data':[{'id':'new-text'},{'id':'whisper-audio'},{'id':'bad id'}]})
        calls.append(json.loads(request.content)['model'])
        return groq_response()
    pool=GroqPool(key='test-only',models=['retired-model'],transport=httpx.MockTransport(handler))
    asyncio.run(pool.generate('system','question',json.loads))
    assert calls==['new-text'] and pool.models==['new-text']


def test_standard_groq_key_alias_can_work_without_gemini(monkeypatch):
    for name in ['UZEX_GROQ_KEY','UZEX_GEMINI_KEY_PRIMARY','UZEX_GEMINI_KEY_BACKUP','UZEX_GEMINI_KEY_3','UZEX_GEMINI_KEY_4','UZEX_GEMINI_KEYS']:
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv('GROQ_API_KEY','test-only')
    calls=[]
    def handler(request):calls.append(request.url.host);return groq_response()
    pool=GeminiPool(discover=False,groq_models=['fallback'],transport=httpx.MockTransport(handler))
    _,provider=asyncio.run(pool.generate('system','question',json.loads))
    assert pool.configured and calls==['api.groq.com'] and provider['kind']=='groq'


def test_all_exhausted_providers_return_unavailable():
    pool=GeminiPool(keys=['test-gemini'],models=['model'],groq_key='test-groq',groq_models=['fallback'],discover=False,transport=httpx.MockTransport(lambda request:httpx.Response(429)))
    with pytest.raises(ModelUnavailable) as error:
        asyncio.run(pool.generate('system','question',json.loads))
    assert error.value.reason=='all_unavailable'


def test_groq_failover_answer_is_computed_from_actual_database(monkeypatch):
    def handler(request):
        if request.url.host=='generativelanguage.googleapis.com':return httpx.Response(429)
        return groq_response({'metric':'amount','contract_type':'Экспортный','year':2024})
    pool=GeminiPool(keys=['test-gemini'],models=['test-primary'],groq_key='test-groq',groq_models=['test-fallback'],discover=False,transport=httpx.MockTransport(handler))
    monkeypatch.setattr('server.ai.get_pool',lambda:pool)
    body=TestClient(app).post('/api/ai/ask',json={'question':'Сумма экспортных сделок за 2024 год'}).json()
    assert body['provider']['kind']=='groq' and body['status']=='answer'
    assert body['rows'][0]['deals']==1327
    from decimal import Decimal
    assert Decimal(body['rows'][0]['amount'])==Decimal('2621400340149.8958')
