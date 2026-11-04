"""Independent checks for explicit question constraints before any SQL runs.

This is deliberately not a second free-form parser. Recognized constraints must
be represented in the typed plan; a mismatch rejects the plan instead of
silently answering a different question. Unrecognized language still needs live
model evaluation and is not certified by these checks.
"""
from __future__ import annotations

import calendar
import re
from datetime import date

from server.catalog import CANCELLED, COMMODITIES, REGIONS, SNAPSHOT, STATUS_UZ, normalize, normalized_grade


class QuestionMismatch(ValueError):
    def __init__(self, field):
        self.field = field
        super().__init__('Question constraint mismatch: '+field)


COMPANY_PATTERN = r'(?:компани\w*|корхон\w*|kompaniya\w*|korxona\w*|покупател\w*|продавц\w*|xaridor\w*|sotuvchi\w*)\s+[«"]([^»"]{2,160})[»"]'


def question_text(text):
    """Names are identifiers, not years/products/regions mentioned as filters."""
    q = normalize(text.replace('№',' '))
    return re.sub(COMPANY_PATTERN,lambda m:re.sub(r'[«"].*?[»"]',' ',m.group(0)),q,flags=re.I)


def _mentions(text, vocabulary):
    matches = []
    for item in vocabulary:
        for alias in [item[2], item[3], *item[-1]]:
            alias = normalize(alias).strip()
            suffix = r'\w*' if len(alias.split())>1 or len(alias)>=4 else r'(?!\w)'
            for match in re.finditer(r'(?<!\w)'+re.escape(alias)+suffix, text):
                matches.append((match.start(), match.end(), item[0]))
    # A longer complete product phrase takes precedence over its ingredients.
    return {key for start,end,key in matches if not any(
        other_key!=key and other_start<=start and end<=other_end and other_end-other_start>end-start
        for other_start,other_end,other_key in matches)}


def _products(text):
    products = _mentions(text, COMMODITIES)
    compounds = {
        'pipe': (r'полиэтилен\w*\s+труб\w*|polietilen\w*\s+quvur\w*', 'polyethylene'),
        'wire': (r'арматурн\w*\s+проволок\w*|armatura\w*\s+sim\w*', 'rebar'),
        'yarn': (r'paxta\s+ip\w*', 'cotton'),
    }
    for key,(pattern,ingredient) in compounds.items():
        if re.search(pattern,text):
            without_compound = re.sub(pattern,' ',text)
            products.add(key)
            if ingredient not in _mentions(without_compound,COMMODITIES): products.discard(ingredient)
    return products


MONTHS = [
    r'январ\w*|yanvar\w*', r'феврал\w*|fevral\w*', r'март\w*|mart\w*',
    r'апрел\w*|aprel\w*', r'ма[йяе]|may', r'июн\w*|iyun\w*',
    r'июл\w*|iyul\w*', r'август\w*|avgust\w*', r'сентябр\w*|sentabr\w*|sentyabr\w*',
    r'октябр\w*|oktabr\w*|oktyabr\w*', r'ноябр\w*|noyabr\w*', r'декабр\w*|dekabr\w*',
]


def calendar_mentions(text):
    dates = []
    for match in re.finditer(r'(?<!\d)(?:(\d{4})-(\d{2})-(\d{2})|(\d{1,2})\.(\d{1,2})\.(\d{4}))(?!\d)',text):
        y,m,d = match.group(1,2,3) if match.group(1) else match.group(6,5,4)
        try:
            dates.append(date(int(y),int(m),int(d)))
        except ValueError:
            raise QuestionMismatch('date') from None
    months = [index for index,pattern in enumerate(MONTHS,1) if re.search(r'\b(?:'+pattern+r')\b',text)]
    for month in months:
        pattern = MONTHS[month-1]
        ru = re.finditer(r'(?<!\d)(\d{1,2})\s+(?:'+pattern+r')\s+((?:19|20)\d{2})(?!\d)',text)
        uz = re.finditer(r'(?<!\d)((?:19|20)\d{2})-?yil\s+(\d{1,2})[-\s]+(?:'+pattern+r')\b',text)
        for match,reverse in [(m,False) for m in ru]+[(m,True) for m in uz]:
            year,day = match.group(1,2) if reverse else match.group(2,1)
            try:
                value = date(int(year),month,int(day))
            except ValueError:
                raise QuestionMismatch('date') from None
            if value not in dates: dates.append(value)
    return dates,months


