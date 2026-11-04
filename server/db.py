from contextlib import contextmanager
from datetime import date, datetime, time
from decimal import Decimal
import os
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def connection():
    path = Path(os.environ.get('UZEX_DB_PATH', ROOT / 'data/uzex.duckdb'))
    con = duckdb.connect(str(path), read_only=True, config={'enable_external_access': False, 'threads': 2})
    try:
        yield con
    finally:
        con.close()


def serial(value):
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: serial(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    return value


def query(sql: str, parameters=None):
    with connection() as con:
        cursor = con.execute(sql, parameters or [])
        fields = [x[0] for x in cursor.description]
        return serial([dict(zip(fields, row)) for row in cursor.fetchall()])
