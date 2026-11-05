"""Composable group statistics, ranks, distinct counterparties and market shares."""
from __future__ import annotations

import calendar
import re
from datetime import date
from decimal import Decimal, localcontext

from server.catalog import COMMODITIES, REGIONS, SNAPSHOT, commodity_label, region_label, normalize, normalized_grade
from server.db import query
from server.ratios import percentage


def analysis_intent(text):
    q=normalize(text)
    return bool(re.search(r'топ|\btop(?=\s|[-\d])|наибольш|больше\s+всего|крупнейш|лидер|наименьш|меньше\s+всего|минимальн|eng\s+(?:ko\'p|yirik|katta|kam)',q))


def quarter_number(text):
    q=normalize(text)
    match=re.search(r'\b([1-4])(?:\s*-?\s*(?:й|м|ом|го))?\s*[- ]?\s*(?:квартал\w*|chora[kg]\w*)',q)
    if match:return int(match.group(1))
    match=re.search(r'\b(iv|iii|ii|i)\s+квартал\w*',q)
    if match:return {'i':1,'ii':2,'iii':3,'iv':4}[match.group(1)]
    match=re.search(r'\b(перв\w*|втор\w*|трет\w*|четверт\w*)\s+квартал\w*',q)
    if match:return next(value for prefix,value in [('перв',1),('втор',2),('трет',3),('четверт',4)] if match.group(1).startswith(prefix))
    match=re.search(r'\b(birinchi|ikkinchi|uchinchi|to\'rtinchi)\s+chora[kg]\w*',q)
    return {'birinchi':1,'ikkinchi':2,'uchinchi':3,"to'rtinchi":4}[match.group(1)] if match else None


def requirements(text):
    """Independently recognize requested output fields, not calculated values."""
    from server.ai_models import share_intent
    from server.question_checks import question_text
    q=question_text(text)
    roles={'buyer':r'покупател|закуп|xaridor|xarid\s+qil|sotib\s+ol',
           'seller':r'продав[це]|продаж|sotuvch|sotgan|sotish','broker':r'брокер|broker'}
    mentioned=[(m.start(),role) for role,pattern in roles.items() if (m:=re.search(pattern,q))]
    group=min(mentioned)[1] if mentioned else None
    if not analysis_intent(q):
        group='none'
        for candidate,pattern in {'buyer':r'по\s+покупател|xaridorlar\s+bo\'yicha','seller':r'по\s+продавц|sotuvchilar\s+bo\'yicha',
                                  'month':r'по\s+месяц|помесяч|oylar\s+bo\'yicha','year':r'по\s+годам|yillar\s+bo\'yicha',
                                  'region':r'по\s+регион','commodity':r'по\s+товар','broker':r'по\s+брокер|brokerlar\s+bo\'yicha'}.items():
            if re.search(pattern,q):group=candidate
    quantity=bool(re.search(r'объем|hajm|tonna|тонн|kilogram|килограмм|литр|litr',q))
    amount=bool(re.search(r'сумм|оборот|стоимост|summa|aylanma|qiymat',q))
    deals=bool(re.search(r'нечта|nechta\s+bitim|сколько\s+сдел|число\s+сдел|количество\s+сдел|bitimlar\s+soni',q))
    unique_sellers=bool(re.search(r'(?:разн\w*|уникальн\w*)\s+продав|число\s+продав|(?:nechta|qancha)(?:\s+turli)?\s+sotuvchi',q))
    unique_buyers=bool(re.search(r'(?:разн\w*|уникальн\w*)\s+покупател|число\s+покупател|(?:nechta|qancha)(?:\s+turli)?\s+xaridor',q))
    weighted=bool(re.search(r'средневзвеш|o\'rtacha\s+tortilgan',q))
    measures=[key for key,present in [('quantity',quantity),('amount',amount),('deals',deals),('distinct_sellers',unique_sellers),('distinct_buyers',unique_buyers),('weighted_price',weighted)] if present]
    rank=None
    if re.search(r'по\s+(?:физическ\w*\s+)?объем|(?:наибольш|наименьш|максимальн|минимальн)\w*\s+объем|eng\s+(?:ko\'p|kam|katta)\s+hajm|hajm\w*\s+(?:bo\'yicha|xarid|sotib)|больше\s+всего\s+(?:тонн|килограмм)',q):rank='quantity'
    elif re.search(r'по\s+(?:сумм|оборот|стоимост)|(?:наибольш|наименьш|максимальн|минимальн)\w*\s+(?:сумм|оборот)|eng\s+ko\'p\s+(?:summa|qiymat)|summa\w*\s+bo\'yicha',q):rank='amount'
    elif re.search(r'по\s+(?:числу|количеству)\s+сдел|eng\s+ko\'p\s+bitim|bitimlar\s+soni\s+bo\'yicha',q):rank='deals'
    elif sum([quantity,amount,deals])==1:rank=next(key for key in ['quantity','amount','deals'] if key in measures)
    share=None
    if share_intent(q):
        share='quantity' if quantity else 'amount' if amount else 'deals' if deals else rank
    return {'group':group,'measures':measures,'sort_by':rank,'share_by':share,'order':'asc' if re.search(r'наименьш|меньше\s+всего|минимальн|eng\s+kam',q) else 'desc',
            'share_requested':share_intent(q),'broker_details':bool(re.search(r'брокер|broker',q)) and group in ['buyer','seller']}