def relative_period(text):
    return bool(re.search(r'сегодня|вчера|(?:прошл\w*|позапрошл\w*|предыдущ\w*|эт\w*|последн\w*|текущ\w*)\s+(?:\d+\s+)?(?:год\w*|месяц\w*|недел\w*|дн\w*)|bugun|kecha|o\'tgan|shu\s+(?:yil|oy)|joriy',text))


def _calendar_checks(q, plan, require, scope_year):
    years = sorted({int(value) for value in re.findall(r'(?<!\d)((?:19|20)\d{2})(?!\d)',q)})
    dates,months = calendar_mentions(q)
    if not years and months and not relative_period(q):
        if scope_year is None: raise QuestionMismatch('month_without_year')
        years = [scope_year]
        if len(months)==1:
            day = re.search(r'(?<!\d)(\d{1,2})\s+(?:'+MONTHS[months[0]-1]+r')\b',q)
            if day:
                try: dates=[date(scope_year,months[0],int(day.group(1)))]
                except ValueError: raise QuestionMismatch('date') from None
    if len(dates)==2:
        require('date_from',min(dates)); require('date_to',max(dates))
    elif len(dates)==1:
        if plan.metric=='rate':
            require('date_from',dates[0])
            if plan.date_to not in [None,dates[0]]: raise QuestionMismatch('date_to')
        elif re.search(r'\b(?:за|на)\s+\d|\b(?:sanasi|sanasidagi)\b',q):
            require('date_from',dates[0]); require('date_to',dates[0])
    elif len(months)==1 and len(years)==1:
        month,year = months[0],years[0]
        require('date_from',date(year,month,1))
        end = date(year,month,calendar.monthrange(year,month)[1])
        if plan.date_to != end and not (end>date.fromisoformat(SNAPSHOT) and plan.date_to==date.fromisoformat(SNAPSHOT)):
            raise QuestionMismatch('date_to')
    elif not months and len(years)==1 and re.search(r'(?:в|за)\s+(?:весь\s+)?20\d{2}|20\d{2}-?yil',q):
        if not re.search(r'квартал|полугоди|месяц|chorak|yarim|oy\b',q):
            year = years[0]
            if plan.date_from not in [None,date(year,1,1)]: raise QuestionMismatch('date_from')
            allowed = [None,date(year,12,31)]
            if year==2026: allowed.append(date.fromisoformat(SNAPSHOT))
            if plan.date_to not in allowed: raise QuestionMismatch('date_to')
    if len(years)>1 and not dates and not months:
        require('date_from',date(min(years),1,1)); require('date_to',date(max(years),12,31))
        if re.search(r'сравн|taqqosla|solishtir',q): require('group','year')


