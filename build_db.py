"""
UZEX Database Builder
Loads CSV files from the dataset folder into a high-performance SQLite database:
- Cleans and converts numbers (spaces in numbers removed)
- Converts dates DD.MM.YYYY to ISO YYYY-MM-DD
- Precalculates USD exchange rates, deal_amount_uzs, volume_units, unit_price
- Builds FTS5 search indexes for participants, contracts, and brokers
- Creates optimized B-Tree indexes for fast analytical aggregations
"""

import os
import sys
import csv
import sqlite3
import time
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
if not os.path.exists(DATA_DIR):
    # fallback to downloads if running locally
    DATA_DIR = r"C:\Users\user\Downloads\uzex_spot_data\uzex_spot_data"
DB_PATH = os.path.join(os.path.dirname(__file__), "uzex.db")

def parse_date(d_str):
    if not d_str or not d_str.strip():
        return None
    d_str = d_str.strip()
    try:
        parts = d_str.split('.')
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    except Exception:
        pass
    return d_str

def parse_num(val_str, default=0.0):
    if not val_str or not val_str.strip():
        return default
    # remove spaces and percent signs
    clean = val_str.replace(' ', '').replace('%', '').strip()
    try:
        return float(clean)
    except ValueError:
        return default

def clean_text(text):
    if not text:
        return ""
    # strip quotes, normalize spaces
    t = text.strip().strip('"').strip("'").strip()
    return t

# Region mapping RU <-> UZ
RU_TO_UZ_REGION = {
    'Андижанская область': 'Andijon viloyati',
    'Бухарская область': 'Buxoro viloyati',
    'Джизакская область': 'Jizzax viloyati',
    'Кашкадарьинская область': 'Qashqadaryo viloyati',
    'Навоийская область': 'Navoiy viloyati',
    'Наманганская область': 'Namangan viloyati',
    'Республика Каракалпакстан': 'Qoraqalpog‘iston Respublikasi',
    'Самаркандская область': 'Samarqand viloyati',
    'Сурхандарьинская область': 'Surxondaryo viloyati',
    'Сырдарьинская область': 'Sirdaryo viloyati',
    'Ташкентская область': 'Toshkent viloyati',
    'Ферганская область': 'Farg‘ona viloyati',
    'Хорезмская область': 'Xorazm viloyati',
    'г. Ташкент': 'Toshkent shahri'
}

UZ_TO_RU_REGION = {v: k for k, v in RU_TO_UZ_REGION.items()}

