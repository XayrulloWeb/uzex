import os
from pathlib import Path

env_file = Path(__file__).resolve().parents[1] / '.env'
if env_file.exists():
    for line in env_file.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.strip().startswith('#'):
            k, v = line.strip().split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.analytics import Scope, catalog, deal, registry, report, summary
from server.db import ROOT, query
from server.ai import router as ai_router


@asynccontextmanager
async def lifespan(app):
    query('SELECT count(*) FROM trades')
    yield


app = FastAPI(title='UZEX Observatory', version='0.1.0', lifespan=lifespan)
app.include_router(ai_router)


@app.get('/api/health')
def health():
    from server.gemini import get_pool
    return {'status': 'ok', 'deals': query('SELECT count(*) count FROM trades')[0]['count'], 'ai_enabled': get_pool().configured}


@app.get('/api/catalog')
def get_catalog():
    return catalog()


def get_scope(year: int | None, region: str | None, commodity: str | None, status: str):
    try:
        scope = Scope(year=year or None, region=region or None, commodity=commodity or None, status=status)
        from server.analytics import where
        where(scope)
        return scope
    except ValueError:
        raise HTTPException(422, 'Invalid filter')


@app.get('/api/overview')
def overview(year: int = Query(2026, ge=0, le=2026), region: str | None = None, commodity: str | None = None, status: Literal['all','active','fulfilled']='all'):
    return summary(get_scope(year,region,commodity,status))


@app.get('/api/deals')
def get_deals(year: int = Query(2026,ge=0,le=2026), region: str | None=None, commodity: str | None=None,
              status: Literal['all','active','fulfilled']='all', search: str=Query('',max_length=160), offset: int=Query(0,ge=0,le=500000), limit: int=Query(15,ge=1,le=100)):
    return registry(get_scope(year,region,commodity,status), search, offset, limit)


@app.get('/api/deals/{identity}')
def get_deal(identity: int):
    result = deal(identity)
    if not result:
        raise HTTPException(404, 'Deal not found in dataset')
    return result


@app.get('/api/reports/{kind}')
def get_report(kind: str, year: int=Query(2026,ge=0,le=2026), region: str | None=None, commodity: str | None=None,
               status: Literal['all','active','fulfilled']='all', lang: Literal['ru','uz']='ru'):
    try:
        return report(kind, get_scope(year,region,commodity,status),lang)
    except ValueError:
        raise HTTPException(404, 'Unknown report')


dist = ROOT / 'dist'
if dist.exists():
    app.mount('/assets', StaticFiles(directory=dist/'assets'), name='assets')


@app.get('/{path:path}', include_in_schema=False)
def frontend(path: str):
    if path.startswith('api/'):
        raise HTTPException(404, 'Unknown API route')
    if dist.exists():
        target = (dist / path).resolve()
        if target.is_relative_to(dist.resolve()) and target.is_file():
            return FileResponse(target)
        return FileResponse(dist/'index.html')
    raise HTTPException(503, 'Build the frontend with npm run build, or use the Vite dev server.')