def validate_question(request, plan):
    if plan.action!='query': return
    from server.ai_models import chronological_metric, requested_share_basis, share_intent

    def require(field, expected):
        actual=getattr(plan,field)
        target=plan.share_target if plan.metric=='share' else None
        if target and target.dimension==('status' if field=='statuses' else field):
            actual=[target.value] if field=='statuses' else target.value
        if actual!=expected: raise QuestionMismatch(field)

    q = question_text(request.question)
    followup = bool(request.history and (re.search(r'^(?:а\b|теперь\b|также\b|для\s+(?:этого|него)|endi\b|shu\b|o\'sha\b)',q) or re.fullmatch(r'(?:за|в)\s+20\d{2}(?:\s+году)?[?!.]*',q)))
    previous = question_text(' '.join(request.history)) if followup else ''
    has_previous = lambda value: bool(previous and normalize(str(value)).strip('"«»') in previous)
    if re.search(r'\b(?:более|менее|больше|меньше|свыше|не\s+менее|не\s+более)\s+\d|\d[\d\s.,]*\s*(?:mln|million|so\'m|dollar|tonna)\w*\s+(?:ortiq|ko\'p|kam)',q):
        raise QuestionMismatch('numeric_threshold_not_supported')
    companies = re.findall(COMPANY_PATTERN,request.question,flags=re.I)
    if len(set(map(normalize,companies)))>1: raise QuestionMismatch('multiple_companies')
    if companies:
        if not plan.company_name or normalize(plan.company_name.strip('"«»'))!=normalize(companies[0]):
            raise QuestionMismatch('company_name')
    elif plan.company_name and not has_previous(plan.company_name) and normalize(plan.company_name.strip('"«»')) not in q:
        raise QuestionMismatch('unexpected_company')

    # An identifier must be used with the entity type stated by the user.
    identifiers = {
        'contract_id': r'(?:контракт\w*|shartnoma\w*)\s*(?:№|raqami\s*)?\s*(\d{6})(?!\d)|(?<!\d)(\d{6})-raqamli\s+shartnoma',
        'deal_id': r'(?:сделк\w*|bitim\w*)\s*(?:№|raqami\s*)?\s*(\d{6,9})(?!\d)|(?<!\d)(\d{6,9})-raqamli\s+bitim',
        'participant_inn': r'(?:инн|stir)\s*[:№]?\s*(\d{9})(?!\d)',
        'broker_code': r'\b(bk\d{3})\b',
    }
    for field,pattern in identifiers.items():
        values = {next(value for value in match.groups() if value is not None) for match in re.finditer(pattern,q)}
        if len(values)>1: raise QuestionMismatch('multiple_'+field)
        if values:
            value = values.pop()
            require(field,int(value) if field=='deal_id' else value.upper() if field=='broker_code' else value)
        elif (value:=getattr(plan,field)) is not None:
            if str(value).casefold() not in q and not has_previous(value): raise QuestionMismatch('unexpected_'+field)
    if plan.metric in ['participant','broker','contract']:
        if re.search(r'сумм|оборот|объем|сколько|число|количество|покажи\s+сделки|summ|aylanma|hajm|nechta|bitimlar\s+soni',q):
            raise QuestionMismatch('reference_instead_of_calculation')
        return

    products = _products(q)
    if len(products)>1: raise QuestionMismatch('multiple_commodities')
    if plan.metric=='share':
        if not share_intent(q) or plan.share_target is None: raise QuestionMismatch('share_definition')
        target=plan.share_target
        if target.dimension=='commodity' and target.value not in products: raise QuestionMismatch('share_target')
        if target.dimension=='region' and target.value not in _mentions(q,REGIONS): raise QuestionMismatch('share_target')
        if target.dimension=='contract_type' and not re.search(r'экспорт|eksport' if target.value=='Экспортный' else r'внутренн|ichki',q):
            raise QuestionMismatch('share_target')
        require('share_basis',requested_share_basis(q))
    if products: require('commodity',next(iter(products)))
    elif request.scope.commodity and not plan.deal_id: require('commodity',request.scope.commodity)
    elif plan.commodity and plan.commodity not in _products(previous): raise QuestionMismatch('unexpected_commodity')
    grade = normalized_grade(q)
    if grade: require('grade',grade)
    elif plan.grade and plan.grade!=normalized_grade(previous): raise QuestionMismatch('unexpected_grade')
    classes = re.findall(r'\b([12345]|iii|ii|iv|i|v)\s*[- ]?\s*(?:класс|klass)\b',q)
    if classes:
        aliases = {'i':'1','ii':'2','iii':'3','iv':'4','v':'5'}
        values = {aliases.get(value,value) for value in classes}
        if len(values)>1: raise QuestionMismatch('multiple_classes')
        require('quality_class',values.pop())
    elif plan.quality_class and not (previous and re.search(r'\b'+re.escape(plan.quality_class)+r'\s*[- ]?\s*(?:класс|klass)\b',previous)):
        raise QuestionMismatch('unexpected_class')
    brand = re.search(r'\b(?:аи|ai)[-– ]?(\d{2,3})\b',q)
    if brand:
        if not plan.brand or re.sub(r'[^\d]','',plan.brand)!=brand.group(1): raise QuestionMismatch('brand')
    evidence = q+' '+previous
    if plan.brand:
        compact = lambda text: re.sub(r'[\W_]+','',normalize(text)).replace('ai','аи')
        if compact(plan.brand) not in compact(evidence): raise QuestionMismatch('unexpected_brand')
    if plan.product_text and normalize(plan.product_text) not in evidence:
        raise QuestionMismatch('unexpected_product_text')
    forms = {form for form,pattern in {'Спот':r'спот|spot','Форвард':r'форвард|forvard|forward','Фьючерс':r'фьючерс|fyuchers|f\'yuchers'}.items() if re.search(r'\b(?:'+pattern+r')\w*',q)}
    if len(forms)>1: raise QuestionMismatch('multiple_forms')
    if forms: require('form',forms.pop())
    elif plan.form and normalize(plan.form) not in previous: raise QuestionMismatch('unexpected_form')

    regions = _mentions(q,REGIONS)
    if 'tashkent_region' in regions and re.search(r'ташкент\w*\s+област|toshkent\s+viloyat|tashkent\s+region',q):
        regions.discard('tashkent_city')
    if len(regions)>1: raise QuestionMismatch('multiple_regions')
    if regions:
        if re.search(r'(?:покупател\w*|продавц\w*|компани\w*|xaridor\w*|sotuvchi\w*)\s+(?:из|в|dan)\b',q):
            raise QuestionMismatch('participant_region_not_warehouse')
        require('region',next(iter(regions)))
    elif request.scope.region and not plan.deal_id: require('region',request.scope.region)
    elif plan.region and plan.region not in _mentions(previous,REGIONS): raise QuestionMismatch('unexpected_region')

    export = bool(re.search(r'\b(?:экспорт\w*|eksport\w*)',q))
    domestic = bool(re.search(r'\b(?:внутренн\w*|ichki)',q))
    if export and re.search(r'не[- ]?экспорт|eksport\s+bo\'lmagan',q): export,domestic=False,True
    if export and domestic:
        if re.search(r'сравн|taqqosla|solishtir',q): raise QuestionMismatch('contract_type_comparison')
        require('contract_type',None)
    elif export: require('contract_type','Экспортный')
    elif domestic: require('contract_type','Внутренний')
    elif plan.contract_type and not re.search(r'экспорт|eksport' if plan.contract_type=='Экспортный' else r'внутренн|ichki',previous):
        raise QuestionMismatch('unexpected_contract_type')

    without = bool(re.search(r'без\s+(?:учета\s+)?аннулир|исключ\w*\s+аннулир|не\s+учитыв\w*\s+аннулир|bekor\s+qilingan\w*(?:\s+bitim\w*)?\s+hisobga\s+olma|bekor\s+qilingan\w*\s+tashqari',q))
    including = bool(re.search(r'включая\s+аннулир|с\s+учетом\s+аннулир|bekor\s+qilingan\w*\s+ham',q))
    all_statuses = bool(re.search(r'все\s+состояни|barcha\s+holat|hamma\s+holat',q))
    cancelled = bool(re.search(r'аннулир|bekor\s+qilingan',q)) and not without and not including
    partial = bool(re.search(r'частично\s+исполн|исполнен\s*\(частично\)|qisman\s+bajaril',q))
    fulfilled = not partial and bool(re.search(r'(?:полностью\s+)?исполненн|to\'liq\s+bajaril',q))
    wanted_status = [CANCELLED] if cancelled else ['Исполнен(Частично)'] if partial else ['Исполнен'] if fulfilled else None
    named_statuses = [status for status,uz in STATUS_UZ.items() if any(re.search(
        r'(?:состояни\w*|статус\w*|holat\w*)\s*[«"]?'+re.escape(normalize(label))+r'(?!\w)',q
    ) for label in [status,uz])]
    if len(named_statuses)>1: raise QuestionMismatch('combined_statuses')
    if named_statuses: wanted_status=named_statuses
    if plan.metric=='share' and plan.share_target.dimension=='status' and not wanted_status: raise QuestionMismatch('share_target')
    if wanted_status:
        if including or all_statuses: raise QuestionMismatch('combined_statuses')
        require('statuses',wanted_status)
        if cancelled: require('include_cancelled',True)
    elif including or all_statuses:
        if set(plan.statuses) >= set(STATUS_UZ.keys()): plan.statuses = []
        require('include_cancelled',True); require('statuses',[])
    elif without or (request.scope.status=='active' and not plan.deal_id):
        require('include_cancelled',False); require('statuses',[])
    elif request.scope.status=='fulfilled' and not plan.deal_id: require('statuses',['Исполнен'])
    elif plan.statuses: raise QuestionMismatch('unexpected_statuses')

    paid = bool(re.search(r'по\s+дате\s+оплат|дата\s+оплаты|оплачен[оы]\s+в\s+20\d{2}|оплатили\s+в\s+20\d{2}|to\'lov\s+sanasi|(?:первая|последняя|ранняя|поздняя)\s+оплата|(?:birinchi|oxirgi|ilk)\s+to\'lov',q))
    delivered = bool(re.search(r'по\s+дате\s+постав|дата\s+поставки|поставлен[оы]\s+в\s+20\d{2}|yetkazib\s+berish\s+sanasi|(?:первая|последняя|ранняя|поздняя)\s+поставка',q))
    if paid and delivered: raise QuestionMismatch('multiple_date_fields')
    if paid: require('date_field','payment_date')
    elif delivered: require('date_field','delivery_date')
    elif plan.date_field!='deal_date' and not re.search(r'оплат|постав|to\'lov|yetkaz',q):
        raise QuestionMismatch('unexpected_date_field')

    units = {
        'килограмм':r'килограмм\w*|kilogram\w*|kg|кг', 'тонна':r'тонн\w*|tonna\w*',
        'литр':r'литр\w*|litr\w*', 'штука':r'штук\w*|dona\w*',
    }
    found_units = {unit for unit,pattern in units.items() if re.search(r'\b(?:'+pattern+r')\b',q)}
    if re.search(r'квадратн\w*\s+метр|кв\.?\s*метр|\bm2\b|kvadrat\s+metr',q): found_units.add('кв.метр')
    elif re.search(r'кубическ\w*\s+метр|куб\.?\s*метр|\bm3\b|kub\s+metr',q): found_units.add('куб.метр')
    elif re.search(r'\bметр\w*|\bmetr\w*',q): found_units.add('метр')
    if len(found_units)>1: raise QuestionMismatch('multiple_units')
    if len(found_units)==1: require('physical_unit',found_units.pop())
    elif plan.physical_unit and not has_previous(plan.physical_unit): raise QuestionMismatch('unexpected_unit')
    actual_delivery = bool(re.search(r'фактически\s+поставл|поставленн\w*\s+объем|yetkazilgan\s+hajm|yetkazib\s+berilgan\s+hajm',q))
    if actual_delivery: require('delivered_only',True)
    elif plan.delivered_only and not re.search(r'постав|yetkaz',evidence): raise QuestionMismatch('unexpected_delivered_only')

    temporal = chronological_metric(q)
    weighted = bool(re.search(r'средневзвеш|o\'rtacha\s+tortilgan',q))
    price = bool(re.search(r'\bцен\w*|\bnarx\w*',q))
    amount = bool(re.search(r'\bсумм\w*|\bоборот\w*|\bsumma\w*|\baylanma\w*',q))
    volume = bool(re.search(r'\bобъем\w*|\bhajm\w*|сколько(?:\s+(?:всего|было))?\s+(?:тонн|килограмм|литр|штук|метр)|qancha\s+(?:tonna|kilogram|litr|dona)',q))
    counting = bool(re.search(r'сколько(?:\s+\w+){0,3}\s+сдел|в\s+скольких.*?сделк|число\s+сдел|количество\s+сдел|nechta(?:\s+noyob)?\s+bitim|bitimlar\s+soni',q))
    late = bool(re.search(r'с\s+опозданием|позже\s+срока|kech\s+yetkaz',q))
    if plan.metric=='share' and (volume or late): raise QuestionMismatch('unsupported_share_basis_or_filter')
    if late and (amount or volume or price): raise QuestionMismatch('late_calculation_not_supported')
    if share_intent(q): require('metric','share')
    elif temporal: require('metric',temporal)
    elif weighted: require('metric','weighted_price')
    elif price and re.search(r'максималь|сам\w*\s+высок|eng\s+yuqori',q): require('metric','max_price')
    elif price and re.search(r'минималь|сам\w*\s+низк|eng\s+past',q): require('metric','min_price')
    elif re.search(r'крупнейшая\s+(?:экспортная\s+|внутренняя\s+)?сделка|самая\s+большая\s+(?:экспортная\s+)?сделка',q): require('metric','max_amount')
    elif amount and not price and not (plan.metric=='detail' and plan.deal_id): require('metric','amount')
    elif volume and not price and not (plan.metric=='detail' and plan.deal_id): require('metric','volume')
    elif late: require('metric','late_delivery')
    elif counting: require('metric','count')

    ranked = bool(re.search(r'\bтоп|\btop|крупнейш|наибольш|лидер|eng\s+yirik|eng\s+ko\'p',q))
    individual_deal = bool(re.search(r'(?:крупнейш\w*|наибольш\w*)\s+(?:экспортн\w*\s+|внутренн\w*\s+)?сделк',q))
    if ranked:
        buyer = bool(re.search(r'покупател|xaridor',q))
        seller = bool(re.search(r'продав[це]|sotuvchi',q))
        if buyer!=seller and not individual_deal: require('group','buyer' if buyer else 'seller')
        require('order','desc')
    limit = re.search(r'\b(?:топ|top)\s*[- ]?\s*(\d{1,3})\b',q)
    if limit: require('limit',int(limit.group(1)))
    ordered_records = re.search(r'\b(первые|последние|birinchi|oxirgi)\s+(\d{1,2})\s+(?:экспортн\w*\s+)?(?:сдел\w*|bitim\w*)',q)
    if ordered_records:
        edge,count = ordered_records.groups()
        require('metric','records'); require('limit',int(count))
        require('order','asc' if edge in ['первые','birinchi'] else 'desc')
    groups = {
        'month':r'по\s+месяц|помесяч|ежемесяч|динамик|oylar\s+bo\'yicha|oylik',
        'year':r'по\s+годам|yillar\s+bo\'yicha',
        'buyer':r'по\s+покупател|xaridorlar\s+bo\'yicha',
        'seller':r'по\s+продавц|sotuvchilar\s+bo\'yicha',
        'broker':r'по\s+брокер|brokerlar\s+bo\'yicha',
        'region':r'по\s+регион|hududlar\s+bo\'yicha',
        'commodity':r'по\s+товар|tovarlar\s+bo\'yicha',
        'form':r'по\s+формам|shakllar\w*\s+bo\'yicha',
        'status':r'по\s+состояни|holatlar\s+bo\'yicha',
        'category':r'по\s+категори|toifalar\s+bo\'yicha',
        'auction':r'по\s+видам\s+торгов|savdo\s+turlari\s+bo\'yicha',
    }
    wanted_groups = {group for group,pattern in groups.items() if re.search(pattern,q)}
    if len(wanted_groups)>1: raise QuestionMismatch('multiple_groups')
    if wanted_groups: require('group',wanted_groups.pop())
    elif plan.group!='none' and not ranked and not (plan.comparison and plan.group=='year') and not re.search(r'сравн|taqqosla|solishtir',q):
        if not previous or not re.search(groups[plan.group],previous): raise QuestionMismatch('unexpected_group')

    if plan.metric!='rate' and plan.metric!='count':
        if re.search(r'в\s+сум(?:ах|ы)|\buzs\b|so\'m(?:da|ga)',q): require('report_currency','UZS')
        elif re.search(r'в\s+долларах|\busd\b|dollarda',q): require('report_currency','USD')
    if plan.participant_inn or plan.broker_code or plan.company_name:
        buyer = bool(re.search(r'покупател|покупок|закупок|xarid',q))
        seller = bool(re.search(r'продав[це]|продаж|sotuvchi|sotgan',q))
        if not ranked: require('role','buyer' if buyer and not seller else 'seller' if seller and not buyer else 'any')

    _calendar_checks(q,plan,require,request.scope.year)
