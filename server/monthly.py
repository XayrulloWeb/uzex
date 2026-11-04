"""Verified monthly comparisons, optionally accompanied by daily FX statistics."""
from __future__ import annotations

import calendar
import re
from datetime import date
from decimal import Decimal, localcontext

from server.catalog import COMMODITIES, SNAPSHOT, commodity_label, normalize
from server.db import query
from server.question_checks import MONTHS as MONTH_PATTERNS
from server.ratios import changes


def month_end(start):
    return date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])


def rate_requested(text):
    return bool(re.search(r'курс\w*\s+(?:доллар\w*|usd)|(?:доллар\w*|usd)\s+курс\w*|dollar\w*\s+kurs\w*', normalize(text)))


def trade_currency_text(text):
    return re.sub(r'курс\w*\s+(?:доллар\w*|usd)|(?:доллар\w*|usd)\s+курс\w*|dollar\w*\s+kurs\w*',' ',normalize(text))


def month_requirements(request):
    """Extract explicit comparison direction, independently of a model proposal.

    Deliberately bounded: two named months in one year, with an explicit
    baseline connector. Other calendar language needs clarification.
    """
    from server.ai_models import MonthComparison
    from server.question_checks import calendar_mentions, question_text
    q = question_text(request.question)
    dates, _ = calendar_mentions(q)
    years = sorted({int(y) for y in re.findall(r'(?<!\d)((?:19|20)\d{2})(?!\d)',q)})
    if dates or len(years)>1: return None
    year = years[0] if years else request.scope.year
    if year is None: return None
    found = []
    for number, pattern in enumerate(MONTH_PATTERNS,1):
        found += [(m.start(),m.end(),number) for m in re.finditer(r'\b(?:'+pattern+r')\b',q)]
    found.sort()
    if len(found)!=2 or found[0][2]==found[1][2]: return None
    baselines = []
    for start,end,number in found:
        before,after = q[:start],q[end:]
        if re.search(r'(?:относительно|по\s+сравнению\s+с|в\s+сравнении\s+с)\s*$', before) or re.match(r'\s+nisbatan\b',after):
            baselines.append(number)
    if len(baselines)!=1: return None
    baseline = baselines[0]
    target = next(number for _,_,number in found if number!=baseline)
    return MonthComparison(baseline=date(year,baseline,1),target=date(year,target,1),include_usd_rate=rate_requested(q))


def local_monthly_plan(request):
    """Handle a family of exact questions; never discard unknown qualifiers."""
    from server.ai_models import QueryPlan
    from server.question_checks import _products, question_text
    comparison = month_requirements(request)
    if comparison is None: return None
    q = question_text(request.question)
    products = _products(q)
    if len(products)>1: return None
    amount = bool(re.search(r'\bсумм\w*|\bоборот\w*|\bsumma\w*|\baylanma\w*',q))
    count = bool(re.search(r'число\s+сдел|количество\s+сдел|nechta\s+bitim|bitimlar\s+soni',q))
    if amount == count: return None
    remainder = re.sub(r'(?<!\d)(?:19|20)\d{2}(?!\d)',' ',q)
    for pattern in MONTH_PATTERNS: remainder = re.sub(r'\b(?:'+pattern+r')\b',' ',remainder)
    remainder = re.sub(r'хлопков\w*\s+(?:пряж\w*|масл\w*|шрот\w*)|paxta\s+(?:ip\w*|kalava\w*|yog\w*|shrot\w*)',' ',remainder)
    # Catalogue phrases are removed as whole phrases, longest first.
    aliases = sorted({normalize(alias).strip() for item in COMMODITIES for alias in [item[2],item[3],*item[-1]]},key=len,reverse=True)
    for alias in aliases:
        if alias: remainder = re.sub(r'(?<!\w)'+re.escape(alias)+(r'\w*' if len(alias)>=4 else r'(?!\w)'),' ',remainder)
    allowed = (r'и|в|за|на|по|с|к|от|во|како[йея]|какую|каков\w*|был\w*|сколько|насколько|покажи|посчитай|рассчитай|'
               r'год\w*|месяц\w*|курс\w*|доллар\w*|средн\w*|сумм\w*|оборот\w*|число|количеств\w*|сдел\w*|'
               r'экспорт\w*|внутренн\w*|вырос\w*|рост\w*|снизил\w*|изменил\w*|изменени\w*|увеличил\w*|уменьшил\w*|'
               r'относительно|сравнению|сравнении|разниц\w*|процент\w*|абсолютн\w*|без|аннулирован\w*|включая|все[хм]?|состояни\w*|'
               r'uzs|usd|сумах|сумы|va|yil\w*|oy\w*|dollar\w*|kurs\w*|o\'rtacha|qancha|qanday|bo\'lgan|bo\'ldi|'
               r'eksport\w*|ichki|summ\w*|aylanma\w*|nechta|bitim\w*|soni|nisbatan|qanchaga|o\'s\w*|o\'zgar\w*|'
               r'kamay\w*|osh\w*|farq\w*|foiz\w*|hisobla\w*|so\'m\w*|bekor|qilingan\w*|hisobga|olma\w*|barcha|holat\w*|ham|qo\'sh\w*')
    words = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*|\d+",remainder)
    if any(not re.fullmatch(allowed,word) for word in words): return None
    export = bool(re.search(r'экспорт|eksport',q))
    domestic = bool(re.search(r'внутренн|ichki',q))
    if export and domestic: return None
    without = bool(re.search(r'без\s+аннулир|bekor\s+qilingan\w*(?:\s+bitim\w*)?\s+hisobga\s+olma',q))
    including = bool(re.search(r'включая\s+аннулир|все\s+состояни|barcha\s+holat|qilingan\w*\s+ham',q))
    if re.search(r'аннулир|bekor\s+qilingan',q) and not without and not including: return None
    scope = request.scope
    return QueryPlan(metric='amount' if amount else 'count',group='month',comparison=True,month_comparison=comparison,
                     year=comparison.target.year,date_from=min(comparison.baseline,comparison.target),
                     date_to=month_end(max(comparison.baseline,comparison.target)),
                     commodity=next(iter(products)) if products else scope.commodity,region=scope.region,
                     contract_type='Экспортный' if export else 'Внутренний' if domestic else None,
                     include_cancelled=not without if (without or including) else scope.status!='active',
                     statuses=[] if (without or including) else ['Исполнен'] if scope.status=='fulfilled' else [],
                     report_currency='USD' if re.search(r'в\s+долларах|\busd\b|dollarda',trade_currency_text(q)) else 'UZS')


