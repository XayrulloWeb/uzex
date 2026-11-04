import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react';
import { AnimatePresence, motion, MotionConfig, useReducedMotion } from 'framer-motion';
import {
  ArrowUpRight,
  ArrowRight,
  ArrowDown,
  Search,
  SlidersHorizontal,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  X,
  Download,
  Check,
  Layers3,
  MoveUpRight,
  RotateCcw,
  ShieldCheck,
  Info,
  ScanLine,
  Database,
  Loader2,
  ChartNoAxesCombined,
  Boxes,
  Building2,
  MapPin,
  CircleHelp,
} from 'lucide-react';
import type { Catalog, DealDetail, Lang, Overview, Registry, Report, Scope } from './types';
import { api, compact, csvDownload, dateLabel, exact, integer, params, STATUS_UZ } from './lib';
import Chart from './Chart';
import AITerminal from './AITerminal';

const MapScene = lazy(() => import('./MapScene'));
const initialScope: Scope = { year: 2026, region: '', commodity: '', status: 'all' };
const reportOptions = [
  { id: 'buyers', ru: 'Топ покупателей', uz: 'Yirik xaridorlar', icon: Building2 },
  { id: 'sellers', ru: 'Топ продавцов', uz: 'Yirik sotuvchilar', icon: Boxes },
  { id: 'exports', ru: 'Экспорт', uz: 'Eksport', icon: ArrowUpRight },
  { id: 'regions', ru: 'По регионам', uz: 'Hududlar', icon: MapPin },
  { id: 'statuses', ru: 'Состояния сделок', uz: 'Bitim holatlari', icon: Layers3 },
  { id: 'late', ru: 'Поставки с опозданием', uz: 'Kech yetkazib berish', icon: ScanLine },
];

function Brand({ small = false }: { small?: boolean }) {
  return (
    <span className={`brand ${small ? 'brand-small' : ''}`}>
      <svg viewBox="0 0 40 40" fill="none" aria-hidden="true">
        <path d="m20 2 7 11 11 7-11 7-7 11-7-11L2 20l11-7z" fill="currentColor" />
        <circle cx="20" cy="20" r="5" fill="#121810" />
      </svg>
      <span>
        uzex
        <span className="brand-divider" />
        <span className="brand-caption">OBSERVATORY</span>
      </span>
    </span>
  );
}

function Modal({
  children,
  title,
  kicker,
  onClose,
  wide = false,
}: {
  children: ReactNode;
  title: string;
  kicker: string;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    (ref.current?.querySelector('button') as HTMLElement | null)?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeRef.current();
      if (e.key === 'Tab' && ref.current) {
        const nodes = ref.current.querySelectorAll<HTMLElement>(
          'button:not(:disabled),a[href],input,select,textarea,[tabindex="0"]',
        );
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener('keydown', key);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener('keydown', key);
      before?.focus();
    };
  }, []);
  return (
    <motion.div
      className="modal-backdrop"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={onClose}
    >
      <motion.div
        className={`modal ${wide ? 'modal-wide' : ''}`}
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        initial={{ opacity: 0, y: 20, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 12 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-heading">
          <div>
            <div className="eyebrow">{kicker}</div>
            <h2 id="modal-title">{title}</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close / Закрыть / Yopish">
            <X size={22} />
          </button>
        </div>
        {children}
      </motion.div>
    </motion.div>
  );
}

function Metric({
  label,
  value,
  unit,
  note,
  index,
  loading,
}: {
  label: string;
  value: string;
  unit?: string;
  note: string;
  index: number;
  loading: boolean;
}) {
  return (
    <motion.div
      className="metric"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.07 }}
    >
      <div className="metric-label">
        <span>{label}</span>
        <span className="metric-index">0{index + 1}</span>
      </div>
      <div className={`metric-value ${loading ? 'is-updating' : ''}`}>
        {value}
        <span>{unit}</span>
      </div>
      <div className="metric-note">{note}</div>
    </motion.div>
  );
}

