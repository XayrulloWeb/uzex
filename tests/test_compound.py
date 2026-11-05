"""Common-scope compound questions, independently checked against raw CSVs."""
import asyncio
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from server.ai_models import AIQuestion,QueryPlan
from server.ai_analytics import constrain_request,execute_plan
from server.app import app
from server.compound import local_compound_plan,requested_metrics
from server.question_checks import QuestionMismatch,validate_question
from server.gemini import GeminiPool

REF=json.loads((Path(__file__).parents[1]/'docs/compound-reference.json').read_text(encoding='utf-8'))['years']
QUESTION='2022-yilda jami bitimlar soni va birinchi bitim tafsilotlari?'


def calculate(question,scope=None):
    request=AIQuestion(question=question,scope=scope or {'year':None})
    plan=local_compound_plan(request)
    assert plan is not None
    return execute_plan(constrain_request(request,plan),request)


@pytest.mark.parametrize('question,lang',[(QUESTION,'uz'),('Сколько всего сделок за 2022 год и первая сделка?','ru')])
def test_actual_screenshot_question_answers_both_parts_without_model_dependency(monkeypatch,question,lang):
    def forbidden():raise AssertionError('Supported compound query must not depend on a provider')
    monkeypatch.setattr('server.ai.get_pool',forbidden)
    response=TestClient(app).post('/api/ai/ask',json={'question':question,'lang':lang,'scope':{'year':None}})
    body=response.json()
    assert response.status_code==200 and body['status']=='answer'
    assert body['provider']['model']=='verified-compound'
    count,first=body['sections']
    assert count['rows'][0]['deals']==84299
    row=first['rows'][0]
    assert row['deal_id']==100001 and row['deal_date']=='2022-01-03' and row['deal_time']=='10:04:49'
    assert Decimal(row['quantity'])==79720 and Decimal(row['amount'])==Decimal('304547938.4')
    assert '84\u202f299' in body['answer'] and '100001' in body['answer']
    assert len(body['provenance']['operations'])==2


@pytest.mark.parametrize('year',range(2022,2027))
@pytest.mark.parametrize('template,expected',[
    ('За {year} год количество сделок и общая сумма',['count','amount']),
    ('{year}-yilda jami bitimlar soni va oxirgi bitim tafsilotlari',['count','last_deal']),
    ('За {year} год первая и последняя сделка',['first_deal','last_deal']),
    ('За {year} год количество сделок и общая сумма и первая сделка и последняя сделка',['count','amount','first_deal','last_deal']),
])
def test_compound_operation_combinations_match_independent_csv_reference(year,template,expected):
    body=calculate(template.format(year=year),{'year':2024 if year!=2024 else 2025})
    reference=REF[str(year)]['all']
    assert [s['metric'] for s in body['sections']]==expected
    for section in body['sections']:
        row=section['rows'][0]
        if section['metric']=='count':assert row['deals']==reference['count']
        elif section['metric']=='amount':assert Decimal(row['amount'])==Decimal(reference['amount_uzs'])
        else:
            item=reference['first' if section['metric']=='first_deal' else 'last']
            assert row['deal_id']==item['deal_id']
            assert row['deal_date']+'T'+row['deal_time']==item['timestamp']


def test_ui_status_filter_is_shared_by_every_operation():
    body=calculate(QUESTION,{'year':2026,'status':'active'})
    reference=REF['2022']['without_cancelled']
    assert body['sections'][0]['rows'][0]['deals']==reference['count']
    assert body['sections'][1]['rows'][0]['deal_id']==reference['first']['deal_id']
    assert all(not s['plan']['include_cancelled'] for s in body['sections'])


@pytest.mark.parametrize('metrics',[[],['amount'],['first_deal','last_deal']])
def test_guard_rejects_omitted_or_unrequested_operations(metrics):
    request=AIQuestion(question=QUESTION)
    plan=QueryPlan(metric='count',additional_metrics=metrics,year=2022)
    with pytest.raises(QuestionMismatch):validate_question(request,plan)


