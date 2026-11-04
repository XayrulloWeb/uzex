"""Deterministic query compiler and grounded response renderer for AI plans."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from functools import lru_cache

from server.ai_models import AIQuestion, QueryPlan, chronological_metric, local_chronology_plan, local_count_plan, money
from server.catalog import CANCELLED, SNAPSHOT, commodity_label, normalize, region_label
from server.db import query
from server.question_checks import QuestionMismatch, calendar_mentions, question_text, relative_period, validate_question


def outcome(reason: str, lang='ru', kind='no_data'):
    texts = {
        'out_of_period': ('В наборе нет данных за запрошенный период. Реестр сделок охватывает 03.01.2022–30.10.2026; отсутствие периода нельзя выдавать за нулевой оборот.', 'So‘ralgan davr uchun ma’lumot yo‘q. Bitimlar reyestri 03.01.2022–30.10.2026 davrini qamrab oladi; mavjud bo‘lmagan davr aylanmasini nol deb bo‘lmaydi.'),
        'unsupported_field': ('В наборе нет себестоимости, расходов и сумм налогов для расчёта чистой прибыли. Сумма сделки не является прибылью.', 'To‘plamda sof foydani hisoblash uchun tannarx, xarajatlar va soliq summalari yo‘q. Bitim summasi foyda emas.'),
        'not_found': ('По указанным условиям запись в предоставленном наборе не найдена. Я не буду подставлять другую компанию, сделку или товар.', 'Ko‘rsatilgan shartlar bo‘yicha yozuv to‘plamda topilmadi. Boshqa kompaniya, bitim yoki tovar bilan almashtirmayman.'),
        'ambiguous_entity': ('Уточните компанию или товар. Для компании лучше указать ИНН/STIR; по неполному совпадению нельзя надёжно выбрать одного участника.', 'Kompaniya yoki tovarni aniqlashtiring. Kompaniya uchun STIRni ko‘rsatish ma’qul; qisman mos nomdan bitta ishtirokchini ishonchli tanlab bo‘lmaydi.'),
        'need_product': ('Уточните товар и единицу измерения, чтобы цена или объём имели однозначный смысл.', 'Narx yoki hajmni aniq hisoblash uchun tovar va o‘lchov birligini ko‘rsating.'),
        'currency': ('Уточните валюту: общие суммы можно сопоставить в UZS. Для отчёта в USD выберите экспортные долларовые сделки.', 'Valyutani aniqlashtiring: umumiy summalar UZSda solishtiriladi. USD hisobot uchun eksportdagi dollar bitimlarini tanlang.'),
        'date': ('Укажите точную дату или интервал для курса доллара.', 'Dollar kursi uchun aniq sana yoki oraliqni ko‘rsating.'),
        'unknown': ('Не удалось надёжно сопоставить вопрос с доступными полями. Уточните период, товар и требуемый показатель. Это не означает, что данных нет.', 'Savolni mavjud maydonlar bilan ishonchli bog‘lab bo‘lmadi. Davr, tovar va kerakli ko‘rsatkichni aniqlashtiring. Bu ma’lumot yo‘qligini anglatmaydi.'),
        'question_mismatch': ('Не удалось подтвердить, что расчёт учитывает все условия вопроса. Уточните запрос; непроверенные числа не показаны. Это не означает, что данных нет.', 'Hisob-kitob savolning barcha shartlarini hisobga olishini tasdiqlab bo‘lmadi. So‘rovni aniqlashtiring; tekshirilmagan raqamlar ko‘rsatilmaydi. Bu ma’lumot yo‘qligini anglatmaydi.'),
    }
    ru, uz = texts.get(reason, texts['unknown'])
    return {'status': kind, 'answer': uz if lang == 'uz' else ru, 'columns': [], 'rows': [], 'provenance': None, 'reason': reason}


def constrain_request(request: AIQuestion, plan: QueryPlan):
    """Do not trust a model to omit an explicit year or invent an identifier."""
    q = question_text(request.question)
    context = normalize(' '.join([request.question]+request.history))
    identifier_context = normalize(' '.join([request.question]+request.history).replace('№',' '))
    for field in ['deal_id', 'contract_id', 'participant_inn', 'broker_code']:
        value = getattr(plan, field)
        if value is not None and not re.search(r'(?<!\w)'+re.escape(str(value).casefold())+r'(?!\w)', identifier_context):
            raise QuestionMismatch('identifier_not_supplied')
    if plan.company_name and normalize(plan.company_name) not in context:
        raise QuestionMismatch('company_not_supplied')
    if plan.action == 'query':
        exact_plan = local_chronology_plan(request) or local_count_plan(request)
        if exact_plan:
            plan = exact_plan
        elif metric := chronological_metric(q):
            plan.metric = metric
            plan.order = 'asc' if metric == 'first_deal' else 'desc'
            plan.limit = 1
    years = [int(x) for x in re.findall(r'(?<!\d)((?:19|20)\d{2})(?!\d)', q)]
    if len(set(years)) == 1:
        requested = years[0]
        if plan.date_from or plan.date_to:
            if any(d.year != requested for d in [plan.date_from, plan.date_to] if d):
                raise QuestionMismatch('requested_year')
        plan.year = requested
    elif len(set(years)) > 1:
        plan.year = None
        if not plan.date_from:
            plan.date_from, plan.date_to = date(min(years), 1, 1), date(max(years), 12, 31)
    all_time=bool(re.search(r'вс[её]м (?:наборе|реестре)|весь период|все годы|вс[её] время|всему набору|butun (?:davr|to\'plam|reyestr)|barcha (?:davr|yil)|ma\'lumotlar to\'plamida|all time', q))
    if all_time and not years:
        plan.year = None
        plan.date_from = plan.date_to = None
    elif plan.deal_id and not years and not any(calendar_mentions(q)) and not relative_period(q):
        plan.year = plan.date_from = plan.date_to = None
    elif not years and not all_time and not relative_period(q):
        plan.year = request.scope.year
        if not any(calendar_mentions(q)) and (plan.date_from or plan.date_to):
            raise QuestionMismatch('unexpected_date_range')
    elif not years and plan.year is None and not plan.date_from and not plan.date_to:
        plan.year=request.scope.year
    if plan.region is None and not plan.deal_id: plan.region=request.scope.region
    if plan.commodity is None and not plan.deal_id: plan.commodity=request.scope.commodity
    if plan.brand and (brand:=re.fullmatch(r'(?:аи|ai)[-– ]?(\d{2,3})',normalize(plan.brand))):
        plan.brand='АИ-'+brand.group(1)
    validate_question(request,plan)
    return plan


@lru_cache(maxsize=1)
def company_index():
    rows = query('SELECT inn,name FROM participants')
    return [(r['inn'], r['name'], normalize(re.sub(r'["«»]', '', r['name']))) for r in rows]


def resolve_company(name):
    needle = normalize(re.sub(r'["«»]', '', name))
    matches = [(inn, original) for inn, original, normal in company_index() if normal == needle or re.search(r'(?<!\w)'+re.escape(needle)+r'(?!\w)', normal)]
    return matches


def column(key, lang='ru', kind='text'):
    labels = {'id': ('Код / ИНН', 'Kod / STIR'), 'label': ('Наименование', 'Nomi'), 'deals': ('Сделки', 'Bitimlar'),
              'amount': ('Сумма', 'Summa'), 'quantity': ('Объём', 'Hajm'), 'unit': ('Единица', 'Birlik'),
              'price': ('Цена за единицу', 'Birlik narxi'), 'deal_id': ('Сделка', 'Bitim'), 'deal_date': ('Дата', 'Sana'),
              'product_label': ('Товар', 'Tovar'), 'status': ('Состояние', 'Holat'), 'seller_name': ('Продавец', 'Sotuvchi'),
              'buyer_name': ('Покупатель', 'Xaridor'), 'usd_rate': ('UZS за 1 USD', '1 USD uchun UZS'), 'rate_date': ('Дата', 'Sana')}
    pair = labels.get(key, (key, key))
    return {'key': key, 'label': pair[lang == 'uz'], 'kind': kind}


def date_text(value):
    return date.fromisoformat(str(value)).strftime('%d.%m.%Y')


def scope_text(plan, lang):
    if plan.date_from and plan.date_to:
        return f'за период {date_text(plan.date_from)}–{date_text(plan.date_to)}' if lang=='ru' else f'{date_text(plan.date_from)}–{date_text(plan.date_to)} davrida'
    if plan.date_from:
        return f'начиная с {date_text(plan.date_from)}' if lang=='ru' else f'{date_text(plan.date_from)} sanasidan boshlab'
    if plan.date_to:
        return f'по {date_text(plan.date_to)} включительно' if lang=='ru' else f'{date_text(plan.date_to)} sanasigacha'
    if plan.year:
        return f'за {plan.year} год' if lang=='ru' else f'{plan.year}-yilda'
    return 'во всём предоставленном наборе' if lang=='ru' else 'berilgan butun to‘plamda'


def requested_record_facts(plan, row, lang, question):
    q = question_text(question)
    facts = []
    if re.search(r'\bсумм|\bsumma',q):
        facts.append(('Сумма — ' if lang=='ru' else 'Summa — ')+money(row['amount'])+' '+plan.report_currency+'.')
    if re.search(r'\bобъем|\bhajm',q):
        facts.append(('Объём — ' if lang=='ru' else 'Hajm — ')+money(row['quantity'],4).rstrip('0').rstrip(',')+' '+row['unit']+'.')
    if re.search(r'\bцен|\bnarx',q) and Decimal(row['quantity']):
        price = Decimal(row['amount'])/Decimal(row['quantity'])
        facts.append(('Цена — ' if lang=='ru' else 'Narx — ')+money(price)+' '+plan.report_currency+' / '+row['unit']+'.')
    return ' '+ ' '.join(facts) if facts else ''


def record_answer(plan, rows, total, lang, question=''):
    """Answer the selected operation directly, using only computed facts."""
    row = rows[0]
    scope = scope_text(plan, lang)
    day = date_text(row['deal_date'])
    kind = 'экспортная сделка' if plan.contract_type=='Экспортный' else 'внутренняя сделка' if plan.contract_type=='Внутренний' else 'сделка'
    uz_kind = 'eksport bitimi' if plan.contract_type=='Экспортный' else 'ichki bitim' if plan.contract_type=='Внутренний' else 'bitim'
    if plan.metric in ['first_deal', 'last_deal']:
        first = plan.metric=='first_deal'
        facts = requested_record_facts(plan,row,lang,question)
        if plan.date_field=='deal_date':
            clock = f" в {row['deal_time']}" if row.get('deal_time') else ''
            if lang=='ru':
                return f"{'Первая' if first else 'Последняя'} зарегистрированная {kind} {scope} — {day}{clock}, №{row['deal_id']}."+facts
            clock = f", soat {row['deal_time']}" if row.get('deal_time') else ''
            return f"{scope[0].upper()+scope[1:]} {'birinchi' if first else 'oxirgi'} {uz_kind} — {day}{clock}; bitim №{row['deal_id']}."+facts
        activity = date_text(row['activity_date'])
        name = 'оплаты' if plan.date_field=='payment_date' else 'поставки'
        uz_name = 'to‘lov' if plan.date_field=='payment_date' else 'yetkazib berish'
        if lang=='ru':
            return f"Самая {'ранняя' if first else 'поздняя'} дата {name} {scope} — {activity}. Подтверждение: сделка №{row['deal_id']} от {day}."+facts
        return f"{scope[0].upper()+scope[1:]} eng {'erta' if first else 'kech'} {uz_name} sanasi — {activity}. Dalil: {day} sanasidagi №{row['deal_id']} bitim."+facts
    if plan.metric in ['min_amount', 'max_amount']:
        if lang=='ru':
            return f"{'Крупнейшая' if plan.metric=='max_amount' else 'Наименьшая'} по сумме {kind} {scope} — №{row['deal_id']} от {day}: {money(row['amount'])} {plan.report_currency}."
        return f"{scope[0].upper()+scope[1:]} summasi eng {'katta' if plan.metric=='max_amount' else 'kichik'} {uz_kind} — {day} sanasidagi №{row['deal_id']}: {money(row['amount'])} {plan.report_currency}."
    if plan.metric in ['min_price', 'max_price']:
        if lang=='ru':
            return f"{'Максимальная' if plan.metric=='max_price' else 'Минимальная'} цена {scope} — {money(row['price'])} {plan.report_currency} / {row['unit']}, сделка №{row['deal_id']} от {day}."
        return f"{scope[0].upper()+scope[1:]} eng {'yuqori' if plan.metric=='max_price' else 'past'} narx — {money(row['price'])} {plan.report_currency} / {row['unit']}; {day} sanasidagi №{row['deal_id']} bitim."
    if plan.metric=='detail':
        if lang=='ru':
            return f"Сделка №{row['deal_id']} от {day}: {row['product_label']}. Объём — {money(row['quantity'],4).rstrip('0').rstrip(',')} {row['unit']}; сумма — {money(row['amount'])} {plan.report_currency}."
        return f"{day} sanasidagi №{row['deal_id']} bitim: {row['product_label']}. Hajm — {money(row['quantity'],4).rstrip('0').rstrip(',')} {row['unit']}; summa — {money(row['amount'])} {plan.report_currency}."
    return f"Найдено {money(total['count'],0)} сделок; показано {len(rows)}. Суммы приведены к {plan.report_currency}." if lang=='ru' else f"{money(total['count'],0)} ta bitim topildi; {len(rows)} tasi ko‘rsatilgan. Summalar {plan.report_currency}da."


def execute_plan(plan: QueryPlan, request: AIQuestion):
    lang = request.lang
    uz = lang == 'uz'
    if plan.action != 'query':
        return outcome(plan.reason if plan.reason in ['ambiguous_entity', 'need_product'] else 'unknown', lang, 'clarify')
    if plan.metric in ['participant','broker','contract']:
        return reference_result(plan,lang)
    last = date(2026, 10, 31) if plan.metric == 'rate' else date.fromisoformat(SNAPSHOT)
    first = date(2022, 1, 1)
    if (plan.year and plan.year not in range(2022,2027)) or (plan.date_from and (plan.date_from > last or plan.date_from < first)):
        return outcome('out_of_period', lang)
    if plan.date_to and plan.date_to > last:
        # A named whole year/month may extend past the snapshot; expose the actual end.
        if plan.date_to.year == 2026 and plan.date_to.month <= 10:
            plan.date_to = last
        elif (plan.year == 2026 and not plan.date_from) or (plan.date_to==date(2026,12,31) and not any(calendar_mentions(question_text(request.question)))):
            plan.date_to = last
        else:
            return outcome('out_of_period', lang)
    if plan.metric == 'rate':
        if not plan.date_from:
            return outcome('date', lang, 'clarify')
        sql = 'SELECT rate_date,usd_rate FROM usd_rates WHERE rate_date BETWEEN ? AND ? ORDER BY rate_date LIMIT ?'
        parameters = [plan.date_from, plan.date_to or plan.date_from, plan.limit]
        rows = query(sql, parameters)
        if not rows:
            return outcome('not_found', lang)
        answer = ('Курс из предоставленного набора; это вымышленные, не текущие рыночные значения.' if not uz else 'Kurs berilgan to‘plamdan olingan; bu o‘ylab topilgan, joriy bozor qiymatlari emas.')
        if len(rows)==1:
            row = rows[0]
            fact = f"Курс на {date_text(row['rate_date'])}: 1 USD = {money(row['usd_rate'])} UZS." if not uz else f"{date_text(row['rate_date'])} sanasidagi kurs: 1 USD = {money(row['usd_rate'])} UZS."
            answer = fact+' '+answer
        return result(answer, rows, [column('rate_date',lang), column('usd_rate',lang,'decimal')], sql, parameters, len(rows), plan, lang=lang)
    if plan.metric in ['weighted_price', 'min_price', 'max_price'] and not (plan.commodity or plan.contract_id or plan.product_text):
        return outcome('need_product', lang, 'clarify')

    conditions, parameters = ['TRUE'], []
    def add(sql, *values):
        conditions.append(sql); parameters.extend(values)
    if plan.year: add('year('+plan.date_field+')=?', plan.year)
    if plan.date_from: add(plan.date_field+'>=?', plan.date_from)
    if plan.date_to: add(plan.date_field+'<=?', plan.date_to)
    if plan.metric in ['first_deal', 'last_deal']:
        add(plan.date_field+' IS NOT NULL')
    for field in ['commodity','region','contract_type','form','deal_id','contract_id']:
        value = getattr(plan, field)
        if value is not None: add(field+'=?', value)
    if not plan.include_cancelled: add('status<>?', CANCELLED)
    if plan.statuses: add('status IN ('+','.join('?' for _ in plan.statuses)+')', *plan.statuses)
    if plan.company_name:
        matches = resolve_company(plan.company_name)
        if len(matches) != 1:
            return outcome('ambiguous_entity' if matches else 'not_found', lang, 'clarify' if matches else 'no_data')
        if plan.participant_inn and plan.participant_inn!=matches[0][0]:
            return outcome('ambiguous_entity',lang,'clarify')
        plan.participant_inn = matches[0][0]
    if plan.participant_inn:
        if not query('SELECT inn FROM participants WHERE inn=?',[plan.participant_inn]): return outcome('not_found',lang)
        if plan.role == 'seller': add('seller_inn=?',plan.participant_inn)
        elif plan.role == 'buyer': add('buyer_inn=?',plan.participant_inn)
        else: add('(seller_inn=? OR buyer_inn=?)',plan.participant_inn,plan.participant_inn)
    if plan.broker_code:
        if not query('SELECT code FROM brokers WHERE code=?',[plan.broker_code]): return outcome('not_found',lang)
        if plan.role == 'seller': add('seller_broker=?',plan.broker_code)
        elif plan.role == 'buyer': add('buyer_broker=?',plan.broker_code)
        else: add('(seller_broker=? OR buyer_broker=?)',plan.broker_code,plan.broker_code)
    if plan.grade: add('grade_norm=?',plan.grade)
    if plan.brand: add('search_text LIKE ?', '%'+normalize(plan.brand).replace('ai-', 'аи-')+'%')
    if plan.product_text: add('search_text LIKE ?', '%'+normalize(plan.product_text)+'%')
    if plan.quality_class:
        aliases = {'1': ['1', 'i'], '2': ['2', 'ii'], '3': ['3', 'iii']}.get(plan.quality_class,[normalize(plan.quality_class)])
        checks=[]
        for value in aliases:
            checks.append('regexp_matches(search_text, ?)')
            parameters.append(r'(^|\s)'+re.escape(value)+r'[- ]*(класс|klass)(\s|$)|\b(класс|klass)\s+'+re.escape(value)+r'(\s|$)')
        conditions.append('('+' OR '.join(checks)+')')
    if plan.metric == 'late_delivery': add('late_delivery=TRUE')
    if plan.report_currency == 'USD':
        if plan.contract_type != 'Экспортный': return outcome('currency',lang,'clarify')
        add("currency='USD'")
    amount = 'amount_native' if plan.report_currency=='USD' else 'amount_uzs'
    quantity = 'coalesce(delivered_quantity,0)' if plan.delivered_only else 'quantity'
    unit = 'unit'
    if plan.physical_unit in ['килограмм','тонна']:
        add("unit IN ('килограмм','тонна')")
        quantity = f"CASE WHEN unit='тонна' THEN ({quantity})*1000 ELSE ({quantity}) END"
        if plan.physical_unit=='тонна': quantity = f"({quantity})*CAST('0.001' AS DECIMAL(4,3))"
        unit = "'"+plan.physical_unit+"'"
    elif plan.physical_unit:
        add('unit=?',plan.physical_unit)
    condition = ' AND '.join(conditions)
    total = query(f'SELECT count(*) AS count,min({plan.date_field}) AS first_date,max({plan.date_field}) AS last_date FROM trades WHERE '+condition, parameters)[0]
    if total['count']==0 and (plan.metric!='count' or plan.deal_id or plan.contract_id or plan.brand or plan.product_text):
        return outcome('not_found',lang)
    if plan.metric in ['detail','records','first_deal','last_deal','min_price','max_price','min_amount','max_amount']:
        return record_result(plan, lang, condition, parameters, amount, quantity, unit, total, request.question)
    return aggregate_result(plan, lang, condition, parameters, amount, quantity, unit, total)


def aggregate_result(plan, lang, condition, parameters, amount, quantity, unit, total):
    dims = {
        'seller': ('seller_inn','seller_name'), 'buyer': ('buyer_inn','buyer_name'),
        'month': (f"strftime({plan.date_field},'%Y-%m')", f"strftime({plan.date_field},'%Y-%m')"),
        'year': (f'year({plan.date_field})',f'year({plan.date_field})'), 'region': ('region','region'),
        'commodity': ('commodity','commodity'), 'category': ('category','category'),
        'status': ('status','status'), 'form': ('form','form'), 'auction': ('auction','auction'),
        'broker': ('broker_key','broker_name'),
    }
    selected, grouped, columns = [], [], []
    source = f'(SELECT * FROM trades WHERE {condition}) AS filtered'
    if plan.group=='broker':
        source = f'''(SELECT t.*,b.code AS broker_key,b.name AS broker_name FROM
            (SELECT * FROM trades WHERE {condition}) t JOIN brokers b ON (t.seller_broker=b.code OR t.buyer_broker=b.code)) AS filtered'''
    if plan.group!='none':
        key,label=dims[plan.group]
        selected += [key+' AS id',label+' AS label']
        grouped += [key,label]
        columns += [column('label',lang)]
        if key!=label: columns.append(column('id',lang))
    selected += ['count(*) AS deals']
    columns += [column('deals',lang,'integer')]
    if plan.metric in ['amount','weighted_price']:
        selected.append('coalesce(sum('+amount+'),0) AS amount')
        c=column('amount',lang,'decimal');c['unit']=plan.report_currency;columns.append(c)
    if plan.metric in ['volume','weighted_price']:
        selected += ['coalesce(sum('+quantity+'),0) AS quantity',unit+' AS unit']
        if unit=='unit': grouped.append(unit)
        columns += [column('quantity',lang,'decimal'),column('unit',lang)]
    group=' GROUP BY '+','.join(dict.fromkeys(grouped)) if grouped else ''
    rank='amount/nullif(quantity,0)' if plan.metric=='weighted_price' else 'amount' if plan.metric=='amount' else 'quantity' if plan.metric=='volume' else 'deals'
    ordering='id ASC' if plan.group in ['month','year'] else rank+' '+plan.order.upper()
    if plan.group!='none' and plan.group not in ['month','year']: ordering+=', id ASC'
    inner='SELECT '+','.join(selected)+' FROM '+source+group
    sql='SELECT * FROM ('+inner+') AS aggregates ORDER BY '+ordering+' LIMIT ?'
    actual_params=parameters+[120 if plan.group in ['month','year'] else plan.limit]
    rows=query(sql,actual_params)
    for row in rows:
        if plan.group=='region': row['label']=region_label(row['id'],lang)
        if plan.group=='commodity': row['label']=commodity_label(row['id'],lang)
        if plan.metric=='weighted_price':
            row['price']=format(Decimal(row['amount'])/Decimal(row['quantity']), 'f') if Decimal(row['quantity']) else None
    if plan.metric=='weighted_price':
        c=column('price',lang,'decimal');c['unit']=plan.report_currency;columns.append(c)
    if plan.group=='none' and len(rows)==1:
        row=rows[0]
        if plan.metric=='amount':
            answer = f"Сумма зарегистрированных сделок — {money(row['amount'])} {plan.report_currency}; учтено {money(row['deals'],0)} сделок." if lang=='ru' else f"Qayd etilgan bitimlar summasi — {money(row['amount'])} {plan.report_currency}; {money(row['deals'],0)} ta bitim hisobga olindi."
        elif plan.metric=='volume':
            answer = f"Объём — {money(row['quantity'],4).rstrip('0').rstrip(',')} {row['unit']}; учтено {money(row['deals'],0)} сделок." if lang=='ru' else f"Hajm — {money(row['quantity'],4).rstrip('0').rstrip(',')} {row['unit']}; {money(row['deals'],0)} ta bitim hisobga olindi."
        elif plan.metric=='weighted_price' and row['price'] is not None:
            answer = f"Средневзвешенная цена — {money(row['price'])} {plan.report_currency} / {row['unit']}. Расчёт: сумма сделок ÷ суммарный физический объём." if lang=='ru' else f"O‘rtacha tortilgan narx — {money(row['price'])} {plan.report_currency} / {row['unit']}. Hisob: bitimlar summasi ÷ jami fizik hajm."
        else:
            answer = f"По выбранным условиям — {money(row['deals'],0)} сделок." if lang=='ru' else f"Tanlangan shartlar bo‘yicha {money(row['deals'],0)} ta bitim."
    elif rows and plan.group in ['seller','buyer','broker','region','commodity','category','status','form','auction'] and plan.metric in ['amount','count','late_delivery']:
        row = rows[0]
        groups = {'seller':('продавцы','sotuvchilar'), 'buyer':('покупатели','xaridorlar'), 'broker':('брокеры','brokerlar'),
                  'region':('регионы склада','ombor hududlari'), 'commodity':('товары','tovarlar'), 'category':('категории','toifalar'),
                  'status':('состояния','holatlar'), 'form':('формы контракта','shartnoma shakllari'), 'auction':('виды торгов','savdo turlari')}
        measure = ('сумме сделок','bitimlar summasi') if plan.metric=='amount' else ('числу сделок','bitimlar soni')
        value = money(row['amount'])+' '+plan.report_currency if plan.metric=='amount' else money(row['deals'],0)+(' сделок' if lang=='ru' else ' ta bitim')
        identifier = f" ({'ИНН' if lang=='ru' else 'STIR'} {row['id']})" if plan.group in ['seller','buyer'] else f" ({row['id']})" if plan.group=='broker' else ''
        if lang=='ru':
            answer = f"{'Лидер' if plan.order=='desc' else 'Минимум'} по {measure[0]} ({groups[plan.group][0]}): {row['label']}{identifier} — {value}. Учтено {money(total['count'],0)} сделок; показано {len(rows)} строк."
        else:
            answer = f"{measure[1][0].upper()+measure[1][1:]} bo‘yicha {'yetakchi' if plan.order=='desc' else 'eng kichik natija'} ({groups[plan.group][1]}): {row['label']}{identifier} — {value}. {money(total['count'],0)} ta bitim hisobga olindi; {len(rows)} qator ko‘rsatilgan."
    else:
        answer = f"Учтено {money(total['count'],0)} сделок. Показано строк: {len(rows)}. Единицы измерения учитываются отдельно." if lang=='ru' else f"{money(total['count'],0)} ta bitim hisobga olindi. Ko‘rsatilgan qatorlar: {len(rows)}. O‘lchov birliklari alohida hisoblanadi."
    return result(answer,rows,columns,sql,actual_params,total['count'],plan,{'from':total['first_date'],'to':total['last_date']},lang=lang)


def record_result(plan, lang, condition, parameters, amount, quantity, unit, total, question=''):
    if plan.metric=='detail' and plan.deal_id is None and plan.contract_id is None:
        return outcome('unknown',lang,'clarify')
    if plan.metric in ['min_price','max_price']:
        if plan.group!='none': return outcome('unknown',lang,'clarify')
        if not plan.physical_unit:
            units=query('SELECT DISTINCT unit FROM trades WHERE '+condition,parameters)
            if len(units)>1: return outcome('need_product',lang,'clarify')
        ordering=amount+'/nullif(('+quantity+'),0) '+('ASC' if plan.metric=='min_price' else 'DESC')+',deal_id ASC'
    elif plan.metric in ['min_amount','max_amount']:
        if plan.group!='none': return outcome('unknown',lang,'clarify')
        ordering=amount+(' ASC' if plan.metric=='min_amount' else ' DESC')+',deal_id ASC'
    else:
        if plan.metric in ['first_deal', 'last_deal'] and plan.group != 'none':
            return outcome('unknown',lang,'clarify')
        direction = 'ASC' if plan.metric == 'first_deal' else 'DESC' if plan.metric == 'last_deal' else plan.order.upper()
        ordering = plan.date_field+' '+direction
        if plan.date_field == 'deal_date': ordering += ',deal_time '+direction
        ordering += ',deal_id '+direction
    extra_date = ','+plan.date_field+' AS activity_date' if plan.date_field!='deal_date' else ''
    sql=f'''SELECT deal_id,deal_date,deal_time{extra_date},product_label,({quantity}) AS quantity,({unit}) AS unit,
        {amount} AS amount,status,seller_name,buyer_name FROM trades WHERE {condition}
        ORDER BY {ordering} LIMIT ?'''
    actual_params=parameters+[1 if plan.metric in ['first_deal','last_deal'] else plan.limit]
    rows=query(sql,actual_params)
    columns=[column(k,lang,'integer' if k=='deal_id' else 'decimal' if k in ['quantity','amount'] else 'text') for k in ['deal_id','deal_date','product_label','quantity','unit','amount','status','seller_name','buyer_name']]
    columns.insert(2, {'key':'deal_time','label':'Время сделки' if lang=='ru' else 'Bitim vaqti','kind':'text'})
    if extra_date:
        columns.insert(2,{'key':'activity_date','label':('Дата оплаты' if plan.date_field=='payment_date' else 'Дата поставки') if lang=='ru' else ('To‘lov sanasi' if plan.date_field=='payment_date' else 'Yetkazilgan sana'),'kind':'text'})
    for c in columns:
        if c['key']=='amount': c['unit']=plan.report_currency
    if plan.metric in ['min_price','max_price','detail']:
        for row in rows:
            row['price']=format(Decimal(row['amount'])/Decimal(row['quantity']), 'f') if Decimal(row['quantity']) else None
        c=column('price',lang,'decimal');c['unit']=plan.report_currency;columns.append(c)
    answer = record_answer(plan, rows, total, lang, question)
    return result(answer,rows,columns,sql,actual_params,total['count'],plan,{'from':total['first_date'],'to':total['last_date']},lang=lang)


def plan_context(plan,lang):
    uz = lang=='uz'
    metrics = {'count':('Число сделок','Bitimlar soni'), 'amount':('Сумма сделок','Bitimlar summasi'),
               'volume':('Физический объём','Fizik hajm'), 'weighted_price':('Средневзвешенная цена','O‘rtacha tortilgan narx'),
               'min_price':('Минимальная цена','Eng past narx'), 'max_price':('Максимальная цена','Eng yuqori narx'),
               'min_amount':('Минимальная сумма сделки','Eng kichik bitim summasi'), 'max_amount':('Максимальная сумма сделки','Eng katta bitim summasi'),
               'first_deal':('Первая сделка','Birinchi bitim'), 'last_deal':('Последняя сделка','Oxirgi bitim'),
               'detail':('Карточка сделки','Bitim kartochkasi'), 'records':('Список сделок','Bitimlar ro‘yxati'),
               'late_delivery':('Завершённые поставки с опозданием','Kech yakunlangan yetkazishlar'),
               'rate':('Курс из набора данных','To‘plamdagi kurs'), 'participant':('Участник','Ishtirokchi'),
               'broker':('Брокер','Broker'), 'contract':('Контракт','Shartnoma')}
    labels = [metrics[plan.metric][uz]]
    for field,prefix in [('deal_id','№'),('contract_id','Shartnoma ' if uz else 'Контракт '),('participant_inn','STIR ' if uz else 'ИНН '),('broker_code','Broker ' if uz else 'Брокер '),('company_name','')]:
        if value:=getattr(plan,field): labels.append(prefix+str(value))
    if plan.metric in ['participant','broker','contract']: return labels
    if plan.metric=='rate':
        if plan.date_from: labels.append(date_text(plan.date_from)+((' — '+date_text(plan.date_to)) if plan.date_to and plan.date_to!=plan.date_from else ''))
        return labels
    labels.append(scope_text(plan,lang))
    if plan.date_field!='deal_date': labels.append(('По дате оплаты' if plan.date_field=='payment_date' else 'По дате поставки') if not uz else ('To‘lov sanasi bo‘yicha' if plan.date_field=='payment_date' else 'Yetkazish sanasi bo‘yicha'))
    if plan.contract_type: labels.append(('Eksport' if plan.contract_type=='Экспортный' else 'Ichki') if uz else plan.contract_type)
    if plan.commodity: labels.append(commodity_label(plan.commodity,lang))
    if plan.region: labels.append(('Ombor: ' if uz else 'Склад: ')+region_label(plan.region,lang))
    if plan.group!='none':
        groups = {'month':('По месяцам','Oylar bo‘yicha'), 'year':('По годам','Yillar bo‘yicha'), 'buyer':('По покупателям','Xaridorlar bo‘yicha'),
                  'seller':('По продавцам','Sotuvchilar bo‘yicha'), 'broker':('По брокерам','Brokerlar bo‘yicha'), 'region':('По регионам склада','Ombor hududlari bo‘yicha'),
                  'commodity':('По товарам','Tovarlar bo‘yicha'), 'form':('По формам контракта','Shartnoma shakllari bo‘yicha'), 'status':('По состояниям','Holatlar bo‘yicha'),
                  'category':('По категориям','Toifalar bo‘yicha'), 'auction':('По видам торгов','Savdo turlari bo‘yicha')}
        labels.append(groups[plan.group][uz])
    if plan.statuses:
        from server.catalog import STATUS_UZ
        labels.extend(STATUS_UZ.get(status,status) if uz else status for status in plan.statuses)
    else: labels.append(('Bekor qilinganlarsiz' if not plan.include_cancelled else 'Barcha holatlar') if uz else ('Без аннулированных' if not plan.include_cancelled else 'Все состояния'))
    if plan.brand: labels.append(('Marka ' if uz else 'Марка ')+plan.brand)
    if plan.grade: labels.append(('Nav ' if uz else 'Сорт ')+plan.grade)
    if plan.quality_class: labels.append(('Sinf ' if uz else 'Класс ')+plan.quality_class)
    if plan.physical_unit: labels.append(plan.physical_unit)
    if plan.metric in ['amount','weighted_price','min_price','max_price','min_amount','max_amount','detail','records']: labels.append(plan.report_currency)
    return labels


def result(answer, rows, columns, sql, parameters, count, plan, period=None, lang='ru'):
    from server.db import serial
    return {'status':'answer','answer':answer,'columns':columns,'rows':rows,'interpretation':plan_context(plan,lang),
            'provenance': {'sql':sql, 'parameters':serial(parameters), 'row_count':count, 'snapshot':SNAPSHOT,
                           'sources': ['usd_rates.csv'] if plan.metric=='rate' else ['deals_2022…2026.csv','contracts.csv','participants.csv','brokers.csv','usd_rates.csv'],
                           'period':period, 'date_field':plan.date_field, 'currency':plan.report_currency, 'include_cancelled':plan.include_cancelled, 'statuses':plan.statuses,
                           'method':'USD × rate on deal date; quantity = lots × lot size; weighted price = sum(amount) / sum(quantity)'},
            'plan':plan.model_dump(mode='json')}


def reference_result(plan,lang):
    lookup={'participant':('participants','inn',plan.participant_inn),'broker':('brokers','code',plan.broker_code),'contract':('contracts','contract_id',plan.contract_id)}
    table,key,value=lookup[plan.metric]
    if plan.metric=='participant' and plan.company_name:
        matches=resolve_company(plan.company_name)
        if len(matches)!=1:return outcome('ambiguous_entity' if matches else 'not_found',lang,'clarify' if matches else 'no_data')
        if value and value!=matches[0][0]: return outcome('ambiguous_entity',lang,'clarify')
        value=matches[0][0]
    if value is None:return outcome('ambiguous_entity',lang,'clarify')
    sql=f'SELECT * FROM {table} WHERE {key}=?'
    records=query(sql,[value])
    if not records:return outcome('not_found',lang)
    labels={'inn':('ИНН','STIR'),'name':('Наименование','Nomi'),'code':('Код брокера','Broker kodi'),'region_raw':('Регион','Hudud'),
            'activity':('Вид деятельности','Faoliyat'),'role':('Роль','Roli'),'vat_payer':('Плательщик НДС','QQS to‘lovchi'),
            'contract_id':('Контракт','Shartnoma'),'product_name':('Товар','Tovar'),'currency':('Валюта','Valyuta'),'base_price':('Базисная цена','Bazaviy narx'),
            'unit':('Единица','Birlik'),'lot_size':('Размер лота','Lot hajmi'),'seller_inn':('ИНН продавца','Sotuvchi STIR'),'payment_days':('Срок оплаты, дней','To‘lov muddati, kun'),
            'delivery_days':('Срок поставки, дней','Yetkazish muddati, kun'),'brand':('Марка','Marka'),'size':('Размер','O‘lcham'),'grade':('Сорт','Nav'),'quality_class':('Класс','Sinf'),
            'tnved':('ТН ВЭД','TIF TN'),'warehouse':('Адрес склада','Ombor manzili'),'form':('Форма','Shakl'),'registered_date':('Регистрация','Ro‘yxatga olingan'),'valid_until':('Действует до','Amal qilish muddati')}
    rows=[]
    for field,cell in records[0].items():
        if field not in labels:continue
        if isinstance(cell,bool):cell=('Да' if cell else 'Нет') if lang=='ru' else ('Ha' if cell else 'Yo‘q')
        rows.append({'field':labels[field][lang=='uz'],'value':str(cell) if cell is not None else '—'})
    answer='Карточка из предоставленного справочника. Это сведения текущей выгрузки, не история изменения реквизитов.' if lang=='ru' else 'Berilgan ma’lumotnomadan kartochka. Bu joriy to‘plam ma’lumotlari, rekvizitlarning o‘zgarish tarixi emas.'
    response=result(answer,rows,[{'key':'field','label':'Поле' if lang=='ru' else 'Maydon','kind':'text'},{'key':'value','label':'Значение' if lang=='ru' else 'Qiymat','kind':'text'}],sql,[value],1,plan,lang=lang)
    response['provenance']['sources']=[{'participants':'participants.csv','brokers':'brokers.csv','contracts':'contracts.csv'}[table]]
    response['provenance']['method']='Reference card from the provided dataset; no trade aggregation.'
    return response
