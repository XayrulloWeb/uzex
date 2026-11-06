import asyncio
import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from server.ai_models import AIQuestion, QueryPlan, language, local_chronology_plan, local_count_plan, local_ratio_plan, preflight, prompt, system_prompt
from server.ai_analytics import constrain_request, execute_plan, outcome
from server.gemini import ModelUnavailable, get_pool
from server.question_checks import QuestionMismatch
from server.monthly import local_monthly_plan
from server.compound import local_compound_plan, requested_metrics, shared_scope
from server.audit_log import get_recent_questions, log_question
from server.analysis_reports import analysis_intent, local_analysis_plan
from server.export_deep_report import generate_export_deep_report, is_export_deep_query
from server.deep_reports import generate_deep_report, is_deep_report_query

router=APIRouter(prefix='/api/ai',tags=['AI analyst'])


@router.get('/status')
def status():
    pool=get_pool()
    return {'provider':'gemini+groq' if pool.groq.configured else 'gemini','configured':pool.configured,
            'models':pool.models+(pool.groq.models if pool.groq.configured else []),
            'providers':[{'provider':'gemini','configured':bool(pool.keys),'models':pool.models},
                         {'provider':'groq','configured':pool.groq.configured,'models':pool.groq.models}],
            'backup_keys':max(0,len(pool.keys)-1),'response_budget_seconds':80}


@router.get('/questions-log')
def questions_log(limit: int = 50):
    entries = get_recent_questions(limit)
    return {'count': len(entries), 'questions': entries}


@router.post('/ask')
async def ask(request: AIQuestion, raw_request: Request = None):
    request.lang=language(request.question,request.lang)
    started=time.monotonic()
    client_ip = None
    if raw_request is not None:
        try:
            client_ip = raw_request.headers.get('x-forwarded-for', '').split(',')[0].strip() or (raw_request.client.host if raw_request.client else None)
        except Exception:
            pass

    def _finish(res):
        try:
            is_dict = isinstance(res, dict)
            log_question(
                question=request.question,
                lang=request.lang,
                status=res.get('status', 'unknown') if is_dict else 'unavailable',
                answer=res.get('answer', '') if is_dict else '',
                provider=res.get('provider') if is_dict else None,
                elapsed_ms=res.get('elapsed_ms', 0) if is_dict else round((time.monotonic()-started)*1000),
                reason=res.get('reason') if is_dict else None,
                client_ip=client_ip
            )
        except Exception:
            pass
        return res

    absent=preflight(request)
    if absent:
        response=outcome(absent,request.lang)
        response['elapsed_ms']=round((time.monotonic()-started)*1000)
        return _finish(response)
    if not analysis_intent(request.question) and len(requested_metrics(request.question))>1 and not shared_scope(request):
        response=outcome('compound_scope',request.lang,'clarify')
        response['elapsed_ms']=round((time.monotonic()-started)*1000)
        return _finish(response)
    try:
        async with asyncio.timeout(80):
            trusted=local_analysis_plan(request) or local_compound_plan(request) or local_monthly_plan(request) or local_ratio_plan(request)
            if trusted:
                plan=constrain_request(request,trusted)
                response=await asyncio.to_thread(execute_plan,plan,request)
                response['provider']={'kind':'local','model':'verified-analysis' if plan.analysis else 'verified-compound' if plan.additional_metrics else 'verified-monthly-report' if plan.month_comparison else 'verified-ratio' if plan.metric=='share' else 'verified-comparison','attempts':0,'used_backup':False}
                response['elapsed_ms']=round((time.monotonic()-started)*1000)
                return _finish(response)
            if is_export_deep_query(request.question):
                deep_resp = await asyncio.to_thread(generate_export_deep_report, request)
                if deep_resp:
                    deep_resp['elapsed_ms'] = round((time.monotonic()-started)*1000)
                    return _finish(deep_resp)
            if is_deep_report_query(request.question):
                deep_resp = await asyncio.to_thread(generate_deep_report, request)
                if deep_resp:
                    deep_resp['elapsed_ms'] = round((time.monotonic()-started)*1000)
                    return _finish(deep_resp)
            def validate(text):
                payload=json.loads(text)
                if isinstance(payload, list):
                    if len(payload)!=1: raise QuestionMismatch('multiple_plans')
                    payload = payload[0]
                if isinstance(payload,dict) and payload.get('action','query')=='query' and 'metric' not in payload:
                    raise ValueError('Model must explicitly choose a metric')
                return constrain_request(request,QueryPlan.model_validate(payload))
            plan,provider=await get_pool().generate(system_prompt(),prompt(request),validate)
            response=await asyncio.to_thread(execute_plan,plan,request)
            provider['kind']=provider.get('kind','gemini')
            response['provider']=provider
            response['elapsed_ms']=round((time.monotonic()-started)*1000)
            return _finish(response)
    except (ModelUnavailable,TimeoutError) as exc:
        reason=exc.reason if isinstance(exc,ModelUnavailable) else 'deadline'
        if reason=='question_mismatch':
            response=outcome('question_mismatch',request.lang,'clarify')
            response['elapsed_ms']=round((time.monotonic()-started)*1000)
            return _finish(response)
        try:
            fallback=local_ratio_plan(request) or local_count_plan(request) or local_chronology_plan(request)
            if fallback: fallback=constrain_request(request,fallback)
        except (ValueError,ValidationError):
            return _finish(outcome('question_mismatch',request.lang,'clarify'))
        if fallback:
            response=await asyncio.to_thread(execute_plan,fallback,request)
            response['provider']={'kind':'local','model':'verified-count' if fallback.metric=='count' else 'verified-chronology','attempts':0,'used_backup':True}
            response['elapsed_ms']=round((time.monotonic()-started)*1000)
            return _finish(response)
        answer=('AI-аналитик ещё не подключён к ключам среды. Поиск и готовые отчёты доступны.' if reason=='not_configured' else 'Модели временно недоступны: исчерпан лимит или произошёл сбой. Поиск и готовые отчёты доступны. Это не означает, что ответа нет в данных.') if request.lang=='ru' else ('AI-tahlilchi muhit kalitlariga hali ulanmagan. Qidiruv va tayyor hisobotlar mavjud.' if reason=='not_configured' else 'Modellar vaqtincha mavjud emas: limit tugagan yoki nosozlik yuz bergan. Qidiruv va tayyor hisobotlar mavjud. Bu ma’lumotlarda javob yo‘qligini anglatmaydi.')
        return _finish(JSONResponse(status_code=503,content={'status':'unavailable','reason':reason,'answer':answer,'rows':[],'columns':[],'provenance':None,'elapsed_ms':round((time.monotonic()-started)*1000)}))
    except QuestionMismatch:
        return _finish(outcome('question_mismatch',request.lang,'clarify'))
    except (ValueError,ValidationError):
        return _finish(outcome('unknown',request.lang,'clarify'))