@pytest.mark.parametrize('question',[
    'Сколько сделок за 2022 год и первая сделка за 2023 год',
    'Сколько всего сделок за 2022 год и первый экспорт',
    'Сколько сделок с цементом и первая сделка с хлопком за 2022 год',
])
def test_differently_scoped_subsets_are_not_silently_merged(question):
    request=AIQuestion(question=question)
    assert local_compound_plan(request) is None
    with pytest.raises(QuestionMismatch):validate_question(request,QueryPlan(metric='count',additional_metrics=['first_deal']))


@pytest.mark.parametrize('extra',[' и средняя цена',' и физический объем',' компании «Global Trade»',' первого сорта'])
def test_bounded_local_compound_parser_does_not_discard_unknown_qualifiers(extra):
    assert local_compound_plan(AIQuestion(question='Сколько сделок и первая сделка за 2022 год'+extra)) is None


def test_model_path_can_supply_compound_plan_for_shared_warehouse_filter(monkeypatch):
    question='Количество сделок со склада в Самарканде и первая сделка со склада в Самарканде за 2022 год'
    assert local_compound_plan(AIQuestion(question=question)) is None
    class Pool:
        async def generate(self,system,prompt,validate):
            return validate(json.dumps({'metric':'count','additional_metrics':['first_deal'],'year':2022,'region':'samarkand'})),{'kind':'gemini','model':'scripted-plan','attempts':1,'used_backup':False}
    monkeypatch.setattr('server.ai.get_pool',lambda:Pool())
    body=TestClient(app).post('/api/ai/ask',json={'question':question}).json()
    assert body['status']=='answer' and len(body['sections'])==2
    assert body['sections'][0]['rows'][0]['deals']>0
    assert all(s['plan']['region']=='samarkand' for s in body['sections'])
    assert all('samarkand' in s['provenance']['parameters'] for s in body['sections'])


def test_empty_subset_can_answer_zero_count_without_fabricating_a_first_trade():
    question='Количество сделок экспорта хлопка и первый экспорт хлопка за 2026 год'
    request=AIQuestion(question=question)
    plan=constrain_request(request,QueryPlan(metric='count',additional_metrics=['first_deal'],year=2026,commodity='cotton',contract_type='Экспортный'))
    body=execute_plan(plan,request)
    assert body['sections'][0]['rows'][0]['deals']==0
    assert body['sections'][1]['status']=='no_data' and body['sections'][1]['rows']==[]


def test_first_trade_amount_remains_a_detail_not_a_total_of_all_trades():
    assert requested_metrics('Какая сумма первой сделки за 2022 год?')==['first_deal']
    assert requested_metrics('Сколько была сумма первой сделки за 2022 год?')==['first_deal']


def test_different_subsets_get_specific_supported_scope_explanation_before_provider(monkeypatch):
    def forbidden():raise AssertionError('Different subsets must not become a silently merged total')
    monkeypatch.setattr('server.ai.get_pool',forbidden)
    body=TestClient(app).post('/api/ai/ask',json={'question':'Сколько всего сделок за 2022 год и первый экспорт'}).json()
    assert body['reason']=='compound_scope' and body['rows']==[]
    assert 'разным выборкам' in body['answer']


def test_model_discovery_runs_at_first_call_on_a_recently_booted_host(monkeypatch):
    calls=[]
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200,json={'models':[{'name':'models/available-flash','supportedGenerationMethods':['generateContent']}]})
    monkeypatch.setattr('server.gemini.time.monotonic',lambda:10.0)
    pool=GeminiPool(keys=['test-only'],models=['retired-flash'],transport=httpx.MockTransport(handler))
    async def check():
        async with httpx.AsyncClient(transport=pool.transport) as client:
            await pool._discover(client,20)
            await pool._discover(client,20)
    asyncio.run(check())
    assert calls==['GET'] and pool.models==['available-flash']