export default function App() {
  const [lang, setLang] = useState<Lang>(() =>
    localStorage.getItem('uzex-lang') === 'uz' ? 'uz' : 'ru',
  );
  const [scope, setScope] = useState<Scope>(initialScope);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [view, setView] = useState<'overview' | 'registry'>('overview');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [flat, setFlat] = useState(false);
  const [chartMode, setChartMode] = useState<'amount' | 'deals'>('amount');
  const [method, setMethod] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [reportLoading, setReportLoading] = useState('');
  const [reportError, setReportError] = useState('');
  const [detail, setDetail] = useState<DealDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [registryLoading, setRegistryLoading] = useState(false);
  const [registryError, setRegistryError] = useState(false);
  const [toast, setToast] = useState('');
  const [sourceOpen, setSourceOpen] = useState(false);
  const reportRequest = useRef<AbortController | null>(null);
  const reduced = !!useReducedMotion();
  const t = (ru: string, uz: string) => (lang === 'ru' ? ru : uz);

  useEffect(() => {
    document.documentElement.lang = lang;
    localStorage.setItem('uzex-lang', lang);
    document.title = t(
      'UZEX Observatory — рынок в деталях',
      'UZEX Observatory — bozor tafsilotlari',
    );
  }, [lang]);
  useEffect(() => {
    const c = new AbortController();
    api<Catalog>('/api/catalog', c.signal)
      .then(setCatalog)
      .catch((e) => {
        if (e.name !== 'AbortError') setError('catalog');
      });
    return () => c.abort();
  }, [retry]);
  useEffect(() => {
    const c = new AbortController();
    setLoading(true);
    setError('');
    api<Overview>('/api/overview?' + params(scope), c.signal)
      .then((d) => {
        setOverview(d);
        setLoading(false);
      })
      .catch((e) => {
        if (e.name !== 'AbortError') {
          setError('overview');
          setOverview(null);
          setLoading(false);
        }
      });
    return () => c.abort();
  }, [scope, retry]);
  useEffect(() => {
    setOffset(0);
  }, [scope, search]);
  useEffect(() => {
    const c = new AbortController();
    setRegistryLoading(true);
    setRegistryError(false);
    api<Registry>('/api/deals?' + params(scope, { offset, limit: 8, search }), c.signal)
      .then((d) => {
        setRegistry(d);
        setRegistryLoading(false);
      })
      .catch((e) => {
        if (e.name !== 'AbortError') {
          setRegistryError(true);
          setRegistryLoading(false);
        }
      });
    return () => c.abort();
  }, [scope, search, offset, retry]);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(''), 3000);
    return () => clearTimeout(id);
  }, [toast]);

  const update = (part: Partial<Scope>) => {
    reportRequest.current?.abort();
    setReportLoading('');
    setReportError('');
    setScope((s) => ({ ...s, ...part }));
    setReport(null);
  };
  const region = catalog?.regions.find((r) => r.id === scope.region);
  const commodity = catalog?.commodities.find((c) => c.id === scope.commodity);
  const period = scope.year === 0 ? t('2022 — 2026', '2022 — 2026') : String(scope.year);
  const money = compact(overview?.metrics.amount_uzs || '0', lang);
  const expo = compact(overview?.metrics.export_amount_uzs || '0', lang);
  const goRegistry = () => {
    setView('registry');
    document
      .getElementById('analysis')
      ?.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth' });
  };
  const scopeLabel = [
    period,
    region?.[lang],
    commodity?.[lang],
    scope.status === 'all'
      ? t('все состояния', 'barcha holatlar')
      : scope.status === 'active'
        ? t('без аннулированных', 'bekor qilinganlarsiz')
        : t('исполненные', 'bajarilgan'),
  ]
    .filter(Boolean)
    .join(' · ');

  async function openReport(kind: string) {
    reportRequest.current?.abort();
    const controller = new AbortController();
    reportRequest.current = controller;
    setReportLoading(kind);
    setReportError('');
    setSourceOpen(false);
    try {
      const result = await api<Report>(
        `/api/reports/${kind}?` + params(scope, { lang }),
        controller.signal,
      );
      if (!controller.signal.aborted) setReport(result);
    } catch {
      if (controller.signal.aborted) return;
      setReportError(
        t(
          'Не удалось получить отчёт. Попробуйте ещё раз.',
          'Hisobotni yuklab bo‘lmadi. Qayta urinib ko‘ring.',
        ),
      );
    } finally {
      if (!controller.signal.aborted) setReportLoading('');
    }
  }
  async function openDeal(id: number) {
    setDetailLoading(true);
    try {
      setDetail(await api<DealDetail>(`/api/deals/${id}`));
    } catch {
      setToast(t('Сделка не найдена или недоступна.', 'Bitim topilmadi yoki mavjud emas.'));
    } finally {
      setDetailLoading(false);
    }
  }
  function submitSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    if (/^\s*[№#]?\s*\d{6}\s*$/.test(q)) {
      void openDeal(Number(q.replace(/\D/g, '')));
      return;
    }
    setSearch(q);
    setOffset(0);
    goRegistry();
  }
  const exportPage = () => {
    if (!registry) return;
    csvDownload(
      'uzex-deals-page.csv',
      [
        'deal_id',
        'date',
        'product',
        'quantity',
        'unit',
        'amount',
        'currency',
        'amount_uzs',
        'status',
        'seller_inn',
        'buyer_inn',
      ],
      registry.rows.map((r) => [
        r.deal_id,
        r.deal_date,
        r.product_label,
        r.quantity,
        r.unit,
        r.amount_native,
        r.currency,
        r.amount_uzs,
        r.status,
        r.seller_inn,
        r.buyer_inn,
      ]),
    );
    setToast(t('Текущая страница выгружена в CSV', 'Joriy sahifa CSV formatida yuklandi'));
  };

  const renderRegistry = (preview = false) => (
    <section className={`registry-section ${preview ? 'registry-preview' : ''}`} id="registry">
      <div className="section-heading">
        <div>
          <div className="eyebrow dark">
            <span className="tiny-line" />
            {t('ПРОЗРАЧНОСТЬ В КАЖДОЙ СДЕЛКЕ', 'HAR BIR BITIMDA SHAFFOFLIK')}
          </div>
          <h2>
            {preview
              ? t('За цифрами — сделки.', 'Raqamlar ortida — bitimlar.')
              : t('Реестр сделок.', 'Bitimlar reyestri.')}
          </h2>
        </div>
        {preview ? (
          <button className="text-button" onClick={goRegistry}>
            {t('Открыть реестр', 'Reyestrni ochish')}
            <ArrowUpRight size={17} />
          </button>
        ) : (
          <button className="outline-button" onClick={exportPage} disabled={!registry?.rows.length}>
            <Download size={15} />
            {t('CSV страницы', 'Sahifa CSV')}
          </button>
        )}
      </div>
      {!preview && (
        <form
          className="registry-search"
          onSubmit={(e) => {
            e.preventDefault();
            setSearch(query.trim());
            setOffset(0);
          }}
        >
          <Search size={18} />
          <input
            aria-label={t('Поиск по реестру', 'Reyestrdan qidirish')}
            placeholder={t(
              'Товар, компания, ИНН, номер сделки или контракта',
              'Tovar, kompaniya, STIR, bitim yoki shartnoma raqami',
            )}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit">
            {t('Найти', 'Qidirish')}
            <ArrowRight size={16} />
          </button>
        </form>
      )}
      <div className="registry-meta">
        <span>
          <i className="status-dot dark-dot" />
          {registryLoading
            ? t('Обновляем выборку…', 'Tanlanma yangilanmoqda…')
            : `${integer(registry?.total || 0)} ${t('сделок в выборке', 'ta bitim tanlandi')}`}
        </span>
        {search && (
          <button
            onClick={() => {
              setSearch('');
              setQuery('');
            }}
          >
            {t('Поиск', 'Qidirish')}: {search}
            <X size={12} />
          </button>
        )}
        <span className="mono">{scopeLabel}</span>
      </div>
      {registryError ? (
        <div className="empty-state">
          <CircleHelp size={24} />
          <p>{t('Не удалось загрузить реестр.', 'Reyestrni yuklab bo‘lmadi.')}</p>
          <button className="text-button" onClick={() => setRetry((x) => x + 1)}>
            {t('Повторить', 'Qayta urinish')}
            <RotateCcw size={14} />
          </button>
        </div>
      ) : (
        <div className={`table-scroll ${registryLoading ? 'is-updating' : ''}`}>
          <table className="deals-table">
            <thead>
              <tr>
                <th>{t('Сделка / дата', 'Bitim / sana')}</th>
                <th>{t('Товар', 'Tovar')}</th>
                <th>{t('Объём', 'Hajm')}</th>
                <th>{t('Сумма сделки', 'Bitim summasi')}</th>
                <th>{t('Состояние', 'Holat')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(preview ? registry?.rows.slice(0, 5) : registry?.rows)?.map((row) => (
                <tr key={row.deal_id}>
                  <td>
                    <button className="deal-link" onClick={() => void openDeal(row.deal_id)}>
                      #{row.deal_id}
                    </button>
                    <span className="table-sub">{dateLabel(row.deal_date, lang)}</span>
                  </td>
                  <td>
                    <span className="product-name">{row.product_label}</span>
                    <span className="table-sub">
                      {catalog?.regions.find((r) => r.id === row.region)?.[lang]}
                      <span className="table-dot">·</span>
                      {row.contract_id}
                    </span>
                  </td>
                  <td>
                    <span className="number">{exact(row.quantity, 0)}</span>
                    <span className="table-sub">{row.unit}</span>
                  </td>
                  <td>
                    <span className="number">{exact(row.amount_native)}</span>
                    <span className="table-sub">{row.currency}</span>
                  </td>
                  <td>
                    <span
                      className={`deal-status ${row.status.includes('Аннулирован') ? 'cancelled' : row.status === 'Исполнен' ? 'fulfilled' : ''}`}
                    >
                      <i />
                      {lang === 'uz' ? STATUS_UZ[row.status] || row.status : row.status}
                    </span>
                  </td>
                  <td>
                    <button
                      className="row-open"
                      onClick={() => void openDeal(row.deal_id)}
                      aria-label={t(
                        `Открыть сделку ${row.deal_id}`,
                        `${row.deal_id} bitimni ochish`,
                      )}
                    >
                      <ArrowUpRight size={18} />
                    </button>
                  </td>
                </tr>
              ))}
              {!registry?.rows.length && !registryLoading && (
                <tr>
                  <td colSpan={6}>
                    <div className="empty-state">
                      <Search size={26} />
                      <p>
                        {t(
                          'В этой выборке сделки не найдены.',
                          'Bu tanlanmada bitimlar topilmadi.',
                        )}
                      </p>
                      <span>
                        {t(
                          'Попробуйте другой период, название или ИНН.',
                          'Boshqa davr, nom yoki STIR bilan urinib ko‘ring.',
                        )}
                      </span>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {!preview && (
        <div className="pagination">
          <span>
            {registry?.total
              ? `${offset + 1}–${Math.min(offset + 8, registry.total)} ${t('из', '/')} ${integer(registry.total)}`
              : '0'}
          </span>
          <div>
            <button
              className="icon-button"
              disabled={offset === 0 || registryLoading}
              onClick={() => setOffset((n) => Math.max(0, n - 8))}
              aria-label={t('Предыдущая страница', 'Oldingi sahifa')}
            >
              <ChevronLeft size={18} />
            </button>
            <button
              className="icon-button"
              disabled={!registry || offset + 8 >= registry.total || registryLoading}
              onClick={() => setOffset((n) => n + 8)}
              aria-label={t('Следующая страница', 'Keyingi sahifa')}
            >
              <ChevronRight size={18} />
            </button>
          </div>
        </div>
      )}
    </section>
  );

  return (
    <MotionConfig reducedMotion="user">
      <div className="app">
        <a className="skip-link" href="#main">
          {t('К содержимому', 'Asosiy qismga o‘tish')}
        </a>
        <header className="site-header">
          <button
            className="brand-button"
            onClick={() => {
              setView('overview');
              window.scrollTo({ top: 0, behavior: reduced ? 'instant' : 'smooth' });
            }}
            aria-label="UZEX Observatory"
          >
            <Brand />
          </button>
          <nav aria-label={t('Главная навигация', 'Asosiy navigatsiya')}>
            <button
              className={view === 'overview' ? 'active' : ''}
              onClick={() => setView('overview')}
            >
              {t('Обсерватория', 'Observatoriya')}
            </button>
            <button className={view === 'registry' ? 'active' : ''} onClick={goRegistry}>
              {t('Реестр сделок', 'Bitimlar reyestri')}
            </button>
            <button onClick={() => setMethod(true)}>{t('О данных', 'Ma’lumotlar')}</button>
          </nav>
          <div className="header-right">
            <span className="dataset-status">
              <i className="status-dot" />
              {t('500 000 СДЕЛОК', '500 000 BITIM')}
            </span>
            <div className="language-switch" aria-label="Language">
              <button
                className={lang === 'ru' ? 'selected' : ''}
                onClick={() => setLang('ru')}
                aria-pressed={lang === 'ru'}
              >
                RU
              </button>
              <span>/</span>
              <button
                className={lang === 'uz' ? 'selected' : ''}
                onClick={() => setLang('uz')}
                aria-pressed={lang === 'uz'}
              >
                UZ
              </button>
            </div>
          </div>
        </header>
        <main id="main">
          <div className="dark-world">
            <div className="world-topline">
              <span className="eyebrow">
                <span className="crosshair">+</span>
                {t('ОБЗОР ТОВАРНОГО РЫНКА', 'TOVAR BOZORI SHARHI')}
              </span>
              <span className="mono muted">UZ / 41°18′ N 69°14′ E</span>
              <button className="snapshot" onClick={() => setMethod(true)}>
                <span className="status-dot" />
                {t('СРЕЗ', 'HOLAT')} 30.10.2026 <Info size={12} />
              </button>
            </div>
            <div className="hero-layout">
              <div className="hero-copy">
                <motion.div
                  className="hero-edition"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                >
                  <span>UZEX</span>
                  <span>MARKET INTELLIGENCE</span>
                </motion.div>
                <motion.h1
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.7 }}
                >
                  {t('Рынок.', 'Bozor.')}
                  <br />
                  <span>{t('В деталях.', 'Tafsilotlarda.')}</span>
                  <span className="title-star">✳</span>
                </motion.h1>
                <motion.p
                  initial={{ opacity: 0, y: 15 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.15, duration: 0.6 }}
                >
                  {t(
                    'Каждая сделка — часть большой картины. Исследуйте связи, объёмы и движение рынка.',
                    'Har bir bitim — katta manzaraning bir qismi. Bozor aloqalari, hajmlari va dinamikasini o‘rganing.',
                  )}
                </motion.p>
                <button
                  className="explore-button"
                  onClick={() =>
                    document
                      .getElementById('analysis')
                      ?.scrollIntoView({ behavior: reduced ? 'instant' : 'smooth', block: 'start' })
                  }
                >
                  {t('Исследовать данные', 'Ma’lumotlarni o‘rganish')}
                  <span>
                    <ArrowDown size={19} />
                  </span>
                </button>
                <div className="hero-footnote">
                  <ShieldCheck size={15} />
                  <span>
                    {t(
                      'Проверяемые данные. Прозрачные расчёты.',
                      'Tekshiriladigan ma’lumotlar. Shaffof hisob-kitoblar.',
                    )}
                  </span>
                </div>
              </div>
              <div className="map-panel">
                <div className="map-label">
                  <span className="square-dot" />
                  {region?.[lang] || t('РЕСПУБЛИКА УЗБЕКИСТАН', 'O‘ZBEKISTON RESPUBLIKASI')}
                  <span className="map-label-line" />
                  <span className="map-label-code">{scope.region ? 'REGION' : '14 REGIONS'}</span>
                </div>
                <div className="map-stage">
                  {catalog && overview ? (
                    <Suspense
                      fallback={
                        <div className="map-loading">
                          {t('СОБИРАЕМ КАРТУ РЫНКА', 'BOZOR XARITASI YUKLANMOQDA')}
                          <span />
                        </div>
                      }
                    >
                      <MapScene
                        regions={catalog.regions}
                        stats={overview.regions}
                        routes={overview.routes}
                        selected={scope.region}
                        lang={lang}
                        onSelect={(id) => update({ region: scope.region === id ? '' : id })}
                        reduced={reduced || method || !!detail || !!report}
                        flat={flat}
                      />
                    </Suspense>
                  ) : (
                    <div className="map-loading">
                      {t('ПОДКЛЮЧАЕМ ДАННЫЕ', 'MA’LUMOTLAR YUKLANMOQDA')}
                      <span />
                    </div>
                  )}
                  <div className="map-compass">
                    <span>N</span>
                    <svg width="26" height="35" viewBox="0 0 26 35">
                      <path d="M13 3 21 26 13 22 5 26Z" fill="none" stroke="currentColor" />
                      <path d="M13 3v19" stroke="currentColor" />
                    </svg>
                  </div>
                  <div className="map-scale">
                    <span />
                    <div>
                      {t('СХЕМА', 'SXEMA')} <i /> UZ
                    </div>
                  </div>
                  <div className="map-view-switch">
                    <button
                      onClick={() => setFlat(false)}
                      className={!flat ? 'selected' : ''}
                      aria-pressed={!flat}
                    >
                      3D
                    </button>
                    <button
                      onClick={() => setFlat(true)}
                      className={flat ? 'selected' : ''}
                      aria-pressed={flat}
                    >
                      2D
                    </button>
                  </div>
                </div>
                <div className="map-caption">
                  <span>
                    <i className="route-key" />
                    {t(
                      'Связи: склад продавца → регион покупателя',
                      'Aloqalar: sotuvchi ombori → xaridor hududi',
                    )}
                  </span>
                  <span>
                    {t('Выберите точку на карте', 'Xaritadan nuqtani tanlang')}
                    <MoveUpRight size={13} />
                  </span>
                </div>
              </div>
            </div>
            <div className="filter-bar" aria-label={t('Фильтры данных', 'Ma’lumotlar filtrlari')}>
              <div className="filter-period">
                <span className="filter-icon">
                  <SlidersHorizontal size={15} />
                </span>
                <div className="year-switch">
                  {[2022, 2023, 2024, 2025, 2026, 0].map((y) => (
                    <button
                      key={y}
                      onClick={() => update({ year: y })}
                      className={scope.year === y ? 'active' : ''}
                      aria-pressed={scope.year === y}
                    >
                      {y || t('Всё время', 'Barcha davr')}
                    </button>
                  ))}
                </div>
              </div>
              <div className="filter-selects">
                <label className="filter-select">
                  <Layers3 size={14} />
                  <select
                    value={scope.commodity}
                    onChange={(e) => update({ commodity: e.target.value })}
                    aria-label={t('Товар', 'Tovar')}
                  >
                    <option value="">{t('Все товары', 'Barcha tovarlar')}</option>
                    {catalog?.commodities.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c[lang]}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={13} />
                </label>
                <label className="filter-select">
                  <select
                    value={scope.region}
                    onChange={(e) => update({ region: e.target.value })}
                    aria-label={t('Регион склада', 'Ombor hududi')}
                  >
                    <option value="">{t('Все регионы', 'Barcha hududlar')}</option>
                    {catalog?.regions.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r[lang]}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={13} />
                </label>
                <button
                  className="reset-filter"
                  onClick={() => update(initialScope)}
                  aria-label={t('Сбросить фильтры', 'Filtrlarni tiklash')}
                  title={t('Сбросить фильтры', 'Filtrlarni tiklash')}
                >
                  <RotateCcw size={14} />
                </button>
              </div>
            </div>
            {error && (
              <div className="error-banner" role="alert">
                {t('Не удалось загрузить данные.', 'Ma’lumotlarni yuklab bo‘lmadi.')}
                <button onClick={() => setRetry((n) => n + 1)}>
                  {t('Повторить', 'Qayta urinish')}
                  <RotateCcw size={13} />
                </button>
              </div>
            )}
            <div className="metrics-grid" aria-busy={loading}>
              <Metric
                index={0}
                loading={loading}
                label={t('СУММА СДЕЛОК', 'BITIMLAR SUMMASI')}
                value={overview ? money.value : '—'}
                unit={money.unit}
                note={t(
                  'В сумах, по курсу на дату сделки',
                  'So‘mda, bitim sanasidagi kurs bo‘yicha',
                )}
              />
              <Metric
                index={1}
                loading={loading}
                label={t('ЗАРЕГИСТРИРОВАНО', 'QAYD ETILGAN')}
                value={overview ? integer(overview.metrics.deals) : '—'}
                note={t('Сделок в выбранном периоде', 'Tanlangan davrdagi bitimlar')}
              />
              <Metric
                index={2}
                loading={loading}
                label={t('УЧАСТНИКИ', 'ISHTIROKCHILAR')}
                value={overview ? integer(overview.metrics.sellers) : '—'}
                unit={t('продавцов', 'sotuvchi')}
                note={
                  overview
                    ? `${integer(overview.metrics.buyers)} ${t('уникальных покупателей', 'noyob xaridor')}`
                    : '—'
                }
              />
              <Metric
                index={3}
                loading={loading}
                label={t('ЭКСПОРТ', 'EKSPORT')}
                value={overview ? expo.value : '—'}
                unit={expo.unit}
                note={
                  overview
                    ? `${integer(overview.metrics.export_deals)} ${t('сделок · в сумах', 'ta bitim · so‘mda')}`
                    : '—'
                }
              />
            </div>
            <div className="world-bottom">
              <span>
                <i className="status-dot" />
                {t('ПОЛНЫЙ НАБОР: 500 000 СДЕЛОК', 'TO‘LIQ TO‘PLAM: 500 000 BITIM')}
              </span>
              <label>
                {t('В расчёте', 'Hisobda')}:{' '}
                <select
                  aria-label={t('Состояния для расчёта', 'Hisoblash holatlari')}
                  value={scope.status}
                  onChange={(e) => update({ status: e.target.value as Scope['status'] })}
                >
                  <option value="all">{t('все состояния', 'barcha holatlar')}</option>
                  <option value="active">{t('без аннулированных', 'bekor qilinganlarsiz')}</option>
                  <option value="fulfilled">{t('только исполненные', 'faqat bajarilgan')}</option>
                </select>
                <ChevronDown size={11} />
              </label>
              <span>{t('2026 — ПО 30 ОКТЯБРЯ', '2026 — 30-OKTABRGACHA')}</span>
            </div>
          </div>

          <div className="light-world" id="analysis">
            <div className="workspace-tabs">
              <button
                onClick={() => setView('overview')}
                className={view === 'overview' ? 'active' : ''}
              >
                <ChartNoAxesCombined size={17} />
                {t('Аналитика', 'Tahlil')}
              </button>
              <button
                onClick={() => setView('registry')}
                className={view === 'registry' ? 'active' : ''}
              >
                <Database size={16} />
                {t('Реестр сделок', 'Bitimlar reyestri')}
              </button>
              <span className="workspace-context">
                <span className="status-dot dark-dot" />
                {scopeLabel}
              </span>
            </div>
            <AnimatePresence mode="wait">
              <motion.div
                key={view}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.2 }}
              >
                {view === 'overview' ? (
                  <>
                    <section className="analytics-top">
                      <div className="trend-panel">
                        <div className="panel-topline">
                          <span className="eyebrow dark">
                            01 / {t('ДИНАМИКА РЫНКА', 'BOZOR DINAMIKASI')}
                          </span>
                          <ArrowUpRight size={18} />
                        </div>
                        <div className="chart-heading">
                          <h2>{t('Большая картина.', 'Katta manzara.')}</h2>
                          <div className="segment-control">
                            <button
                              className={chartMode === 'amount' ? 'active' : ''}
                              onClick={() => setChartMode('amount')}
                            >
                              {t('Сумма', 'Summa')}
                            </button>
                            <button
                              className={chartMode === 'deals' ? 'active' : ''}
                              onClick={() => setChartMode('deals')}
                            >
                              {t('Сделки', 'Bitimlar')}
                            </button>
                          </div>
                        </div>
                        <p className="panel-description">
                          {chartMode === 'amount'
                            ? t(
                                'Сумма зарегистрированных сделок по месяцам, UZS',
                                'Oylar bo‘yicha qayd etilgan bitimlar summasi, UZS',
                              )
                            : t(
                                'Количество зарегистрированных сделок по месяцам',
                                'Oylar bo‘yicha qayd etilgan bitimlar soni',
                              )}
                        </p>
                        <div className={loading ? 'is-updating' : ''}>
                          <Chart data={overview?.monthly || []} lang={lang} mode={chartMode} />
                        </div>
                        <div className="chart-footer">
                          <span>
                            <i />
                            {t('Текущая выборка', 'Joriy tanlanma')}
                          </span>
                          <button onClick={() => void openReport('months')}>
                            {t('Открыть расчёт', 'Hisob-kitobni ochish')}
                            <ArrowUpRight size={13} />
                          </button>
                        </div>
                      </div>
                      <div className="structure-panel">
                        <div className="panel-topline">
                          <span className="eyebrow dark">
                            02 / {t('СТРУКТУРА РЫНКА', 'BOZOR TARKIBI')}
                          </span>
                          <Boxes size={17} />
                        </div>
                        <h2>{t('Что движет рынком.', 'Bozorni nima boshqaradi.')}</h2>
                        <div className="structure-main">
                          <Donut
                            rows={overview?.commodities || []}
                            total={overview?.metrics.amount_uzs || '0'}
                          />
                          <div className="donut-summary">
                            <span>{t('ТОВАРНЫХ ГРУПП', 'TOVAR GURUHI')}</span>
                            <strong>{overview?.commodities.length || '—'}</strong>
                            <span>{t('в выбранном периоде', 'tanlangan davrda')}</span>
                          </div>
                        </div>
                        <div className="commodity-ranking">
                          {overview?.commodities.slice(0, 4).map((r, i) => {
                            const c = catalog?.commodities.find((c) => c.id === r.id);
                            const f = compact(r.amount_uzs, lang);
                            return (
                              <button
                                key={r.id}
                                onClick={() =>
                                  update({ commodity: scope.commodity === r.id ? '' : r.id })
                                }
                              >
                                <span className={`rank-color rank-${i}`} />
                                <span>{c?.[lang] || r.id}</span>
                                <strong>
                                  {f.value} <small>{f.unit}</small>
                                </strong>
                                <ArrowUpRight size={12} />
                              </button>
                            );
                          })}
                        </div>
                        <button
                          className="all-commodities"
                          onClick={() => void openReport('commodities')}
                        >
                          {t('Все товарные группы', 'Barcha tovar guruhlari')}
                          <ArrowRight size={15} />
                        </button>
                      </div>
                    </section>
                    <AITerminal
                      lang={lang}
                      scope={scope}
                      contextLabel={scopeLabel}
                      onDeal={(id) => void openDeal(id)}
                    />
                    <section className="explorer-section">
                      <div className="explorer-copy">
                        <span className="eyebrow dark">
                          03 / {t('ОТ ДАННЫХ К ОТВЕТУ', 'MA’LUMOTDAN JAVOBGA')}
                        </span>
                        <h2>
                          {t('Найдите то,', 'Kerakli ma’lumotni')}
                          <br />
                          <span>{t('что важно.', 'toping.')}</span>
                        </h2>
                        <p>
                          {t(
                            'Одна сделка или целый рынок — начните с поиска или готового аналитического среза.',
                            'Bitta bitim yoki butun bozor — qidiruv yoki tayyor tahliliy hisobotdan boshlang.',
                          )}
                        </p>
                      </div>
                      <div className="explorer-tools">
                        <form className="global-search" onSubmit={submitSearch}>
                          <Search size={21} />
                          <input
                            aria-label={t(
                              'Поиск сделки, ИНН или товара',
                              'Bitim, STIR yoki tovarni qidirish',
                            )}
                            placeholder={t(
                              'Номер сделки, ИНН или название товара',
                              'Bitim raqami, STIR yoki tovar nomi',
                            )}
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            maxLength={160}
                          />
                          <button
                            type="submit"
                            aria-label={t('Найти', 'Qidirish')}
                            disabled={detailLoading}
                          >
                            {detailLoading ? (
                              <Loader2 className="spin" size={20} />
                            ) : (
                              <ArrowUpRight size={23} />
                            )}
                          </button>
                        </form>
                        <div className="search-hint">
                          <span>
                            {t('Попробуйте', 'Sinab ko‘ring')}:{' '}
                            <button
                              onClick={() => {
                                setQuery('100007');
                                void openDeal(100007);
                              }}
                            >
                              №100007
                            </button>
                            <span>·</span>
                            <button
                              onClick={() => {
                                setQuery(t('Карбамид', 'Карбамид'));
                                setSearch('Карбамид');
                                goRegistry();
                              }}
                            >
                              {t('Карбамид', 'Karbamid')}
                            </button>
                          </span>
                          <kbd>↵ ENTER</kbd>
                        </div>
                        <div className="quick-reports">
                          {reportOptions.map((item) => (
                            <button
                              key={item.id}
                              onClick={() => void openReport(item.id)}
                              disabled={!!reportLoading}
                            >
                              <item.icon size={15} />
                              <span>{item[lang]}</span>
                              {reportLoading === item.id ? (
                                <Loader2 size={13} className="spin" />
                              ) : (
                                <ArrowUpRight size={13} />
                              )}
                            </button>
                          ))}
                        </div>
                        {reportError && (
                          <p className="inline-error" role="alert">
                            {reportError}
                          </p>
                        )}
                      </div>
                    </section>
                    {renderRegistry(true)}
                  </>
                ) : (
                  renderRegistry(false)
                )}
              </motion.div>
            </AnimatePresence>
            <section className="trust-strip">
              <div className="trust-symbol">
                <ShieldCheck size={23} />
              </div>
              <div>
                <strong>
                  {t('Цифры, которые можно проверить.', 'Tekshirish mumkin bo‘lgan raqamlar.')}
                </strong>
                <p>
                  {t(
                    'Каждый расчёт опирается на исходные сделки. Компании, суммы и курсы в наборе — вымышленные.',
                    'Har bir hisob-kitob asl bitimlarga asoslanadi. To‘plamdagi kompaniyalar, summalar va kurslar — o‘ylab topilgan.',
                  )}
                </p>
              </div>
              <button className="text-button" onClick={() => setMethod(true)}>
                {t('Методология', 'Metodologiya')}
                <ArrowUpRight size={16} />
              </button>
            </section>
          </div>
        </main>
        <footer>
          <Brand small />
          <span>{t('СДЕЛАНО ДЛЯ UZEX AI HACKATHON 2026', 'UZEX AI HACKATHON 2026 UCHUN')}</span>
          <button onClick={() => setMethod(true)}>
            {t('Источники и расчёты', 'Manbalar va hisob-kitoblar')}
            <ArrowUpRight size={14} />
          </button>
          <span className="footer-coordinate">TASHKENT · UZ</span>
        </footer>

        <AnimatePresence>
          {method && (
            <Modal
              title={t('Прозрачность — основа.', 'Shaffoflik — asos.')}
              kicker="UZEX / DATA NOTES"
              onClose={() => setMethod(false)}
            >
              <div className="method-intro">
                <ShieldCheck size={24} />
                <p>
                  {t(
                    'Исследовательский прототип на полном наборе из 500 000 вымышленных биржевых сделок. Даты: 3 января 2022 — 30 октября 2026.',
                    '500 000 ta o‘ylab topilgan birja bitimidan iborat to‘liq to‘plam asosidagi tadqiqot prototipi. Davr: 2022-yil 3-yanvar — 2026-yil 30-oktabr.',
                  )}
                </p>
              </div>
              <div className="method-list">
                {[
                  [
                    t('Девять исходных таблиц', 'To‘qqizta asl jadval'),
                    t(
                      '5 реестров по годам, 6 616 контрактов, 14 392 участника, 120 брокеров и 1 765 ежедневных курсов.',
                      '5 yillik reyestr, 6 616 shartnoma, 14 392 ishtirokchi, 120 broker va 1 765 kunlik kurs.',
                    ),
                  ],
                  [
                    t('Объём ≠ количество лотов', 'Hajm ≠ lotlar soni'),
                    t(
                      'Физический объём = количество × размер лота. Разные единицы измерения не складываются.',
                      'Fizik hajm = lotlar soni × lot o‘lchami. Turli o‘lchov birliklari qo‘shilmaydi.',
                    ),
                  ],
                  [
                    t('Валюты учитываются отдельно', 'Valyutalar alohida hisoblanadi'),
                    t(
                      'USD переводится в UZS по курсу на дату каждой сделки. Промежуточные суммы не округляются; отображение денег — до двух знаков.',
                      'USD har bir bitim sanasidagi kurs bo‘yicha UZSga o‘giriladi. Oraliq summalar yaxlitlanmaydi; pullar ikki kasr xonasigacha ko‘rsatiladi.',
                    ),
                  ],
                  [
                    t('Состояния на 30.10.2026', 'Holatlar 30.10.2026 sanasiga'),
                    t(
                      'По умолчанию показаны все зарегистрированные сделки, включая аннулированные. Для состоявшихся сделок выберите «без аннулированных». Сумма сделок не является прибылью.',
                      'Odatda bekor qilinganlarni ham o‘z ichiga olgan barcha qayd etilgan bitimlar ko‘rsatiladi. «Bekor qilinganlarsiz» filtridan foydalanishingiz mumkin. Bitim summasi foyda emas.',
                    ),
                  ],
                  [
                    t('География связей', 'Aloqalar geografiyasi'),
                    t(
                      'Точки обозначают регионы. Дуги — крупнейшие связи по сумме: склад продавца → регистрационный регион покупателя. Это агрегаты выбранного периода, не трансляция торгов в реальном времени.',
                      'Nuqtalar hududlarni bildiradi. Yoylar summa bo‘yicha eng yirik aloqalar: sotuvchi ombori → xaridor ro‘yxatdan o‘tgan hudud. Bu tanlangan davr jamlanmasi, real vaqtdagi savdo emas.',
                    ),
                  ],
                  [
                    t('Автономная версия', 'Avtonom versiya'),
                    t(
                      'Фильтры, поиск и отчёты работают по локальной базе. Gemini разбирает вопрос в план; расчёты выполняются сервером. Если модели недоступны, это сообщается отдельно от отсутствия данных.',
                      'Filtrlar, qidiruv va hisobotlar mahalliy baza bilan ishlaydi. Gemini savolni rejaga aylantiradi; hisob-kitoblar serverda bajariladi. Model nosozligi ma’lumot yo‘qligidan alohida ko‘rsatiladi.',
                    ),
                  ],
                ].map(([a, b], i) => (
                  <div key={a}>
                    <span className="mono">0{i + 1}</span>
                    <div>
                      <h3>{a}</h3>
                      <p>{b}</p>
                    </div>
                  </div>
                ))}
              </div>
              <div className="method-source">
                <Database size={16} />
                <span>
                  deals_2022…2026.csv · contracts.csv · participants.csv · brokers.csv ·
                  usd_rates.csv
                </span>
              </div>
            </Modal>
          )}
          {report && (
            <Modal wide title={report.title} kicker={scopeLabel} onClose={() => setReport(null)}>
              <div className="report-stats">
                <div>
                  <span>{t('Сделок в расчёте', 'Hisobdagi bitimlar')}</span>
                  <strong>{integer(report.totals.deals)}</strong>
                </div>
                <div>
                  <span>{t('Сумма в сумах', 'So‘mdagi summa')}</span>
                  <strong>{exact(report.totals.amount_uzs)}</strong>
                </div>
                <button
                  className="outline-button"
                  onClick={() => {
                    csvDownload(
                      `uzex-${report.kind}.csv`,
                      ['id', 'label', 'deals', 'amount_uzs'],
                      report.rows.map((r) => [r.id, r.label, r.deals, r.amount_uzs]),
                    );
                    setToast(t('Отчёт выгружен', 'Hisobot yuklandi'));
                  }}
                >
                  <Download size={15} />
                  CSV
                </button>
              </div>
              <div className="table-scroll">
                <table className="report-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>{t('Наименование', 'Nomi')}</th>
                      <th>{t('Сделки', 'Bitimlar')}</th>
                      <th>{t('Сумма, UZS', 'Summa, UZS')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.rows.map((r, i) => (
                      <tr key={r.id}>
                        <td className="mono">{String(i + 1).padStart(2, '0')}</td>
                        <td>
                          <strong>{r.label}</strong>
                          {r.id !== r.label && <span className="table-sub">{r.id}</span>}
                        </td>
                        <td>{integer(r.deals)}</td>
                        <td className="number">{exact(r.amount_uzs)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!report.rows.length && (
                  <div className="empty-state">
                    {t('В этой выборке данных нет.', 'Bu tanlanmada ma’lumot yo‘q.')}
                  </div>
                )}
              </div>
              <div className="report-footnote">
                {report.kind === 'late'
                  ? t(
                      'Завершённая полная или частичная поставка позже срока: дата оплаты + срок поставки в календарных днях.',
                      'To‘liq yoki qisman yakunlangan yetkazib berish muddati: to‘lov sanasi + kalendar kunlaridagi yetkazib berish muddati.',
                    )
                  : report.kind === 'months'
                    ? t(
                        'Все месяцы выбранного периода. Суммы в UZS по курсу каждой сделки.',
                        'Tanlangan davrning barcha oylari. Summalar har bir bitim kursi bo‘yicha UZSda.',
                      )
                    : t(
                        'Суммы приведены к UZS по курсу каждой сделки. Таблица показывает до 20 позиций; итоги рассчитаны по всей выборке.',
                        'Summalar har bir bitim kursi bo‘yicha UZSga o‘girilgan. Jadvalda 20 tagacha pozitsiya; jami butun tanlanma bo‘yicha hisoblangan.',
                      )}
              </div>
              <button
                className="sources-toggle"
                onClick={() => setSourceOpen((v) => !v)}
                aria-expanded={sourceOpen}
              >
                <ShieldCheck size={16} />
                {t('Проверить основание расчёта', 'Hisob-kitob asosini tekshirish')}
                <ChevronDown size={16} className={sourceOpen ? 'rotate' : ''} />
              </button>
              {sourceOpen && (
                <div className="sources-panel">
                  <p>
                    {t('Источники', 'Manbalar')}: {report.provenance.sources.join(', ')}
                  </p>
                  <p>{t('Состояния зафиксированы на', 'Holatlar sanasi')}: 30.10.2026</p>
                  <pre>{report.provenance.sql.trim()}</pre>
                  <p className="mono">{JSON.stringify(report.provenance.parameters)}</p>
                </div>
              )}
            </Modal>
          )}
          {detail && (
            <Modal
              wide
              title={t(`Сделка №${detail.deal_id}`, `${detail.deal_id}-raqamli bitim`)}
              kicker={`${dateLabel(detail.deal_date, lang)} / ${detail.contract_type} / ${detail.form}`}
              onClose={() => setDetail(null)}
            >
              <div className="deal-product">
                <Boxes size={23} />
                <h3>{detail.product_label}</h3>
                <span
                  className={`deal-status ${detail.status.includes('Аннулирован') ? 'cancelled' : ''}`}
                >
                  {lang === 'uz' ? STATUS_UZ[detail.status] || detail.status : detail.status}
                </span>
              </div>
              <div className="deal-numbers">
                <div>
                  <span>{t('Сумма сделки', 'Bitim summasi')}</span>
                  <strong>
                    {exact(detail.amount_native)}
                    <small>{detail.currency}</small>
                  </strong>
                </div>
                <div>
                  <span>{t('Физический объём', 'Fizik hajm')}</span>
                  <strong>
                    {exact(detail.quantity, 0)}
                    <small>{detail.unit}</small>
                  </strong>
                </div>
              </div>
              <div className="volume-proof">
                <span>{t('Расчёт объёма', 'Hajm hisobi')}</span>
                <strong>
                  {exact(detail.lot_count, 0)} × {exact(detail.lot_size, 0)} ={' '}
                  {exact(detail.quantity, 0)} {detail.unit}
                </strong>
              </div>
              {detail.currency === 'USD' && (
                <div className="volume-proof">
                  <span>{t('Пересчёт валюты', 'Valyutani o‘girish')}</span>
                  <strong>
                    {exact(detail.amount_native)} USD × {exact(detail.usd_rate)} ={' '}
                    {exact(detail.amount_uzs)} UZS
                  </strong>
                </div>
              )}
              <div className="deal-parties">
                <div>
                  <span className="eyebrow dark">{t('ПРОДАВЕЦ', 'SOTUVCHI')}</span>
                  <h4>{detail.seller_name}</h4>
                  <p>
                    {t('ИНН', 'STIR')} {detail.seller_inn}
                  </p>
                  <p>
                    {detail.seller_broker} · {detail.seller_broker_detail.name}
                  </p>
                  <button
                    className="text-button"
                    onClick={() => {
                      setSearch(detail.seller_inn);
                      setQuery(detail.seller_inn);
                      setDetail(null);
                      goRegistry();
                    }}
                  >
                    {t('Сделки компании', 'Kompaniya bitimlari')}
                    <ArrowUpRight size={12} />
                  </button>
                </div>
                <div>
                  <span className="eyebrow dark">{t('ПОКУПАТЕЛЬ', 'XARIDOR')}</span>
                  <h4>{detail.buyer_name}</h4>
                  <p>
                    {t('ИНН', 'STIR')} {detail.buyer_inn}
                  </p>
                  <p>
                    {detail.buyer_broker} · {detail.buyer_broker_detail.name}
                  </p>
                  <button
                    className="text-button"
                    onClick={() => {
                      setSearch(detail.buyer_inn);
                      setQuery(detail.buyer_inn);
                      setDetail(null);
                      goRegistry();
                    }}
                  >
                    {t('Сделки компании', 'Kompaniya bitimlari')}
                    <ArrowUpRight size={12} />
                  </button>
                </div>
              </div>
              <dl className="deal-facts">
                <div>
                  <dt>{t('Цена за единицу', 'Birlik narxi')}</dt>
                  <dd>
                    {exact(detail.unit_price_native)} {detail.currency} / {detail.unit}
                  </dd>
                </div>
                <div>
                  <dt>{t('Стартовая цена за единицу', 'Boshlang‘ich birlik narxi')}</dt>
                  <dd>
                    {exact(detail.start_price)} {detail.currency}
                  </dd>
                </div>
                <div>
                  <dt>{t('Контракт', 'Shartnoma')}</dt>
                  <dd>#{detail.contract_id}</dd>
                </div>
                <div>
                  <dt>{t('Регион склада', 'Ombor hududi')}</dt>
                  <dd>{catalog?.regions.find((r) => r.id === detail.region)?.[lang]}</dd>
                </div>
                <div>
                  <dt>{t('Дата оплаты', 'To‘lov sanasi')}</dt>
                  <dd>{dateLabel(detail.payment_date, lang)}</dd>
                </div>
                <div>
                  <dt>{t('Дата поставки', 'Yetkazib berilgan sana')}</dt>
                  <dd>{dateLabel(detail.delivery_date, lang)}</dd>
                </div>
                <div>
                  <dt>{t('Фактически поставлено', 'Amalda yetkazilgan')}</dt>
                  <dd>
                    {detail.delivered_quantity
                      ? `${exact(detail.delivered_quantity, 0)} ${detail.unit}`
                      : '—'}
                  </dd>
                </div>
                <div>
                  <dt>{t('Код ТН ВЭД', 'TIF TN kodi')}</dt>
                  <dd>{String(detail.contract.tnved)}</dd>
                </div>
              </dl>
              <div className="method-source">
                <ShieldCheck size={16} />
                <span>
                  {t('Источник', 'Manba')}: deals_{detail.deal_date.slice(0, 4)}.csv · contracts.csv
                  · participants.csv · brokers.csv
                  {detail.currency === 'USD' ? ' · usd_rates.csv' : ''}
                </span>
              </div>
            </Modal>
          )}
        </AnimatePresence>
        <AnimatePresence>
          {toast && (
            <motion.div
              role="status"
              className="toast"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 10 }}
            >
              <Check size={16} />
              {toast}
            </motion.div>
          )}
        </AnimatePresence>
        {detailLoading && (
          <div className="detail-loader" role="status">
            <Loader2 size={20} className="spin" />
            {t('Открываем сделку…', 'Bitim ochilmoqda…')}
          </div>
        )}
      </div>
    </MotionConfig>
  );
}

