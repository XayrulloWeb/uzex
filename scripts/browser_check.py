"""Real Chromium interaction checks against the running production application."""
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results'
OUT.mkdir(exist_ok=True)
BASE=os.environ.get('UZEX_TEST_URL','http://127.0.0.1:8000')
CHECKS=[]


def record(name):
    CHECKS.append(name)
    print('PASS',name,flush=True)


def digits(locator):
    return re.sub(r'\D','',locator.inner_text())


with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('UZEX_CHROMIUM_PATH') or shutil.which('chromium'), headless=True,
        args=['--no-sandbox','--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader'])
    context=browser.new_context(viewport={'width':1440,'height':1080},device_scale_factor=1,accept_downloads=True,reduced_motion='reduce')
    page=context.new_page()
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(BASE,wait_until='networkidle')
    expect(page.locator('.metric-value').nth(1)).to_contain_text('99')
    assert digits(page.locator('.metric-value').nth(1))=='99306'
    expect(page.locator('canvas')).to_have_count(1)
    assert page.evaluate('document.body.scrollWidth===window.innerWidth')
    page.screenshot(path=str(OUT/'desktop.png'),full_page=True)
    record('Desktop initial data, 3D scene and layout')

    page.get_by_role('button',name='Всё время',exact=True).click()
    expect(page.locator('.metric-value').nth(1)).to_contain_text('500')
    assert digits(page.locator('.metric-value').nth(1))=='500000'
    record('All five years: 500,000 deals rendered')

    page.get_by_role('button',name='2025',exact=True).click()
    expect(page.locator('.metric-value').nth(1)).to_contain_text('115')
    page.get_by_role('combobox',name='Товар',exact=True).select_option('diesel')
    page.get_by_role('combobox',name='Регион склада',exact=True).select_option('tashkent_city')
    expected=page.request.get(BASE+'/api/overview?year=2025&commodity=diesel&region=tashkent_city').json()['metrics']['deals']
    expect(page.locator('.metrics-grid')).to_have_attribute('aria-busy','false')
    assert digits(page.locator('.metric-value').nth(1))==str(expected)
    record('Combined year, commodity and region filters')

    page.get_by_role('button',name='2D',exact=True).click()
    expect(page.locator('.flat-map')).to_be_visible()
    page.get_by_role('button',name='Наманганская область',exact=True).click()
    expect(page.get_by_role('combobox',name='Регион склада',exact=True)).to_have_value('namangan')
    page.get_by_role('button',name='Сбросить фильтры',exact=True).click()
    expect(page.locator('.metric-value').nth(1)).to_contain_text('99')
    record('2D map selection and filter reset')

    page.get_by_role('button',name='Экспорт',exact=True).click()
    expect(page.get_by_role('dialog')).to_be_visible()
    expect(page.get_by_role('heading',name='Экспортные сделки',exact=True)).to_be_visible()
    page.get_by_role('button',name='Проверить основание расчёта').click()
    expect(page.locator('.sources-panel pre')).to_contain_text('SELECT')
    with page.expect_download() as download:
        page.get_by_role('dialog').get_by_role('button',name='CSV',exact=True).click()
    download.value.save_as(str(OUT/'report.csv'))
    assert 'amount_uzs' in (OUT/'report.csv').read_text(encoding='utf-8-sig')
    page.screenshot(path=str(OUT/'report.png'),full_page=False)
    page.keyboard.press('Escape')
    expect(page.get_by_role('dialog')).to_have_count(0)
    record('Report, provenance, CSV export and Escape dismissal')

    field=page.get_by_role('textbox',name='Поиск сделки, ИНН или товара',exact=True)
    field.fill('100007');field.press('Enter')
    expect(page.get_by_role('heading',name='Сделка №100007',exact=True)).to_be_visible()
    assert '48000' in digits(page.locator('.volume-proof'))
    expect(page.locator('.deal-facts')).to_contain_text('Цена за единицу')
    page.screenshot(path=str(OUT/'deal.png'),full_page=False)
    page.keyboard.press('Escape')
    record('Direct deal lookup, lot arithmetic and detail card')

    field.fill('Karbamid');field.press('Enter')
    expect(page.locator('.registry-search')).to_be_visible()
    expect(page.locator('.deals-table tbody tr')).not_to_have_count(0)
    expect(page.locator('.product-name').first).to_contain_text(re.compile('карбамид|мочевина',re.I))
    first=page.locator('.deal-link').first.inner_text()
    page.get_by_role('button',name='Следующая страница',exact=True).click()
    expect(page.locator('.deal-link').first).not_to_have_text(first)
    with page.expect_download() as download:
        page.get_by_role('button',name='CSV страницы',exact=True).click()
    download.value.save_as(str(OUT/'deals.csv'))
    assert len((OUT/'deals.csv').read_text(encoding='utf-8-sig').splitlines())==9
    record('Uzbek commodity search, registry pagination and page CSV')

    page.get_by_role('button',name='UZ',exact=True).click()
    expect(page.locator('html')).to_have_attribute('lang','uz')
    expect(page.locator('h1')).to_contain_text('Tafsilotlarda.')
    page.reload(wait_until='networkidle')
    expect(page.locator('html')).to_have_attribute('lang','uz')
    record('Uzbek interface and language persistence')

    # Deliberately fail one overview request. Old metrics must not be presented as new data.
    page.get_by_role('button',name='RU',exact=True).click()
    page.route('**/api/overview?**',lambda route:route.fulfill(status=503,body='{}',content_type='application/json'))
    page.get_by_role('button',name='2023',exact=True).click()
    expect(page.locator('.error-banner')).to_be_visible()
    expect(page.locator('.metric-value').nth(1)).to_contain_text('—')
    page.unroute('**/api/overview?**')
    page.get_by_role('button',name='Повторить',exact=True).click()
    expect(page.locator('.metric-value').nth(1)).to_contain_text('93')
    record('Data error hides stale metrics; retry recovers')

    for width in [390,320]:
        mobile_context=browser.new_context(viewport={'width':width,'height':844},device_scale_factor=1,is_mobile=True,has_touch=True,reduced_motion='reduce')
        mobile=mobile_context.new_page()
        mobile.on('pageerror',lambda e:errors.append(str(e)))
        mobile.goto(BASE,wait_until='networkidle')
        expect(mobile.locator('.metric-value').nth(1)).to_contain_text('99')
        assert mobile.evaluate('document.body.scrollWidth===window.innerWidth')
        if width==390: mobile.screenshot(path=str(OUT/'mobile.png'),full_page=True)
        mobile.get_by_role('button',name='UZ',exact=True).click()
        expect(mobile.locator('h1')).to_contain_text('Tafsilotlarda.')
        assert mobile.evaluate('document.body.scrollWidth===window.innerWidth')
        if width==390: mobile.screenshot(path=str(OUT/'mobile-uz.png'),full_page=True)
        mobile.get_by_role('button',name='Metodologiya',exact=True).click()
        expect(mobile.get_by_role('dialog')).to_be_visible()
        mobile.get_by_role('button',name='Close / Закрыть / Yopish',exact=True).click()
        expect(mobile.get_by_role('dialog')).to_have_count(0)
        record(f'Mobile {width}px RU/UZ, modal and no horizontal overflow')
        mobile_context.close()

    # A browser without WebGL must retain the regional map and filters.
    fallback_context=browser.new_context(viewport={'width':1200,'height':900},reduced_motion='reduce')
    fallback_context.add_init_script("""
      const original = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function(type, ...args) {
        if (type === 'webgl' || type === 'webgl2' || type === 'experimental-webgl') return null;
        return original.call(this, type, ...args);
      };
    """)
    fallback=fallback_context.new_page()
    fallback.goto(BASE,wait_until='networkidle')
    expect(fallback.locator('.flat-map')).to_be_visible()
    fallback.get_by_role('button',name='Хорезмская область',exact=True).click()
    expect(fallback.get_by_role('combobox',name='Регион склада',exact=True)).to_have_value('khorezm')
    record('No-WebGL browser retains interactive SVG map')
    fallback_context.close()

    assert not errors, errors
    record('No uncaught browser JavaScript errors')
    browser.close()

(OUT/'browser-results.json').write_text(json.dumps({'run_at':datetime.now(timezone.utc).isoformat(),'target':BASE,'passed':len(CHECKS),'checks':CHECKS},ensure_ascii=False,indent=2)+'\n')
print(f'{len(CHECKS)} browser scenarios passed.',flush=True)
