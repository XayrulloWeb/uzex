import asyncio
import json
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from server.ai_models import AIQuestion, QueryPlan, language, local_chronology_plan, local_count_plan, preflight, prompt, system_prompt
from server.ai_analytics import constrain_request, execute_plan, outcome
from server.gemini import ModelUnavailable, get_pool
from server.question_checks import QuestionMismatch

router=APIRouter(prefix='/api/ai',tags=['AI analyst'])


@router.get('/status')
def status():
    pool=get_pool()
    return {'provider':'gemini','configured':pool.configured,'models':pool.models,'backup_keys':max(0,len(pool.keys)-1),'response_budget_seconds':80}


@router.post('/ask')
async def ask(request: AIQuestion):
    request.lang=language(request.question,request.lang)
    started=time.monotonic()
    absent=preflight(request)
    if absent:
        response=outcome(absent,request.lang)
        response['elapsed_ms']=round((time.monotonic()-started)*1000)
        return response
    try:
        async with asyncio.timeout(80):
            def validate(text):
                payload=json.loads(text)
                if isinstance(payload, list):
                    payload = payload[0] if payload else {}
                if isinstance(payload,dict) and payload.get('action','query')=='query' and 'metric' not in payload:
                    raise ValueError('Model must explicitly choose a metric')
                return constrain_request(request,QueryPlan.model_validate(payload))
            plan,provider=await get_pool().generate(system_prompt(),prompt(request),validate)
            response=await asyncio.to_thread(execute_plan,plan,request)
            provider['kind']='gemini'
            response['provider']=provider
            response['elapsed_ms']=round((time.monotonic()-started)*1000)
            return response
    except (ModelUnavailable,TimeoutError) as exc:
        reason=exc.reason if isinstance(exc,ModelUnavailable) else 'deadline'
        try:
            fallback=local_count_plan(request) or local_chronology_plan(request)
            if fallback: fallback=constrain_request(request,fallback)
        except (ValueError,ValidationError):
            return outcome('question_mismatch',request.lang,'clarify')
        if fallback:
            response=await asyncio.to_thread(execute_plan,fallback,request)
            response['provider']={'kind':'local','model':'verified-count' if fallback.metric=='count' else 'verified-chronology','attempts':0,'used_backup':True}
            response['elapsed_ms']=round((time.monotonic()-started)*1000)
            return response
        if reason=='question_mismatch':
            response=outcome('question_mismatch',request.lang,'clarify')
            response['elapsed_ms']=round((time.monotonic()-started)*1000)
            return response
        answer=('AI-аналитик ещё не подключён к ключам среды. Поиск и готовые отчёты доступны.' if reason=='not_configured' else 'Модели временно недоступны: исчерпан лимит или произошёл сбой. Поиск и готовые отчёты доступны. Это не означает, что ответа нет в данных.') if request.lang=='ru' else ('AI-tahlilchi muhit kalitlariga hali ulanmagan. Qidiruv va tayyor hisobotlar mavjud.' if reason=='not_configured' else 'Modellar vaqtincha mavjud emas: limit tugagan yoki nosozlik yuz bergan. Qidiruv va tayyor hisobotlar mavjud. Bu ma’lumotlarda javob yo‘qligini anglatmaydi.')
        return JSONResponse(status_code=503,content={'status':'unavailable','reason':reason,'answer':answer,'rows':[],'columns':[],'provenance':None,'elapsed_ms':round((time.monotonic()-started)*1000)})
    except QuestionMismatch:
        return outcome('question_mismatch',request.lang,'clarify')
    except (ValueError,ValidationError):
        return outcome('unknown',request.lang,'clarify')
