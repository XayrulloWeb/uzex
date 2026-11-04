"""Integration checks against independently computed CSV reference answers."""
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import app
from server.analytics import Scope, summary
from server.db import query

REFERENCES={x['id']:x['expected'] for x in json.loads((Path(__file__).parents[1]/'docs/reference-questions.json').read_text())['questions']}
client=TestClient(app)


@pytest.mark.parametrize('year,expected',[(2022,84299),(2023,93985),(2024,106647),(2025,115763),(2026,99306),(0,500000)])
def test_complete_year_counts(year,expected):
    r=client.get('/api/overview',params={'year':year})
    assert r.status_code==200
    assert r.json()['metrics']['deals']==expected
    assert sum(row['deals'] for row in r.json()['monthly'])==expected


def test_full_amount_matches_independent_decimal_reference():
    result=client.get('/api/overview?year=0').json()
    assert Decimal(result['metrics']['amount_uzs'])==Decimal(REFERENCES['all_years_registered_amount']['amount_uzs_exact'])
    assert sum(Decimal(x['amount_uzs']) for x in result['monthly'])==Decimal(result['metrics']['amount_uzs'])


@pytest.mark.parametrize('year,key',[(2024,'export_2024'),(2025,'export_2025')])
def test_daily_fx_aggregation(year,key):
    r=client.get('/api/reports/exports',params={'year':year}).json()
    assert r['totals']['deals']==REFERENCES[key]['count']
    assert Decimal(r['totals']['amount_uzs'])==Decimal(REFERENCES[key]['amount_uzs_exact'])


def test_large_lot_is_not_a_physical_quantity():
    r=client.get('/api/deals/100007').json()
    assert Decimal(r['quantity'])==Decimal(REFERENCES['nonunit_lot_volume']['physical_volume'])
    assert Decimal(r['lot_count'])==48 and Decimal(r['lot_size'])==1000


def test_export_detail_keeps_native_currency():
    r=client.get('/api/deals/100024').json()
    expected=REFERENCES['export_deal_conversion']
    assert r['currency']=='USD'
    assert Decimal(r['amount_native'])==Decimal(expected['amount_usd'])
    assert Decimal(r['amount_uzs'])==Decimal(expected['amount_uzs_exact'])


def test_cancellations_and_late_fulfilled_deliveries():
    result=client.get('/api/overview?year=2025').json()
    assert result['metrics']['cancelled']==REFERENCES['cancelled_2025']['count']
    active=client.get('/api/overview?year=2025&status=active').json()
    assert active['metrics']['deals']==115763-8085
    result=client.get('/api/reports/late?year=2024&status=fulfilled').json()
    assert result['totals']['deals']==REFERENCES['late_fulfilled_2024']['count']


def test_diesel_is_not_fuel_oil():
    diesel=client.get('/api/overview?year=2024&commodity=diesel').json()
    fuel=client.get('/api/overview?year=2024&commodity=fuel_oil').json()
    assert diesel['metrics']['deals']>0 and fuel['metrics']['deals']>0
    assert {x['id'] for x in diesel['commodities']}=={'diesel'}
    assert {x['id'] for x in fuel['commodities']}=={'fuel_oil'}
    result=query("SELECT sum(amount_uzs) amount, sum(CASE WHEN unit='тонна' THEN quantity*1000 ELSE quantity END) kg FROM trades WHERE year(deal_date)=2024 AND commodity='diesel' AND contract_type='Внутренний' AND status<>'Аннулирован(Не оплачен)'")[0]
    expected=REFERENCES['weighted_diesel_price_2024']
    assert Decimal(result['amount'])==Decimal(expected['amount_uzs'])
    assert Decimal(result['kg'])==Decimal(expected['quantity_kg'])


def test_region_filter_and_routes_are_consistent():
    r=client.get('/api/overview?year=2025&region=tashkent_city').json()
    assert {x['id'] for x in r['regions']}=={'tashkent_city'}
    assert all(x['origin']=='tashkent_city' and x['destination']!='tashkent_city' for x in r['routes'])
    assert sum(Decimal(x['amount_uzs']) for x in r['commodities'])==Decimal(r['metrics']['amount_uzs'])


def test_months_report_contains_whole_period():
    result=client.get('/api/reports/months?year=0').json()
    assert len(result['rows'])==58
    assert sum(x['deals'] for x in result['rows'])==500000


def test_pagination_search_and_unknown_ids():
    first=client.get('/api/deals?year=2025&limit=3').json()
    second=client.get('/api/deals?year=2025&limit=3&offset=3').json()
    assert first['total']==115763
    assert not {x['deal_id'] for x in first['rows']} & {x['deal_id'] for x in second['rows']}
    assert client.get('/api/deals/999999999').status_code==404
    assert client.get('/api/deals',params={'year':0,'search':"' OR 1=1; DROP TABLE trades; --"}).json()['total']==0
    assert client.get('/api/health').json()['deals']==500000


@pytest.mark.parametrize('url',['/api/overview?year=2027','/api/overview?year=1','/api/overview?region=unknown','/api/overview?commodity=unknown','/api/deals?limit=100000','/api/overview?status=unknown'])
def test_invalid_scope_is_rejected(url):
    assert client.get(url).status_code==422


def test_parallel_read_requests():
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda year:summary(Scope(year=year))['metrics']['deals'],[2022,2023,2024,2025]))
    assert results==[84299,93985,106647,115763]


@pytest.mark.parametrize('name,grade',[
    ('ХЛОПОК СЫРЕЦ (СПОТ) 3 СОРТ II КЛАСС','3'),
    ('Хлопок-сырец I сорт II класс','1'),
    ('Хлопок-сырец II сорт I класс','2'),
    ('Хлопок-сырец I класс',''),
])
def test_grade_is_not_confused_with_quality_class(name,grade):
    from server.catalog import normalized_grade
    assert normalized_grade(name)==grade