def period_for_question(request):
    from server.question_checks import MONTHS, calendar_mentions, question_text, QuestionMismatch
    q=question_text(request.question)
    years=sorted({int(y) for y in re.findall(r'(?<!\d)((?:19|20)\d{2})(?!\d)',q)})
    if len(years)>1:return None
    year=years[0] if years else request.scope.year
    if year is None:return None
    dates,months=calendar_mentions(q)
    quarter=quarter_number(q)
    if quarter:
        first=(quarter-1)*3+1;last=first+2
        if months and (min(months)<first or max(months)>last):raise QuestionMismatch('quarter_months_conflict')
        return date(year,first,1),date(year,last,calendar.monthrange(year,last)[1])
    if len(dates)==2:return min(dates),max(dates)
    if len(dates)==1:return dates[0],dates[0]
    if len(months)==1:
        m=months[0];return date(year,m,1),date(year,m,calendar.monthrange(year,m)[1])
    if len(months)>1:
        hits=sorted((m.start(),m.end()) for pattern in MONTHS for m in re.finditer(r'\b(?:'+pattern+r')\b',q))
        if len(hits)==2 and re.search(r'[–—-]|\bпо\b|gacha',q[hits[0][1]:hits[1][0]]):
            first,last=min(months),max(months)
            return date(year,first,1),date(year,last,calendar.monthrange(year,last)[1])
    return None


def validate_analysis(request,plan):
    from server.question_checks import QuestionMismatch
    required=requirements(request.question)
    if required['group'] and plan.group!=required['group']:raise QuestionMismatch('analysis_group')
    if not set(required['measures'])<=set(plan.analysis.measures):raise QuestionMismatch('analysis_missing_measures')
    if required['sort_by'] and plan.analysis.sort_by!=required['sort_by']:raise QuestionMismatch('analysis_ranking_measure')
    if analysis_intent(request.question) and plan.order!=required['order']:raise QuestionMismatch('analysis_order')
    if required['share_requested'] and plan.analysis.share_by!=required['share_by']:raise QuestionMismatch('analysis_share_measure')
    if not required['share_requested'] and plan.analysis.share_by:raise QuestionMismatch('unrequested_share')
    if required['broker_details']!=plan.analysis.broker_details:raise QuestionMismatch('analysis_brokers')
    if period:=period_for_question(request):
        if plan.date_from!=period[0] or plan.date_to!=period[1]:raise QuestionMismatch('analysis_period')
    else:
        from server.question_checks import calendar_mentions
        if len(calendar_mentions(normalize(request.question))[1])>1:raise QuestionMismatch('analysis_unsupported_calendar')


