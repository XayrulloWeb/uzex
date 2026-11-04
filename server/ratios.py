"""Shares and changes computed from exact aggregates, never model prose."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext

from server.catalog import SNAPSHOT, commodity_label, region_label
from server.db import query


def percentage(numerator, denominator):
    with localcontext() as context:
        context.prec = 38
        denominator = Decimal(str(denominator))
        return format(Decimal(str(numerator))*100/denominator,'f') if denominator else None


def changes(before, after):
    if before is None or after is None: return {'difference':None,'relative_percent':None}
    with localcontext() as context:
        context.prec = 38
        difference = Decimal(str(after))-Decimal(str(before))
        return {'difference':format(difference,'f'),'relative_percent':percentage(difference,before)}


def partial_year_note(plan, lang):
    snapshot = date.fromisoformat(SNAPSHOT)
    years = plan.years or ([plan.year] if plan.year else list(range(plan.date_from.year,plan.date_to.year+1)) if plan.date_from and plan.date_to else [])
    if snapshot.year not in years: return ''
    if plan.date_to and plan.date_to<snapshot: return ''
    if len(years)<2:
        return 'Данные за 2026 год доступны только по 30.10.2026.' if lang=='ru' else '2026-yil ma’lumotlari faqat 30.10.2026 sanasigacha mavjud.'
    return ('2026 год представлен только по 30.10.2026; сравнение использует доступные данные, а не два полных года.' if lang=='ru' else '2026-yil faqat 30.10.2026 sanasigacha berilgan; taqqoslash ikki to‘liq yilni emas, mavjud ma’lumotlarni qamrab oladi.')


def target_label(target, lang):
    if target.dimension=='contract_type':
        return ('экспортных сделок' if target.value=='Экспортный' else 'внутренних сделок') if lang=='ru' else ('eksport bitimlari' if target.value=='Экспортный' else 'ichki bitimlar')
    if target.dimension=='commodity': return commodity_label(target.value,lang)
    if target.dimension=='region': return region_label(target.value,lang)
    return target.value


def share_result(plan, lang, condition, parameters, total):
    from server.ai_analytics import column, outcome, result, scope_text
    from server.ai_models import money
    target = plan.share_target
    if target is None: return outcome('share_definition',lang,'clarify')
    if plan.share_basis!='count' and plan.report_currency!='UZS': return outcome('share_currency',lang,'clarify')
    dims = {'year':(f'year({plan.date_field})',f'year({plan.date_field})'),
            'month':(f"strftime({plan.date_field},'%Y-%m')",f"strftime({plan.date_field},'%Y-%m')"),
            'buyer':('buyer_inn','buyer_name'),'seller':('seller_inn','seller_name'),
            'region':('region','region'),'commodity':('commodity','commodity'),
            'status':('status','status'),'form':('form','form'),'auction':('auction','auction'),
            'category':('category','category'),'broker':('broker_key','broker_name')}
    source = 'trades'
    if plan.group=='broker':
        source = '(SELECT t.*,b.code AS broker_key,b.name AS broker_name FROM trades t JOIN brokers b ON (t.seller_broker=b.code OR t.buyer_broker=b.code))'
    if plan.group=='none':
        prefix,group,order = '', '', ''
    else:
        key,label = dims[plan.group]
        prefix = key+' AS id,'+label+' AS label,'
        group = ' GROUP BY '+','.join(dict.fromkeys([key,label]))
        rank='target_deals*1.0/nullif(deals,0)' if plan.share_basis=='count' else 'target_amount/nullif(amount,0)'
        order = ' ORDER BY id' if plan.group in ['year','month'] else ' ORDER BY '+rank+' '+plan.order.upper()+',id'
    sql = f'''SELECT {prefix}count(*) AS deals,coalesce(sum(amount_uzs),0) AS amount,
        count(*) FILTER (WHERE {target.dimension}=?) AS target_deals,
        coalesce(sum(amount_uzs) FILTER (WHERE {target.dimension}=?),0) AS target_amount,
        min({plan.date_field}) AS first_date,max({plan.date_field}) AS last_date
        FROM {source} WHERE {condition}{group}{order} LIMIT ?'''
    actual_params = [target.value,target.value]+parameters+[120 if plan.group in ['year','month'] else plan.limit if plan.group=='none' else 20000]
    rows = query(sql,actual_params)
    if plan.group=='year':
        # A covered year with no matching denominator has an undefined share.
        expected = plan.years or ([plan.year] if plan.year else list(range(plan.date_from.year,plan.date_to.year+1)) if plan.date_from and plan.date_to else [])
        indexed = {int(row['id']):row for row in rows}
        rows = [indexed.get(year,{'id':year,'label':year,'deals':0,'amount':'0','target_deals':0,'target_amount':'0','first_date':None,'last_date':None}) for year in expected] if expected else rows
    for row in rows:
        if plan.group=='region': row['label']=region_label(row['id'],lang)
        if plan.group=='commodity': row['label']=commodity_label(row['id'],lang)
        row['period']=str(row.get('label',scope_text(plan,lang)))
        row['amount_share_pct']=percentage(row['target_amount'],row['amount'])
        row['count_share_pct']=percentage(row['target_deals'],row['deals'])
    if plan.group not in ['none','year','month']:
        rank='count_share_pct' if plan.share_basis=='count' else 'amount_share_pct'
        direction=Decimal(-1) if plan.order=='desc' else Decimal(1)
        rows.sort(key=lambda row:(row[rank] is None,direction*Decimal(row[rank] or 0),str(row['id'])))
        rows=rows[:plan.limit]
    columns=[{'key':'period','label':'Период / группа' if lang=='ru' else 'Davr / guruh','kind':'text'}]
    if plan.share_basis in ['amount','both']:
        columns += [{'key':'target_amount','label':'Сумма части' if lang=='ru' else 'Qism summasi','kind':'decimal','unit':'UZS'},
                    {'key':'amount','label':'Общая сумма' if lang=='ru' else 'Jami summa','kind':'decimal','unit':'UZS'},
                    {'key':'amount_share_pct','label':'Доля по сумме' if lang=='ru' else 'Summa ulushi','kind':'percent','unit':'%'}]
    if plan.share_basis in ['count','both']:
        columns += [{'key':'target_deals','label':'Сделок в части' if lang=='ru' else 'Qismdagi bitimlar','kind':'integer'},
                    column('deals',lang,'integer'),
                    {'key':'count_share_pct','label':'Доля по числу' if lang=='ru' else 'Son ulushi','kind':'percent','unit':'%'}]
    title = target_label(target,lang)
    lines = []
    comparisons=[]
    for basis,key in [('amount','amount_share_pct'),('count','count_share_pct')]:
        if plan.share_basis not in [basis,'both']: continue
        label = ('По сумме сделок (UZS)' if basis=='amount' else 'По числу сделок') if lang=='ru' else ('Bitimlar summasi bo‘yicha (UZS)' if basis=='amount' else 'Bitimlar soni bo‘yicha')
        values = '; '.join(row['period']+' — '+(money(row[key],4)+'%' if row[key] is not None else ('доля не определена: знаменатель 0' if lang=='ru' else 'ulush aniqlanmagan: maxraj 0')) for row in rows)
        lines.append(label+': '+values+'.')
        if plan.group=='year' and len(rows)>1:
            for before,after in zip(rows,rows[1:]):
                change=changes(before[key],after[key])
                comparisons.append({'basis':basis,'from':before['period'],'to':after['period'],'difference_pp':change['difference'],'relative_change_pct':change['relative_percent']})
                if change['difference'] is None:
                    lines.append('Разница не определена: отсутствует ненулевой знаменатель для одного из периодов.' if lang=='ru' else 'Farq aniqlanmagan: davrlardan birida maxraj nol.')
                    continue
                delta=Decimal(change['difference'])
                sign='+' if delta>0 else ''
                relative=change['relative_percent']
                reltext=(('относительное изменение доли — ' if lang=='ru' else 'ulushning nisbiy o‘zgarishi — ')+('+' if Decimal(relative)>0 else '')+money(relative)+'%') if relative is not None else ('относительное изменение не определено: исходная доля равна 0' if lang=='ru' else 'nisbiy o‘zgarish aniqlanmagan: boshlang‘ich ulush 0')
                lines.append((f"{before['period']} → {after['period']}: {sign}{money(delta,4)} п.п.; " if lang=='ru' else f"{before['period']} → {after['period']}: {sign}{money(delta,4)} foiz punkti; ")+reltext+'.')
    note=partial_year_note(plan,lang)
    if note: lines.append(note)
    answer=('Доля '+title+'.\n' if lang=='ru' else title+' ulushi.\n')+'\n'.join(lines)
    response=result(answer,rows,columns,sql,actual_params,total['count'],plan,{'from':total['first_date'],'to':total['last_date']},lang=lang)
    response['provenance']['method']=('Доля = часть ÷ общий итог × 100. Разница в п.п. = доля после − доля до. Относительное изменение = (доля после − доля до) ÷ доля до × 100. До деления суммы USD приведены к UZS по дате каждой сделки; промежуточные доли не округляются.' if lang=='ru' else 'Ulush = qism ÷ jami × 100. Foiz punktidagi farq = keyingi ulush − oldingi ulush. Nisbiy o‘zgarish = (keyingi ulush − oldingi ulush) ÷ oldingi ulush × 100. USD har bir bitim sanasidagi kurs bilan UZSga o‘tkaziladi; oraliq ulushlar yaxlitlanmaydi.')
    response['provenance']['share_target']=target.model_dump()
    response['provenance']['comparison']=comparisons
    return response


def comparison_answer(plan, rows, lang):
    from server.ai_models import money
    if not plan.comparison or plan.group!='year' or plan.metric not in ['amount','count','volume'] or len(rows)<2: return None
    key='amount' if plan.metric=='amount' else 'quantity' if plan.metric=='volume' else 'deals'
    if plan.metric=='volume' and len({row['unit'] for row in rows})>1: return None
    unit=plan.report_currency if plan.metric=='amount' else rows[0]['unit'] if plan.metric=='volume' else ('сделок' if lang=='ru' else 'ta bitim')
    lines=['; '.join(str(row['id'])+' — '+money(row[key],0 if plan.metric=='count' else 2)+' '+unit for row in rows)+'.']
    for before,after in zip(rows,rows[1:]):
        change=changes(before[key],after[key]);delta=Decimal(change['difference'])
        rel=change['relative_percent']
        relative=(('+' if Decimal(rel)>0 else '')+money(rel)+'%') if rel is not None else ('не определено при исходном значении 0' if lang=='ru' else 'boshlang‘ich qiymat 0 bo‘lganda aniqlanmaydi')
        lines.append(f"{before['id']} → {after['id']}: "+('разница ' if lang=='ru' else 'farq ')+('+' if delta>0 else '')+money(delta,0 if plan.metric=='count' else 2)+' '+unit+'; '+('относительное изменение ' if lang=='ru' else 'nisbiy o‘zgarish ')+relative+'.')
    note=partial_year_note(plan,lang)
    if note: lines.append(note)
    return '\n'.join(lines)
