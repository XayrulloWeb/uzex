from __future__ import annotations

from functools import lru_cache
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from server.catalog import CANCELLED, COMMODITIES, COMMODITY_BY_ID, REGIONS, REGION_BY_ID, SNAPSHOT, commodity_label, region_label, normalize
from server.db import query


class Scope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    year: int | None = Field(default=2026, ge=2022, le=2026)
    region: str | None = None
    commodity: str | None = None
    status: Literal['all', 'active', 'fulfilled'] = 'all'


def where(scope: Scope):
    clauses, params = ['TRUE'], []
    if scope.year:
        clauses.append('year(deal_date)=?')
        params.append(scope.year)
    if scope.region:
        if scope.region not in REGION_BY_ID:
            raise ValueError('Unknown region')
        clauses.append('region=?')
        params.append(scope.region)
    if scope.commodity:
        if scope.commodity not in COMMODITY_BY_ID:
            raise ValueError('Unknown commodity')
        clauses.append('commodity=?')
        params.append(scope.commodity)
    if scope.status == 'active':
        clauses.append('status<>?')
        params.append(CANCELLED)
    elif scope.status == 'fulfilled':
        clauses.append("status='Исполнен'")
    return ' AND '.join(clauses), params


@lru_cache(maxsize=256)
def summary_cached(year, region, commodity, status):
    scope = Scope(year=year, region=region, commodity=commodity, status=status)
    condition, params = where(scope)
    metrics = query(f'''SELECT count(*) deals, coalesce(sum(amount_uzs),0) amount_uzs,
        count(DISTINCT seller_inn) sellers, count(DISTINCT buyer_inn) buyers,
        count(*) FILTER (WHERE status='{CANCELLED}') cancelled,
        count(*) FILTER (WHERE status='Исполнен') fulfilled,
        count(*) FILTER (WHERE currency='USD') export_deals,
        coalesce(sum(amount_uzs) FILTER (WHERE currency='USD'),0) export_amount_uzs,
        min(deal_date) first_date, max(deal_date) last_date
        FROM trades WHERE {condition}''', params)[0]
    monthly = query(f'''SELECT strftime(deal_date,'%Y-%m') period, count(*) deals, sum(amount_uzs) amount_uzs
        FROM trades WHERE {condition} GROUP BY period ORDER BY period''', params)
    regions = query(f'''SELECT region id, count(*) deals, sum(amount_uzs) amount_uzs
        FROM trades WHERE {condition} GROUP BY region ORDER BY sum(amount_uzs) DESC''', params)
    commodities = query(f'''SELECT commodity id, count(*) deals, sum(amount_uzs) amount_uzs
        FROM trades WHERE {condition} GROUP BY commodity ORDER BY sum(amount_uzs) DESC''', params)
    # A route is derived from seller warehouse → buyer registration region, not an invented live transaction.
    # Route queries use a filtered subquery to keep the selected warehouse region unambiguous.
    routes = query(f'''SELECT t.region origin, r.region destination, count(*) deals, sum(t.amount_uzs) amount_uzs
        FROM (SELECT * FROM trades WHERE {condition}) t
        JOIN participants b ON t.buyer_inn=b.inn JOIN region_names r ON b.region_raw=r.raw
        WHERE t.region<>r.region GROUP BY t.region,r.region ORDER BY sum(t.amount_uzs) DESC LIMIT 12''', params)
    return {'metrics': metrics, 'monthly': monthly, 'regions': regions, 'commodities': commodities, 'routes': routes,
            'snapshot': SNAPSHOT, 'scope': scope.model_dump(), 'total_dataset_deals': 500000}


def summary(scope: Scope):
    return summary_cached(scope.year, scope.region, scope.commodity, scope.status)


def registry(scope: Scope, search='', offset=0, limit=15):
    condition, params = where(scope)
    search = search.strip()
    if search:
        normalized_search = normalize(search)
        matched = [c[0] for c in COMMODITIES if normalized_search in {normalize(c[2]),normalize(c[3]),*(normalize(alias.strip()) for alias in c[4])}]
        extra = ' OR commodity=?' if len(matched)==1 else ''
        condition += ' AND (CAST(deal_id AS VARCHAR)=? OR contract_id=? OR seller_inn=? OR buyer_inn=? OR product_label ILIKE ? OR seller_name ILIKE ? OR buyer_name ILIKE ?'+extra+')'
        params += [search, search, search, search, '%'+search+'%', '%'+search+'%', '%'+search+'%'] + (matched if len(matched)==1 else [])
    total = query(f'SELECT count(*) total FROM trades WHERE {condition}', params)[0]['total']
    rows = query(f'''SELECT deal_id, deal_date, contract_id, product_label, commodity, region, lot_count, lot_size, quantity, unit,
        amount_native, currency, amount_uzs, status, seller_name, seller_inn, buyer_name, buyer_inn
        FROM trades WHERE {condition} ORDER BY deal_date DESC,deal_id DESC LIMIT ? OFFSET ?''', params+[limit, offset])
    return {'total': total, 'rows': rows, 'offset': offset, 'limit': limit, 'scope': scope.model_dump()}