def monthly_result(plan, lang, condition, parameters, amount, total):
    from server.ai_analytics import column, result
    from server.ai_models import money
    comparison = plan.month_comparison
    keys = [d.strftime('%Y-%m') for d in [comparison.baseline,comparison.target]]
    selected = 'coalesce(sum('+amount+'),0) AS amount' if plan.metric=='amount' else 'NULL AS amount'
    sql = f'''WITH trade_totals AS (
        SELECT strftime({plan.date_field},'%Y-%m') AS id,count(*) AS deals,{selected}
        FROM trades WHERE {condition} GROUP BY id
    ), rate_totals AS (
        SELECT strftime(rate_date,'%Y-%m') AS id,count(*) AS rate_days,
               sum(usd_rate) AS rate_sum,min(usd_rate) AS rate_min,max(usd_rate) AS rate_max
        FROM usd_rates WHERE strftime(rate_date,'%Y-%m') IN (?,?) GROUP BY id
    ), periods AS (SELECT ? AS id UNION ALL SELECT ? AS id)
    SELECT p.id,p.id AS label,coalesce(t.deals,0) AS deals,coalesce(t.amount,0) AS amount,
           r.rate_days,r.rate_sum,r.rate_min,r.rate_max
    FROM periods p LEFT JOIN trade_totals t USING(id) LEFT JOIN rate_totals r USING(id)
    ORDER BY CASE WHEN p.id=? THEN 0 ELSE 1 END'''
    actual_params = parameters+keys+keys+[keys[0]]
    rows = query(sql,actual_params)
    # Daily rates have an independent denominator: calendar observations, not trades.
    for row in rows:
        with localcontext() as context:
            context.prec = 38
            row['rate_mean'] = format(Decimal(row['rate_sum'])/row['rate_days'],'f') if row['rate_days'] else None
    before,after = rows
    measure = 'amount' if plan.metric=='amount' else 'deals'
    change = changes(before[measure],after[measure])
    unit = plan.report_currency if plan.metric=='amount' else 'сделок' if lang=='ru' else 'ta bitim'
    places = 2 if plan.metric=='amount' else 0
    lines = []
    if comparison.include_usd_rate:
        if after['rate_days']:
            if lang=='ru':
                lines.append(f"Курс доллара за {keys[1]}: средний — {money(after['rate_mean'])} UZS за 1 USD; дневной диапазон — {money(after['rate_min'])}–{money(after['rate_max'])} UZS ({after['rate_days']} дней).")
            else:
                lines.append(f"{keys[1]} uchun dollar kursi: o‘rtacha — 1 USD uchun {money(after['rate_mean'])} UZS; kunlik oraliq — {money(after['rate_min'])}–{money(after['rate_max'])} UZS ({after['rate_days']} kun).")
        else:
            lines.append('В справочнике нет курса за целевой месяц; курс не подставлен из другого периода.' if lang=='ru' else 'Maqsadli oy uchun kurs yo‘q; boshqa davr kursi qo‘yilmadi.')
    subject = ('Сумма зарегистрированных экспортных сделок' if plan.contract_type=='Экспортный' else 'Сумма зарегистрированных сделок') if lang=='ru' else ('Eksport bitimlarining qayd etilgan summasi' if plan.contract_type=='Экспортный' else 'Bitimlarning qayd etilgan summasi')
    if plan.metric=='count': subject = 'Число сделок' if lang=='ru' else 'Bitimlar soni'
    if plan.commodity: subject += ' — '+commodity_label(plan.commodity,lang)
    lines.append(subject+': '+f"{keys[0]} — {money(before[measure],places)} {unit}; {keys[1]} — {money(after[measure],places)} {unit}.")
    if before['deals']==0 and after['deals']==0:
        lines.append('В предоставленном наборе сделки по этим условиям за оба месяца не найдены. Рост по нулевой базе рассчитать нельзя.' if lang=='ru' else 'Berilgan to‘plamda ikkala oy uchun bu shartlarga mos bitim topilmadi. Nol asosdan o‘sishni hisoblab bo‘lmaydi.')
    delta = Decimal(change['difference'])
    signed_delta = ('+' if delta>0 else '')+money(delta,places)
    relative = change['relative_percent']
    relative_text = (('+' if Decimal(relative)>0 else '')+money(relative)+'%') if relative is not None else ('не определено: исходное значение равно 0' if lang=='ru' else 'aniqlanmagan: boshlang‘ich qiymat 0')
    lines.append((f"{keys[1]} относительно {keys[0]}: изменение {signed_delta} {unit}; относительное изменение — {relative_text}." if lang=='ru' else f"{keys[1]} {keys[0]} ga nisbatan: farq {signed_delta} {unit}; nisbiy o‘zgarish — {relative_text}."))
    snapshot = date.fromisoformat(SNAPSHOT)
    if any(start<=snapshot<month_end(start) for start in [comparison.baseline,comparison.target]):
        lines.append('Сделки за 2026-10 представлены только по 30.10.2026; это неполный месяц.' if lang=='ru' else '2026-10 bitimlari faqat 30.10.2026 gacha berilgan; bu to‘liq oy emas.')
    if comparison.include_usd_rate:
        lines.append('Источник курса — usd_rates.csv из набора задания UZEX; это данные задания, а не текущая котировка.' if lang=='ru' else 'Kurs manbasi — UZEX topshiriq to‘plamidagi usd_rates.csv; bu topshiriq ma’lumoti, joriy kotirovka emas.')
    columns = [column('label',lang),column('deals',lang,'integer')]
    if plan.metric=='amount': columns.append(column('amount',lang,'decimal') | {'unit':plan.report_currency})
    if comparison.include_usd_rate:
        columns += [{'key':'rate_mean','label':'Средний курс' if lang=='ru' else 'O‘rtacha kurs','kind':'decimal','unit':'UZS/USD'},
                    {'key':'rate_min','label':'Мин. курс' if lang=='ru' else 'Eng past kurs','kind':'decimal','unit':'UZS/USD'},
                    {'key':'rate_max','label':'Макс. курс' if lang=='ru' else 'Eng yuqori kurs','kind':'decimal','unit':'UZS/USD'}]
    response = result('\n'.join(lines),rows,columns,sql,actual_params,total['count'],plan,{'from':total['first_date'],'to':total['last_date']},lang=lang)
    response['provenance']['comparison'] = {'from':keys[0],'to':keys[1],**change,'currency':plan.report_currency if plan.metric=='amount' else None}
    response['provenance']['method'] = ('Изменение = целевой месяц − базовый месяц. Относительное изменение = разница ÷ базовый месяц × 100; при нулевой базе не определено. Суммы USD приведены к UZS по дате каждой сделки. Средний курс = сумма дневных курсов ÷ число дней; курс не взвешен по сделкам и не используется вместо дневного курса при пересчёте сумм.' if lang=='ru' else 'Farq = maqsadli oy − asosiy oy. Nisbiy o‘zgarish = farq ÷ asosiy oy × 100; asos 0 bo‘lsa aniqlanmagan. USD summalari har bir bitim sanasidagi kurs bilan UZSga o‘tkaziladi. O‘rtacha kurs = kunlik kurslar yig‘indisi ÷ kunlar soni; bitimlar bilan tortilmagan va summalarni o‘girishda kunlik kursning o‘rnini bosmaydi.')
    return response