function Donut({ rows, total }: { rows: { id: string; amount_uzs: string }[]; total: string }) {
  const colors = ['#476039', '#91a66c', '#c0d28d', '#dbe7b7', '#d7ddce'];
  const circumference = 2 * Math.PI * 49;
  let offset = 0;
  return (
    <svg className="donut" viewBox="0 0 130 130" role="img" aria-label="Commodity distribution">
      <circle cx="65" cy="65" r="49" fill="none" stroke="#e1e5db" strokeWidth="15" />
      {rows.slice(0, 4).map((r, i) => {
        const fraction = Number(total) > 0 ? Number(r.amount_uzs) / Number(total) : 0;
        const length = Math.max(0, fraction * circumference - 2.5);
        const start = offset;
        offset += fraction * circumference;
        return (
          <circle
            key={r.id}
            cx="65"
            cy="65"
            r="49"
            fill="none"
            stroke={colors[i]}
            strokeWidth="15"
            strokeDasharray={`${length} ${circumference - length}`}
            strokeDashoffset={-start}
            transform="rotate(-90 65 65)"
          />
        );
      })}
      <circle cx="65" cy="65" r="2.5" fill="#60774b" />
      <path d="M65 54v6m0 10v6M54 65h6m10 0h6" stroke="#9ca78e" />
    </svg>
  );
}