def deal(identity: int):
    rows = query('SELECT * FROM trades WHERE deal_id=?', [identity])
    if not rows:
        return None
    row = rows[0]
    from decimal import Decimal
    row['unit_price_native'] = str(Decimal(row['amount_native'])/Decimal(row['quantity']))
    row['contract'] = query('SELECT * FROM contracts WHERE contract_id=?', [row['contract_id']])[0]
    row['seller_broker_detail'] = query('SELECT * FROM brokers WHERE code=?', [row['seller_broker']])[0]
    row['buyer_broker_detail'] = query('SELECT * FROM brokers WHERE code=?', [row['buyer_broker']])[0]
    return row


def catalog():
    return {
        'regions': [{'id': r[0], 'raw': r[1], 'ru': r[2], 'uz': r[3], 'lng': r[4], 'lat': r[5]} for r in REGIONS],
        'commodities': [{'id': c[0], 'code': c[1], 'ru': c[2], 'uz': c[3]} for c in COMMODITIES],
        'years': [2022,2023,2024,2025,2026], 'snapshot': SNAPSHOT, 'total_deals': 500000,
        'engine': 'local', 'ai_enabled': False,
    }


def report(kind: str, scope: Scope, lang='ru'):
    """Explicit analytical operations; independent from a future language model."""
    condition, params = where(scope)
    uz = lang == 'uz'
    specifications = {
        'buyers': ('buyer_inn', 'buyer_name', 'Крупнейшие покупатели', 'Eng yirik xaridorlar'),
        'sellers': ('seller_inn', 'seller_name', 'Крупнейшие продавцы', 'Eng yirik sotuvchilar'),
        'commodities': ('commodity', 'commodity', 'Структура товарного рынка', 'Tovar bozori tarkibi'),
        'regions': ('region', 'region', 'Регионы по сумме сделок', 'Bitimlar summasi bo‘yicha hududlar'),
        'statuses': ('status', 'status', 'Состояния сделок', 'Bitim holatlari'),
        'months': ("strftime(deal_date,'%Y-%m')", "strftime(deal_date,'%Y-%m')", 'Динамика по месяцам', 'Oylar bo‘yicha dinamika'),
        'exports': ('currency', 'currency', 'Экспортные сделки', 'Eksport bitimlari'),
        'late': ('seller_inn', 'seller_name', 'Завершённые поставки с опозданием', 'Kech yakunlangan yetkazib berishlar'),
    }
    if kind not in specifications:
        raise ValueError('Unknown report')
    if kind == 'exports':
        condition += " AND currency='USD'"
    if kind == 'late':
        condition += ' AND late_delivery=TRUE'
    key, label, ru_title, uz_title = specifications[kind]
    sql = f'''SELECT {key} AS id, {label} AS label, count(*) AS deals, sum(amount_uzs) AS amount_uzs
        FROM trades WHERE {condition} GROUP BY 1,2 ORDER BY {'id' if kind=='months' else 'sum(amount_uzs) DESC, id'} LIMIT {120 if kind=='months' else 20}'''
    rows = query(sql, params)
    for row in rows:
        if kind == 'regions': row['label'] = region_label(row['id'], lang)
        if kind == 'commodities': row['label'] = commodity_label(row['id'], lang)
        if kind == 'statuses' and uz:
            from server.catalog import STATUS_UZ
            row['label'] = STATUS_UZ.get(row['id'], row['id'])
    totals = query(f'SELECT count(*) deals, coalesce(sum(amount_uzs),0) amount_uzs FROM trades WHERE {condition}', params)[0]
    return {'kind': kind, 'title': uz_title if uz else ru_title, 'rows': rows, 'totals': totals, 'scope': scope.model_dump(),
            'provenance': {'sources': ['deals_*.csv', 'contracts.csv', 'participants.csv', 'usd_rates.csv'], 'sql': sql,
                'parameters': params, 'snapshot': SNAPSHOT, 'method': 'amount_uzs = amount_native × usd_rate on deal date for USD; UZS unchanged',
                'status': scope.status, 'row_count': totals['deals']}}