def main():
    start_time = time.time()
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
            print(f"Removed existing {DB_PATH}")
        except Exception as e:
            print(f"Warning: {e}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Enable WAL mode & performance tuning
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA cache_size = -64000;") # 64MB cache
    cur.execute("PRAGMA temp_store = MEMORY;")

    print("1. Creating schema...")

    cur.execute("""
    CREATE TABLE usd_rates (
        rate_date TEXT PRIMARY KEY,
        usd_rate REAL NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE brokers (
        broker_code TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        clean_name TEXT,
        inn TEXT,
        region TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE participants (
        inn TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        clean_name TEXT,
        region TEXT,
        activity TEXT,
        role TEXT,
        is_vat_payer TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE contracts (
        contract_num TEXT PRIMARY KEY,
        product_name TEXT,
        brand TEXT,
        size TEXT,
        grade TEXT,
        product_type TEXT,
        product_class TEXT,
        hs_code TEXT,
        product_group TEXT,
        category TEXT,
        industry TEXT,
        unit TEXT,
        lot REAL,
        currency TEXT,
        base_price REAL,
        deposit_pct REAL,
        delivery_basis TEXT,
        region_ru TEXT,
        region_uz TEXT,
        warehouse_address TEXT,
        trade_type TEXT,
        contract_type TEXT,
        contract_form TEXT,
        payment_term_days INTEGER,
        delivery_term_days INTEGER,
        packaging TEXT,
        seller_inn TEXT,
        reg_date TEXT,
        valid_until TEXT,
        full_product_desc TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE deals (
        deal_num INTEGER PRIMARY KEY,
        deal_date TEXT NOT NULL,
        deal_time TEXT NOT NULL,
        trade_type TEXT,
        quantity REAL,
        deal_amount REAL,
        start_price REAL,
        contract_num TEXT,
        product_name TEXT,
        lot REAL,
        unit TEXT,
        region TEXT,
        contract_type TEXT,
        contract_form TEXT,
        status TEXT,
        seller_inn TEXT,
        buyer_inn TEXT,
        seller_broker TEXT,
        buyer_broker TEXT,
        payment_date TEXT,
        delivery_date TEXT,
        delivered_qty REAL,
        -- precalculated analytics
        currency TEXT,
        usd_rate REAL,
        volume_units REAL,
        unit_price REAL,
        deal_amount_uzs REAL,
        deal_amount_usd REAL
    );
    """)

    print("2. Loading usd_rates.csv...")
    rates_map = {}
    with open(os.path.join(DATA_DIR, "usd_rates.csv"), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rates_batch = []
        for row in reader:
            d_iso = parse_date(row['Дата'])
            rate = parse_num(row['Курс'])
            rates_map[d_iso] = rate
            rates_batch.append((d_iso, rate))
        cur.executemany("INSERT INTO usd_rates VALUES (?, ?)", rates_batch)
    print(f"   Loaded {len(rates_batch)} USD rates.")

    print("3. Loading brokers.csv...")
    brokers_batch = []
    with open(os.path.join(DATA_DIR, "brokers.csv"), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            b_code = row['Код брокера'].strip()
            name = row['Наименование'].strip()
            clean_n = clean_text(name).lower()
            inn = row['ИНН'].strip()
            reg = row['Регион'].strip()
            brokers_batch.append((b_code, name, clean_n, inn, reg))
        cur.executemany("INSERT INTO brokers VALUES (?, ?, ?, ?, ?)", brokers_batch)
    print(f"   Loaded {len(brokers_batch)} brokers.")

    print("4. Loading participants.csv...")
    parts_batch = []
    with open(os.path.join(DATA_DIR, "participants.csv"), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            inn = row['ИНН'].strip()
            name = row['Наименование'].strip()
            clean_n = clean_text(name).lower()
            reg = row['Регион'].strip()
            act = row['Вид деятельности'].strip()
            role = row['Роль'].strip()
            vat = row['Плательщик НДС'].strip()
            parts_batch.append((inn, name, clean_n, reg, act, role, vat))
        cur.executemany("INSERT INTO participants VALUES (?, ?, ?, ?, ?, ?, ?)", parts_batch)
    print(f"   Loaded {len(parts_batch)} participants.")

    print("5. Loading contracts.csv...")
    contracts_batch = []
    contracts_currency_map = {}
    with open(os.path.join(DATA_DIR, "contracts.csv"), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            c_num = row['Номер контракта'].strip()
            p_name = row['Наименование продукта'].strip()
            brand = row['Марка товара'].strip()
            size = row['Размер товара'].strip()
            grade = row['Сорт товара'].strip()
            ptype = row['Тип товара'].strip()
            pclass = row['Класс товара'].strip()
            hscode = row['Код ТН ВЭД'].strip()
            pgroup = row['Группа товара'].strip()
            cat = row['Категория товара'].strip()
            ind = row['Отрасль промышленности'].strip()
            unit = row['Единица измерения'].strip()
            lot = parse_num(row['Лот'], 1.0)
            curr = row['Валюта'].strip()
            base_p = parse_num(row['Базисная цена'])
            dep = parse_num(row['Сумма залога'])
            del_basis = row['Базис поставки'].strip()
            reg_ru = row['Регион'].strip()
            reg_uz = RU_TO_UZ_REGION.get(reg_ru, reg_ru)
            addr = row['Адрес склада'].strip()
            ttype = row['Тип торгов'].strip()
            ctype = row['Тип контракта'].strip()
            cform = row['Форма контракта'].strip()
            pay_days = int(parse_num(row['Срок оплаты'], 0))
            del_days = int(parse_num(row['Срок поставки'], 0))
            pack = row['Упаковка'].strip()
            s_inn = row['ИНН продавца'].strip()
            rdate = parse_date(row['Дата регистрации'])
            vdate = parse_date(row['Действует до'])

            # Full product description composite
            desc_parts = [p_name]
            if brand: desc_parts.append(f"Марка: {brand}")
            if size: desc_parts.append(f"Размер: {size}")
            if grade: desc_parts.append(f"Сорт: {grade}")
            if ptype: desc_parts.append(f"Тип: {ptype}")
            if pclass: desc_parts.append(f"Класс: {pclass}")
            full_desc = " | ".join(desc_parts)

            contracts_currency_map[c_num] = curr

            contracts_batch.append((
                c_num, p_name, brand, size, grade, ptype, pclass,
                hscode, pgroup, cat, ind, unit, lot, curr,
                base_p, dep, del_basis, reg_ru, reg_uz, addr,
                ttype, ctype, cform, pay_days, del_days, pack,
                s_inn, rdate, vdate, full_desc
            ))
        cur.executemany("""
        INSERT INTO contracts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, contracts_batch)
    print(f"   Loaded {len(contracts_batch)} contracts.")

    print("6. Loading deals (2022-2026, 500 000 records)...")
    total_deals = 0
    deal_insert_sql = """
    INSERT INTO deals VALUES (
        ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
    )
    """

    for year in range(2022, 2027):
        y_start = time.time()
        fpath = os.path.join(DATA_DIR, f"deals_{year}.csv")
        deals_batch = []
        with open(fpath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                d_num = int(row['Номер сделки'])
                d_date = parse_date(row['Дата сделки'])
                d_time = row['Время сделки'].strip()
                ttype = row['Тип торгов'].strip()
                qty = parse_num(row['Количество'])
                amt = parse_num(row['Сумма сделки'])
                start_p = parse_num(row['Стартовая цена'])
                c_num = row['Номер контракта'].strip()
                p_name = row['Наименование товара'].strip()
                lot = parse_num(row['Лот'], 1.0)
                unit = row['Единица измерения'].strip()
                reg = row['Регион'].strip()
                ctype = row['Тип контракта'].strip()
                cform = row['Форма контракта'].strip()
                status = row['Состояние сделки'].strip()
                s_inn = row['ИНН продавца'].strip()
                b_inn = row['ИНН покупателя'].strip()
                s_brk = row['Брокер продавца'].strip()
                b_brk = row['Брокер покупателя'].strip()
                pay_d = parse_date(row['Дата оплаты'])
                del_d = parse_date(row['Дата поставки'])
                del_qty = parse_num(row['Поставлено'], 0.0)

                curr = contracts_currency_map.get(c_num, 'Узбекский сум')
                rate = rates_map.get(d_date, 1.0)

                vol_units = qty * lot
                unit_p = amt / vol_units if vol_units > 0 else 0.0

                if curr == 'Доллар США':
                    amt_usd = amt
                    amt_uzs = amt * rate
                else:
                    amt_uzs = amt
                    amt_usd = amt / rate if rate > 0 else 0.0

                deals_batch.append((
                    d_num, d_date, d_time, ttype, qty, amt, start_p,
                    c_num, p_name, lot, unit, reg, ctype, cform,
                    status, s_inn, b_inn, s_brk, b_brk, pay_d, del_d, del_qty,
                    curr, rate, vol_units, unit_p, amt_uzs, amt_usd
                ))

        cur.executemany(deal_insert_sql, deals_batch)
        total_deals += len(deals_batch)
        print(f"   Deals {year}: {len(deals_batch)} rows loaded in {time.time() - y_start:.2f}s")

    print(f"   Total deals loaded: {total_deals}")

    print("7. Building FTS5 full-text search indexes...")
    cur.execute("""
    CREATE VIRTUAL TABLE participants_fts USING fts5(
        inn,
        name,
        clean_name,
        region,
        activity,
        content='participants',
        content_rowid='rowid'
    );
    """)
    cur.execute("INSERT INTO participants_fts(participants_fts) VALUES('rebuild');")

    cur.execute("""
    CREATE VIRTUAL TABLE contracts_fts USING fts5(
        contract_num,
        product_name,
        full_product_desc,
        category,
        industry,
        hs_code,
        content='contracts',
        content_rowid='rowid'
    );
    """)
    cur.execute("INSERT INTO contracts_fts(contracts_fts) VALUES('rebuild');")

    cur.execute("""
    CREATE VIRTUAL TABLE brokers_fts USING fts5(
        broker_code,
        name,
        clean_name,
        region,
        content='brokers',
        content_rowid='rowid'
    );
    """)
    cur.execute("INSERT INTO brokers_fts(brokers_fts) VALUES('rebuild');")

    print("8. Creating high-speed B-Tree indexes for fast analytical queries...")
    cur.execute("CREATE INDEX idx_deals_date ON deals(deal_date);")
    cur.execute("CREATE INDEX idx_deals_contract ON deals(contract_num);")
    cur.execute("CREATE INDEX idx_deals_seller ON deals(seller_inn);")
    cur.execute("CREATE INDEX idx_deals_buyer ON deals(buyer_inn);")
    cur.execute("CREATE INDEX idx_deals_status ON deals(status);")
    cur.execute("CREATE INDEX idx_deals_contract_type ON deals(contract_type);")
    cur.execute("CREATE INDEX idx_deals_seller_broker ON deals(seller_broker);")
    cur.execute("CREATE INDEX idx_deals_buyer_broker ON deals(buyer_broker);")
    cur.execute("CREATE INDEX idx_deals_amount_uzs ON deals(deal_amount_uzs);")
    cur.execute("CREATE INDEX idx_deals_product ON deals(product_name);")
    cur.execute("CREATE INDEX idx_contracts_cat ON contracts(category);")
    cur.execute("CREATE INDEX idx_contracts_seller ON contracts(seller_inn);")

    conn.commit()
    conn.close()
    print(f"\nDone! Database successfully built at {DB_PATH} in {time.time() - start_time:.2f} seconds.")

if __name__ == "__main__":
    main()
