"""Verified, repeatable CSV → typed DuckDB import. Never modifies input files."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import duckdb

from server.catalog import REGION_BY_RAW, commodity_for, normalize, normalized_grade

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 3
YEARS = {2022: 84299, 2023: 93985, 2024: 106647, 2025: 115763, 2026: 99306}


def file_hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def decimal(column: str, precision='24,4') -> str:
    return f"CAST(replace(replace({q(column)}, ' ', ''), chr(160), '') AS DECIMAL({precision}))"


def date_column(column: str) -> str:
    return f"CAST(strptime(NULLIF({q(column)}, ''), '%d.%m.%Y') AS DATE)"


def build_database(raw: Path | None = None, database: Path | None = None, force=False) -> Path:
    database = database or Path(os.environ.get('UZEX_DB_PATH', ROOT / 'data/uzex.duckdb'))
    manifest_path = database.with_name('import-manifest.json')
    names = [f'deals_{y}.csv' for y in YEARS] + ['contracts.csv', 'participants.csv', 'brokers.csv', 'usd_rates.csv']
    raw = raw or Path(os.environ.get('UZEX_DATA_DIR', ROOT / 'data/raw'))
    hashes = {name: file_hash(raw / name) for name in names}
    expected = json.loads((ROOT / 'docs/data-audit.json').read_text(encoding='utf-8'))
    for name, value in hashes.items():
        if value != expected['source_files'][name]['sha256']:
            raise ValueError(f'Checksum mismatch for {name}; re-audit changed source data before import.')
    if database.exists() and manifest_path.exists() and not force:
        old = json.loads(manifest_path.read_text(encoding='utf-8'))
        if old.get('schema_version') == SCHEMA_VERSION and old.get('sha256') == hashes:
            print('Verified existing database:', database)
            return database
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = database.with_suffix('.building.duckdb')
    if temporary.exists():
        temporary.unlink()
    con = duckdb.connect(str(temporary))
    con.execute("SET threads=3")
    con.execute("SET memory_limit='2GB'")

    def load(name):
        con.execute('CREATE OR REPLACE TEMP TABLE source AS SELECT * FROM read_csv(?, all_varchar=true, nullstr=\'\', strict_mode=true)', [str(raw / name)])

    load('participants.csv')
    con.execute('CREATE TABLE participants AS SELECT "ИНН" AS inn, "Наименование" AS name, "Регион" AS region_raw, "Вид деятельности" AS activity, "Роль" AS role, "Плательщик НДС" = \'Да\' AS vat_payer FROM source')
    load('brokers.csv')
    con.execute('CREATE TABLE brokers AS SELECT "Код брокера" AS code, "Наименование" AS name, "ИНН" AS inn, "Регион" AS region_raw FROM source')
    load('usd_rates.csv')
    con.execute(f'CREATE TABLE usd_rates AS SELECT {date_column("Дата")} rate_date, {decimal("Курс", "18,4")} usd_rate FROM source')
    load('contracts.csv')
    fields = {
        'contract_id': q('Номер контракта'), 'product_name': q('Наименование продукта'),
        'brand': "coalesce(\"Марка товара\", '')", 'size': "coalesce(\"Размер товара\", '')", 'grade': "coalesce(\"Сорт товара\", '')",
        'product_type': "coalesce(\"Тип товара\", '')", 'quality_class': "coalesce(\"Класс товара\", '')", 'tnved': q('Код ТН ВЭД'),
        'commodity_group': q('Группа товара'), 'category': q('Категория товара'), 'industry': q('Отрасль промышленности'),
        'unit': q('Единица измерения'), 'lot_size': decimal('Лот', '18,4'),
        'currency': "CASE WHEN \"Валюта\"='Доллар США' THEN 'USD' ELSE 'UZS' END", 'base_price': decimal('Базисная цена'),
        'deposit': q('Сумма залога'), 'basis': q('Базис поставки'), 'region_raw': q('Регион'), 'warehouse': q('Адрес склада'),
        'auction': q('Тип торгов'), 'contract_type': q('Тип контракта'), 'form': q('Форма контракта'),
        'payment_days': 'CAST("Срок оплаты" AS INTEGER)', 'delivery_days': 'CAST("Срок поставки" AS INTEGER)', 'packaging': q('Упаковка'),
        'seller_inn': q('ИНН продавца'), 'registered_date': date_column('Дата регистрации'), 'valid_until': date_column('Действует до'),
    }
    con.execute('CREATE TABLE contracts AS SELECT ' + ', '.join(f'{value} AS {q(key)}' for key, value in fields.items()) + ' FROM source')
    con.execute('ALTER TABLE contracts ADD COLUMN commodity VARCHAR')
    con.execute('ALTER TABLE contracts ADD COLUMN search_text VARCHAR')
    con.execute('ALTER TABLE contracts ADD COLUMN grade_norm VARCHAR')
    values = []
    for cid, code, name, brand, size, grade, typ, quality in con.execute('SELECT contract_id, tnved, product_name, brand, size, grade, product_type, quality_class FROM contracts').fetchall():
        text = normalize(' '.join([name, brand, size, grade, typ, quality]))
        values.append((commodity_for(code, name), text, normalized_grade(grade or name), cid))
    con.executemany('UPDATE contracts SET commodity=?, search_text=?, grade_norm=? WHERE contract_id=?', values)
    for year, count in YEARS.items():
        load(f'deals_{year}.csv')
        if con.execute('SELECT count(*) FROM source').fetchone()[0] != count:
            raise ValueError(f'Unexpected row count for {year}')
        fields = {
            'deal_id': 'CAST("Номер сделки" AS BIGINT)', 'deal_date': date_column('Дата сделки'), 'deal_time': 'CAST("Время сделки" AS TIME)',
            'auction': q('Тип торгов'), 'lot_count': decimal('Количество', '18,4'), 'amount_native': decimal('Сумма сделки'),
            'start_price': decimal('Стартовая цена'), 'contract_id': q('Номер контракта'), 'product_label': q('Наименование товара'),
            'lot_size': decimal('Лот', '18,4'), 'unit': q('Единица измерения'), 'warehouse_region_raw': q('Регион'),
            'contract_type': q('Тип контракта'), 'form': q('Форма контракта'), 'status': q('Состояние сделки'),
            'seller_inn': q('ИНН продавца'), 'buyer_inn': q('ИНН покупателя'), 'seller_broker': q('Брокер продавца'), 'buyer_broker': q('Брокер покупателя'),
            'payment_date': date_column('Дата оплаты'), 'delivery_date': date_column('Дата поставки'), 'delivered_lots': decimal('Поставлено', '18,4'),
        }
        prefix = 'CREATE TABLE deals AS' if year == 2022 else 'INSERT INTO deals'
        con.execute(prefix + ' SELECT ' + ', '.join(f'{value} AS {q(key)}' for key, value in fields.items()) + ' FROM source')
        print('Imported', year, count)
    con.execute('CREATE TABLE region_names (raw VARCHAR PRIMARY KEY, region VARCHAR)')
    con.executemany('INSERT INTO region_names VALUES (?, ?)', list(REGION_BY_RAW.items()))
    con.execute('''CREATE TABLE trades AS
        SELECT d.*, c.currency, c.commodity, c.category, c.industry, c.tnved, c.product_name,
            c.brand, c.size, c.grade, c.quality_class, c.grade_norm, c.search_text,
            c.payment_days, c.delivery_days, r.region, fx.usd_rate,
            CAST(d.lot_count*d.lot_size AS DECIMAL(24,4)) quantity,
            CAST(d.delivered_lots*d.lot_size AS DECIMAL(24,4)) delivered_quantity,
            CAST(CASE WHEN c.currency='USD' THEN d.amount_native*fx.usd_rate ELSE d.amount_native END AS DECIMAL(30,8)) amount_uzs,
            s.name seller_name, b.name buyer_name,
            d.delivery_date > d.payment_date + c.delivery_days late_delivery
        FROM deals d JOIN contracts c USING (contract_id)
        JOIN usd_rates fx ON d.deal_date=fx.rate_date
        JOIN region_names r ON d.warehouse_region_raw=r.raw
        JOIN participants s ON d.seller_inn=s.inn
        JOIN participants b ON d.buyer_inn=b.inn''')
    con.execute('CREATE INDEX deal_number ON trades(deal_id)')
    con.execute('CREATE INDEX contract_number ON trades(contract_id)')
    total, unique_count = con.execute('SELECT count(*), count(DISTINCT deal_id) FROM trades').fetchone()
    if total != 500000 or unique_count != total:
        raise ValueError('Import completeness or uniqueness failed')
    expected_amount = expected['amounts_uzs_by_scope']['all_registered']
    from decimal import Decimal
    if con.execute('SELECT sum(amount_uzs) FROM trades').fetchone()[0] != Decimal(expected_amount):
        raise ValueError('Monetary aggregate does not match independent source audit')
    con.execute('CHECKPOINT')
    con.close()
    temporary.replace(database)
    manifest_path.write_text(json.dumps({'schema_version': SCHEMA_VERSION, 'sha256': hashes, 'deal_count': total, 'snapshot': '2026-10-30'}, ensure_ascii=False, indent=2)+'\n')
    print('Verified database:', database)
    return database


if __name__ == '__main__':
    build_database()