def local_analysis_plan(request):
    """Catalogue-driven grammar; unfamiliar qualifiers require model validation."""
    from server.ai_models import AnalysisSpec, QueryPlan
    from server.question_checks import COMPANY_PATTERN, _products, _mentions, MONTHS, question_text
    q=question_text(request.question)
    required=requirements(q)
    if not analysis_intent(q) or required['group'] in [None,'none'] or required['sort_by'] is None:return None
    if re.search(COMPANY_PATTERN,request.question,re.I) or re.search(r'(?<!\d)\d{6,}(?!\d)',q):return None
    products=_products(q);regions=_mentions(q,REGIONS)
    if len(products)>1 or len(regions)>1:return None
    remainder=re.sub(r'(?<!\d)(?:19|20)\d{2}(?!\d)',' ',q)
    remainder=re.sub(r'\b[1-4]\s*[- ]?\s*(?:квартал\w*|chora[kg]\w*)',' ',remainder)
    remainder=re.sub(r'\b[1-4]\s*-(?:й|м|ом|го)\s+квартал\w*|\b(?:iv|iii|ii|i)\s+квартал\w*|\b(?:birinchi|ikkinchi|uchinchi|to\'rtinchi)\s+chora[kg]\w*',' ',remainder)
    remainder=re.sub(r'\b(?:перв\w*|втор\w*|трет\w*|четверт\w*)\s+квартал\w*',' ',remainder)
    remainder=re.sub(r'\b[1-5]\s*[- ]?\s*(?:сорт\w*|sort\w*)',' ',remainder)
    top=re.search(r'\b(?:топ|top)\s*[- ]?\s*(\d{1,2})\b',q)
    if top:remainder=re.sub(r'\b(?:топ|top)\s*[- ]?\s*\d{1,2}\b',' ',remainder)
    for pattern in MONTHS:remainder=re.sub(r'\b(?:'+pattern+r')\b',' ',remainder)
    for item in COMMODITIES+REGIONS:
        for alias in sorted([item[2],item[3],*item[-1]],key=len,reverse=True):
            alias=normalize(alias).strip()
            if alias:remainder=re.sub(r'(?<!\w)'+re.escape(alias)+(r'\w*' if len(alias)>=4 else r'(?!\w)'),' ',remainder)
    allowed=(r'за|в|на|по|из|и|его|ее|их|с|со|от|без|все[хм]?|общ\w*|эт\w*|год\w*|период\w*|состояни\w*|'
             r'найди\w*|покажи\w*|кто|како[йея]|назови\w*|компани\w*|инн|названи\w*|покупател\w*|продав[це]\w*|'
             r'крупнейш\w*|наибольш\w*|наименьш\w*|минимальн\w*|лидер\w*|больше|меньше|всего|купил\w*|закуп\w*|продал\w*|объем\w*|сумм\w*|оборот\w*|'
             r'сдел\w*|количеств\w*|число|сколько|разн\w*|уникальн\w*|брокер\w*|дол[яиюе]\w*|процент\w*|составля\w*|'
             r'тонн\w*|килограмм\w*|литр\w*|спот\w*|аннулирован\w*|исключая|топ|'
             r'yil\w*|bitim\w*|orasidan|bekor|qilingan\w*|eng|ko\'p|kam|yirik|katta|hajm\w*|xarid\w*|qilgan\w*|qil\w*|'
             r'kompaniya\w*|top\w*|uning|stir|raqam\w*|nom\w*|tonna\w*|kilogram\w*|litr\w*|nechta|turli|sotuvch\w*|xaridor\w*|'
             r'broker\w*|kim\w*|hamda|ulush\w*|shu|davr\w*|umumiy|necha|foiz\w*|tashkil|ayt\w*|va|spot\w*|'
             r'summa\w*|qiymat\w*|aylanma\w*|jami|soni|bo\'yicha|so\'m\w*|uzs|usd|dollarda|o\'rtacha|tortilgan|'
             r'hisobga|olma\w*|tashqari|barcha|holat\w*|sotib|olgan\w*|sotgan\w*|sotish|долларах|сумах')
    words=re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*|\d+",remainder)
    if any(not re.fullmatch(allowed,word) for word in words):return None
    scope=request.scope
    measures=required['measures'] or [required['sort_by']]
    if required['sort_by'] not in measures:measures.append(required['sort_by'])
    physical='тонна' if re.search(r'тонн|tonna',q) else 'килограмм' if re.search(r'килограмм|kilogram',q) else 'литр' if re.search(r'литр|litr',q) else None
    without=bool(re.search(r'без\s+аннулир|исключая\s+аннулир|bekor\s+qilingan\w*siz\b|bekor\s+qilingan\w*\s+tashqari|hisobga\s+olma',q))
    form='Спот' if re.search(r'\bспот|\bspot',q) else None
    period=period_for_question(request)
    return QueryPlan(metric='analysis',analysis=AnalysisSpec(measures=measures,sort_by=required['sort_by'],share_by=required['share_by'],broker_details=required['broker_details']),
                     group=required['group'],year=scope.year,date_from=period[0] if period else None,date_to=period[1] if period else None,
                     commodity=next(iter(products)) if products else scope.commodity,region=next(iter(regions)) if regions else scope.region,
                     grade=normalized_grade(q) or None,form=form,physical_unit=physical,include_cancelled=not without if without else scope.status!='active',
                     statuses=['Исполнен'] if scope.status=='fulfilled' else [],order=required['order'],limit=int(top.group(1)) if top else 10 if re.search(r'\bтоп\b|\btop\b',q) else 1)


