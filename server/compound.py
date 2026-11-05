"""Several verified operations over one explicitly shared trade scope."""
from __future__ import annotations

import re

from server.catalog import REGIONS


def requested_metrics(text):
    from server.ai_models import chronological_metrics
    from server.question_checks import question_text
    q=question_text(text)
    metrics=[]
    if re.search(r'сколько(?:\s+(?:всего|биржевых|экспортных|внутренних|было|заключено|зарегистрировано|уникальных)){0,3}\s+сдел|(?:число|количество)\s+(?:всех\s+)?сдел|nechta(?:\s+noyob)?\s+bitim|bitimlar\s+soni',q):
        metrics.append('count')
    clauses=re.split(r'\s+(?:и|va|hamda|а\s+также)\s+|[;,]',q)
    # A sum of the first trade is a detail, not the sum of all trades.
    if any(re.search(r'\bсумм\w*|\bоборот\w*|\bsumma\w*|\baylanma\w*',part) and not chronological_metrics(part) for part in clauses):
        metrics.append('amount')
    metrics+=chronological_metrics(q)
    return metrics


def shared_scope(request):
    """Avoid merging differently qualified subsets into one common plan."""
    from server.question_checks import _mentions, _products, calendar_mentions, question_text
    q=question_text(request.question)
    if len(set(re.findall(r'(?<!\d)((?:19|20)\d{2})(?!\d)',q)))>1: return False
    dates,months=calendar_mentions(q)
    if len(months)>1: return False
    clauses=re.split(r'\s+(?:и|va|hamda|а\s+также)\s+|[;,]',q)
    relevant=[part for part in clauses if requested_metrics(part)]
    if len(relevant)<2: return True
    def filters(part):
        return (_products(part),_mentions(part,REGIONS),bool(re.search(r'экспорт|eksport',part)),
                bool(re.search(r'внутренн|ichki',part)),bool(re.search(r'аннулир|bekor',part)))
    return all(filters(part)==filters(relevant[0]) for part in relevant[1:])


def local_compound_plan(request):
    from server.ai_models import QueryPlan
    from server.question_checks import question_text
    q=question_text(request.question)
    metrics=requested_metrics(q)
    if len(metrics)<2 or not shared_scope(request): return None
    remainder=re.sub(r'(?<!\d)(?:19|20)\d{2}(?!\d)',' ',q)
    allowed=(r'и|а|также|в|за|на|по|с|к|от|во|сколько|всего|общее|общая|общую|общий|покажи|покажите|посчитай|назови|'
             r'количество|число|сумм\w*|оборот\w*|сдел\w*|год\w*|был\w*|когда|како[йея]|какая|какую|перв\w*|последн\w*|'
             r'ранн\w*|поздн\w*|сам\w*|зарегистрированн\w*|детал\w*|подробност\w*|сведения|весь|все|период|время|'
             r'jami|nechta|bitim\w*|soni|va|hamda|birinchi|ilk|oxirgi|so\'nggi|eng|erta|kech|tafsilot\w*|'
             r'summa\w*|aylanma\w*|yil\w*|qachon|qaysi|qanday|bo\'lgan|ko\'rsat\w*|butun|davr\w*|barcha|'
             r'uzs|usd|сумах|сумы|долларах|so\'m\w*|dollarda')
    words=re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*|\d+",remainder)
    if any(not re.fullmatch(allowed,word) for word in words): return None
    scope=request.scope
    return QueryPlan(metric=metrics[0],additional_metrics=metrics[1:],year=scope.year,region=scope.region,commodity=scope.commodity,
                     include_cancelled=scope.status!='active',statuses=['Исполнен'] if scope.status=='fulfilled' else [])


def validate_operations(request,plan):
    from server.question_checks import QuestionMismatch
    metrics=requested_metrics(request.question)
    if not plan.additional_metrics:
        if len(metrics)>1 and not plan.month_comparison and plan.metric!='share':
            raise QuestionMismatch('missing_compound_operation')
        return
    actual=[plan.metric]+plan.additional_metrics
    if len(actual)!=len(set(actual)) or set(actual)!=set(metrics):
        raise QuestionMismatch('compound_operations')
    if not shared_scope(request): raise QuestionMismatch('compound_scope')
    if plan.group!='none' or plan.comparison or plan.month_comparison:
        raise QuestionMismatch('compound_group')


def execute_compound(plan,request):
    from server.ai_analytics import execute_plan
    from server.db import serial
    titles={'count':('Количество сделок','Bitimlar soni'),'amount':('Сумма сделок','Bitimlar summasi'),
            'first_deal':('Первая сделка','Birinchi bitim'),'last_deal':('Последняя сделка','Oxirgi bitim')}
    sections=[]
    for metric in [plan.metric]+plan.additional_metrics:
        operation=plan.model_copy(deep=True,update={'metric':metric,'additional_metrics':[],
                    'order':'asc' if metric=='first_deal' else 'desc','limit':1 if metric in ['first_deal','last_deal'] else plan.limit})
        section=execute_plan(operation,request)
        section['title']=titles[metric][request.lang=='uz']
        section['metric']=metric
        sections.append(section)
    # No factual summary from a model: each paragraph is rendered by its operation.
    response=dict(sections[0])
    response['status']='answer' if any(s['status']=='answer' for s in sections) else sections[0]['status']
    response['answer']='\n'.join(s['answer'] for s in sections)
    response['sections']=sections
    response['rows']=[];response['columns']=[]
    response['plan']=plan.model_dump(mode='json')
    response['interpretation']=list(dict.fromkeys(label for s in sections for label in s.get('interpretation',[])))
    provenances=[s['provenance'] for s in sections if s.get('provenance')]
    response['provenance']=dict(provenances[0]) if provenances else None
    if response['provenance']:
        response['provenance']['operations']=[{'title':s['title'],**s['provenance']} for s in sections if s.get('provenance')]
        response['provenance']['method']='\n'.join(dict.fromkeys(p['method'] for p in provenances))
    return serial(response)