def analysis_result(plan,lang,condition,parameters,amount,quantity,unit,total):
    from server.ai_analytics import result,column,outcome
    from server.ai_models import money
    spec=plan.analysis
    physical_needed=any(key in spec.measures for key in ['quantity','weighted_price'])
    if physical_needed and unit=='unit':
        units=query('SELECT DISTINCT unit FROM trades WHERE '+condition,parameters)
        if len(units)!=1:return outcome('need_product',lang,'clarify')
        display_unit=units[0]['unit']
    else:display_unit=plan.physical_unit
    dims={'buyer':('buyer_inn','buyer_name'),'seller':('seller_inn','seller_name'),
          'broker':('broker_key','broker_name'),'commodity':('commodity','commodity'),'region':('region','region'),
          'month':("strftime("+plan.date_field+",'%Y-%m')",)*2,'year':('year('+plan.date_field+')',)*2,
          'status':('status','status'),'form':('form','form'),'category':('category','category'),'auction':('auction','auction')}
    source='trades'
    if plan.group=='broker':
        role='t.buyer_broker=b.code' if plan.role=='buyer' else 't.seller_broker=b.code' if plan.role=='seller' else '(t.buyer_broker=b.code OR t.seller_broker=b.code)'
        source='(SELECT t.*,b.code AS broker_key,b.name AS broker_name FROM trades t JOIN brokers b ON '+role+')'
    if plan.group=='none':prefix='';group=''
    else:
        key,label=dims[plan.group];prefix=key+' AS id,'+label+' AS label,';group=' GROUP BY '+','.join(dict.fromkeys([key,label]))
    quantity_aggregate='sum('+quantity+')' if physical_needed else 'NULL'
    sql=f'''SELECT {prefix}count(*) AS deals,sum({amount}) AS amount,{quantity_aggregate} AS quantity,
        count(DISTINCT seller_inn) AS distinct_sellers,count(DISTINCT buyer_inn) AS distinct_buyers
        FROM {source} WHERE {condition}{group}'''
    rows=query(sql,parameters)
    denominator_sql=f'SELECT count(*) AS deals,sum({amount}) AS amount,{quantity_aggregate} AS quantity FROM trades WHERE '+condition
    denominator=query(denominator_sql,parameters)[0]
    for row in rows:
        if plan.group=='commodity':row['label']=commodity_label(row['id'],lang)
        if plan.group=='region':row['label']=region_label(row['id'],lang)
        with localcontext() as context:
            context.prec=38
            row['weighted_price']=format(Decimal(row['amount'])/Decimal(row['quantity']),'f') if row['quantity'] is not None and Decimal(row['quantity']) else None
        if spec.share_by:row['share_pct']=percentage(row[spec.share_by],denominator[spec.share_by])
    direction=Decimal(-1) if plan.order=='desc' else Decimal(1)
    rows.sort(key=lambda row:(row[spec.sort_by] is None,direction*Decimal(str(row[spec.sort_by] or 0)),str(row.get('id',''))))
    if rows and rows[0][spec.sort_by] is None:
        return outcome('need_product',lang,'clarify')
    if plan.limit==1 and rows:
        best=Decimal(str(rows[0][spec.sort_by]));winners=[r for r in rows if r[spec.sort_by] is not None and Decimal(str(r[spec.sort_by]))==best]
        rows=winners[:50]
    else:winners=[];rows=rows[:plan.limit]
    labels={'deals':('Сделки','Bitimlar'),'amount':('Сумма','Summa'),'quantity':('Объём','Hajm'),
            'distinct_sellers':('Разных продавцов','Turli sotuvchilar'),'distinct_buyers':('Разных покупателей','Turli xaridorlar'),
            'weighted_price':('Средневзвешенная цена','O‘rtacha tortilgan narx')}
    def measure_unit(key):return plan.report_currency if key=='amount' else display_unit if key=='quantity' else plan.report_currency+' / '+str(display_unit) if key=='weighted_price' else None
    columns=[]
    if plan.group!='none':
        columns=[{'key':'id','label':'ИНН / код' if lang=='ru' else 'STIR / kod','kind':'text'},column('label',lang)]
    for key in spec.measures:
        columns.append({'key':key,'label':labels[key][lang=='uz'],'kind':'integer' if key in ['deals','distinct_sellers','distinct_buyers'] else 'decimal',**({'unit':measure_unit(key)} if measure_unit(key) else {})})
    if spec.share_by:columns.append({'key':'share_pct','label':'Доля' if lang=='ru' else 'Ulush','kind':'percent','unit':'%'})
    lines=[]
    if len(winners)>1:lines.append((('Одинаковое максимальное значение у ' if plan.order=='desc' else 'Одинаковое минимальное значение у ')+str(len(winners))+' компаний.' if lang=='ru' else str(len(winners))+' ta kompaniyada bir xil '+('eng katta' if plan.order=='desc' else 'eng kichik')+' qiymat.'))
    if len(winners)>50:lines.append('Показано 50 компаний из '+str(len(winners))+'.' if lang=='ru' else str(len(winners))+' ta kompaniyadan 50 tasi ko‘rsatilgan.')
    for row in rows[:5]:
        name=str(row.get('label','Итого' if lang=='ru' else 'Jami'));identifier=str(row.get('id',''))
        facts=[]
        for key in spec.measures:
            value=row.get(key)
            facts.append(labels[key][lang=='uz']+' — '+(money(value,0 if key in ['deals','distinct_sellers','distinct_buyers'] else 4 if key=='quantity' else 2) if value is not None else '—')+(' '+measure_unit(key) if measure_unit(key) else ''))
        if spec.share_by:facts.append(('Доля' if lang=='ru' else 'Ulush')+' — '+(money(row['share_pct'],4)+'%' if row['share_pct'] is not None else '—'))
        identity=((' (ИНН / код '+identifier+')' if lang=='ru' else ' (STIR / kod '+identifier+')') if identifier else '')
        lines.append(name+identity+': '+ '; '.join(facts)+'.')
    if spec.share_by:
        lines.append(('Знаменатель доли: весь объём той же выборки до ограничения рейтинга — ' if lang=='ru' else 'Ulush maxraji: reyting cheklovidan oldingi ayni tanlanmaning jami — ')+money(denominator[spec.share_by],4 if spec.share_by=='quantity' else 2 if spec.share_by=='amount' else 0)+(' '+str(measure_unit(spec.share_by)) if measure_unit(spec.share_by) else '')+'.')
        if not Decimal(str(denominator[spec.share_by] or 0)):
            lines.append('Доля не определена: знаменатель равен 0.' if lang=='ru' else 'Ulush aniqlanmagan: maxraj 0.')
    snapshot=date.fromisoformat(SNAPSHOT)
    if plan.year==snapshot.year and (plan.date_to is None or plan.date_to>=snapshot):
        lines.append('Данные за 2026 год доступны только по 30.10.2026; результат рассчитан по доступной части периода.' if lang=='ru' else '2026-yil ma’lumotlari faqat 30.10.2026 gacha mavjud; natija davrning mavjud qismi bo‘yicha hisoblangan.')
    response=result('\n'.join(lines),rows,columns,sql,parameters,total['count'],plan,{'from':total['first_date'],'to':total['last_date']},lang=lang)
    response['provenance']['denominator']={'measure':spec.share_by,'value':denominator.get(spec.share_by) if spec.share_by else None,'sql':denominator_sql,'parameters':parameters}
    response['provenance']['method']='Each requested aggregate uses the same filtered source. Distinct counterparties use COUNT(DISTINCT INN). USD converted at each deal date; kilograms/tonnes converted before aggregation. Exact Decimal ranking and share = group / entire filtered source × 100 before top-N. A zero denominator has no defined share.'
    response['provenance']['operations']=[{'title':'Основной расчёт' if lang=='ru' else 'Asosiy hisob','sql':sql,'parameters':parameters,'row_count':total['count']}]
    if spec.share_by:response['provenance']['operations'].append({'title':'Знаменатель доли' if lang=='ru' else 'Ulush maxraji','sql':denominator_sql,'parameters':parameters,'row_count':total['count']})
    if spec.broker_details and rows:
        party='buyer_inn' if plan.group=='buyer' else 'seller_inn';broker='buyer_broker' if plan.group=='buyer' else 'seller_broker'
        ids=[str(row['id']) for row in rows]
        unit_group=',unit' if unit=='unit' else ''
        broker_sql=f'''SELECT {party} AS company_inn,{broker} AS broker_code,coalesce(b.name,'') AS broker_name,count(*) AS deals,sum({quantity}) AS quantity,{unit} AS unit
            FROM trades LEFT JOIN brokers b ON {broker}=b.code WHERE {condition} AND {party} IN ({','.join('?' for _ in ids)})
            GROUP BY {party},{broker},b.name{unit_group} ORDER BY company_inn,quantity DESC,broker_code'''
        broker_params=parameters+ids;brokers=query(broker_sql,broker_params)
        for row in rows:
            actual=[r for r in brokers if r['company_inn']==str(row['id'])]
            names='; '.join(r['broker_code']+(' — '+r['broker_name'] if r['broker_name'] else (' (название отсутствует в справочнике)' if lang=='ru' else ' (ma’lumotnomada nomi yo‘q)')) for r in actual)
            response['answer']+='\n'+str(row['label'])+': '+('брокеры покупателя' if lang=='ru' and plan.group=='buyer' else 'брокеры продавца' if lang=='ru' else 'xaridor brokerlari' if plan.group=='buyer' else 'sotuvchi brokerlari')+' — '+names+'.'
        response['sections']=[{'title':'Результаты' if lang=='ru' else 'Natijalar','rows':rows,'columns':columns},
                              {'title':'Брокеры в выбранных сделках' if lang=='ru' else 'Tanlangan bitimlardagi brokerlar','rows':brokers,
                               'columns':[{'key':'company_inn','label':'ИНН' if lang=='ru' else 'STIR','kind':'text'},{'key':'broker_code','label':'Код брокера' if lang=='ru' else 'Broker kodi','kind':'text'},{'key':'broker_name','label':'Брокер' if lang=='ru' else 'Broker','kind':'text'},column('deals',lang,'integer'),column('quantity',lang,'decimal'),column('unit',lang)]}]
        response['provenance']['operations'].append({'title':'Брокеры' if lang=='ru' else 'Brokerlar','sql':broker_sql,'parameters':broker_params,'row_count':sum(r['deals'] for r in brokers)})
    return response
