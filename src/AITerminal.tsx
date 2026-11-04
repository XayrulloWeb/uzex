import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, ChevronDown, Download, Loader2, ShieldCheck, Sparkles } from 'lucide-react';
import type { Lang, Scope } from './types';
import { csvDownload, exact, integer } from './lib';

type Cell = string | number | null;
type AIResponse = {
  status: 'answer' | 'no_data' | 'clarify' | 'unavailable';
  answer: string;
  columns: { key: string; label: string; kind: string; unit?: string }[];
  rows: Record<string, Cell>[];
  elapsed_ms?: number;
  provider?: { kind?: 'gemini' | 'local'; model: string; attempts: number; used_backup: boolean };
  provenance: null | {
    sql: string;
    parameters: unknown[];
    row_count: number;
    sources: string[];
    period?: { from: string; to: string };
    include_cancelled?: boolean;
    statuses?: string[];
    snapshot: string;
    date_field?: 'deal_date' | 'payment_date' | 'delivery_date';
  };
};

export default function AITerminal({
  lang,
  scope,
  onDeal,
  contextLabel,
}: {
  lang: Lang;
  scope: Scope;
  onDeal: (id: number) => void;
  contextLabel: string;
}) {
  const [question, setQuestion] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [answer, setAnswer] = useState<AIResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [sources, setSources] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const t = (ru: string, uz: string) => (lang === 'ru' ? ru : uz);
  const periodLabel =
    answer?.provenance?.date_field === 'payment_date'
      ? t('Даты оплаты', 'To‘lov sanalari')
      : answer?.provenance?.date_field === 'delivery_date'
        ? t('Даты поставки', 'Yetkazish sanalari')
        : t('Даты сделок', 'Bitim sanalari');
  useEffect(
    () => () => {
      controller.current?.abort();
      controller.current = null;
    },
    [],
  );
  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(id);
  }, [busy]);

  async function ask(text = question) {
    if (busy || text.trim().length < 2) return;
    setQuestion(text);
    setBusy(true);
    setSources(false);
    setElapsed(0);
    setAnswer(null);
    const c = new AbortController();
    controller.current = c;
    const timeout = setTimeout(() => c.abort(), 85000);
    try {
      const response = await fetch('/api/ai/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: text.trim(),
          lang,
          scope: {
            ...scope,
            year: scope.year || null,
            commodity: scope.commodity || null,
            region: scope.region || null,
          },
          history,
        }),
        signal: c.signal,
      });
      const data = await response.json();
      if (!data.answer) throw new Error('Invalid response');
      setAnswer(data);
      if (response.ok) setHistory((previous) => [...previous, text.trim()].slice(-4));
    } catch {
      if (!c.signal.aborted || controller.current === c)
        setAnswer({
          status: 'unavailable',
          answer: t(
            'Не удалось завершить запрос за отведённое время. Поиск и готовые отчёты доступны. Сбой сервиса не означает, что ответа нет в данных.',
            'So‘rovni belgilangan vaqtda yakunlab bo‘lmadi. Qidiruv va tayyor hisobotlar mavjud. Nosozlik ma’lumotlarda javob yo‘qligini anglatmaydi.',
          ),
          columns: [],
          rows: [],
          provenance: null,
        });
    } finally {
      clearTimeout(timeout);
      if (controller.current === c) setBusy(false);
    }
  }
  function formatCell(value: Cell, kind: string) {
    if (value == null) return '—';
    if (kind === 'decimal') return exact(value);
    if (kind === 'integer') return integer(value);
    return String(value);
  }
  const examples =
    lang === 'ru'
      ? [
          'Топ-5 покупателей цемента за 2024 год',
          'Сумма экспорта за 2025 год в сумах',
          'Сколько сделок было в 2027 году?',
        ]
      : [
          '2024-yilda sementning eng yirik 5 xaridori',
          '2025-yildagi eksport bitimlari summasi so‘mda',
          '2027-yilda nechta bitim bo‘lgan?',
        ];
  return (
    <section className="ai-workspace" id="ask-ai" aria-label={t('AI-аналитик', 'AI-tahlilchi')}>
      <div className="ai-top">
        <div className="ai-icon">
          <Sparkles size={23} />
        </div>
        <div>
          <div className="eyebrow">UZEX / AI ANALYST</div>
          <h2>{t('Спросите рынок.', 'Bozordan so‘rang.')}</h2>
        </div>
        <span className="ai-provider">
          GEMINI<span>RU + UZ</span>
        </span>
      </div>
      <p className="ai-description">
        {t(
          'Вопрос — на вашем языке. Числа — из реестра. Каждое вычисление можно проверить.',
          'Savol — sizning tilingizda. Raqamlar — reyestrdan. Har bir hisob-kitobni tekshirish mumkin.',
        )}
      </p>
      <div className="ai-scope">
        {t('По умолчанию', 'Odatda')}: {contextLabel}.{' '}
        {t('Период в вопросе имеет приоритет.', 'Savoldagi davr ustuvor.')}
      </div>
      <form
        className="ai-question"
        onSubmit={(e) => {
          e.preventDefault();
          void ask();
        }}
      >
        <textarea
          aria-label={t('Вопрос AI-аналитику', 'AI-tahlilchiga savol')}
          placeholder={t(
            'Например: кто больше всего купил цемента в 2024 году?',
            'Masalan: 2024-yilda kim eng ko‘p sement sotib olgan?',
          )}
          maxLength={1500}
          rows={2}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void ask();
            }
          }}
        />
        <button
          type="submit"
          disabled={busy || question.trim().length < 2}
          aria-label={t('Спросить AI', 'AIga so‘rov yuborish')}
        >
          {busy ? <Loader2 className="spin" size={22} /> : <ArrowUpRight size={25} />}
        </button>
      </form>
      <div className="ai-examples">
        {examples.map((example) => (
          <button key={example} onClick={() => void ask(example)} disabled={busy}>
            {example}
            <ArrowUpRight size={12} />
          </button>
        ))}
      </div>
      {busy && (
        <div className="ai-processing" role="status">
          <Loader2 size={15} className="spin" />
          <span>{t('Готовим проверяемый ответ', 'Tekshiriladigan javob tayyorlanmoqda')}</span>
          <strong>
            {elapsed} {t('с', 's')}
          </strong>
          <span className="ai-budget">{t('до 80 секунд', '80 soniyagacha')}</span>
        </div>
      )}
      {answer && (
        <div className={`ai-answer ai-${answer.status}`} role="status" aria-live="polite">
          <div className="ai-answer-label">
            <ShieldCheck size={16} />
            <span>
              {answer.status === 'answer'
                ? t('ОТВЕТ ПО ДАННЫМ', 'MA’LUMOTLAR ASOSIDAGI JAVOB')
                : answer.status === 'no_data'
                  ? t('ДАННЫХ НЕДОСТАТОЧНО', 'MA’LUMOT YETARLI EMAS')
                  : answer.status === 'clarify'
                    ? t('НУЖНО УТОЧНЕНИЕ', 'ANIQLASHTIRISH KERAK')
                    : t('СЕРВИС НЕДОСТУПЕН', 'XIZMAT MAVJUD EMAS')}
            </span>
            {answer.elapsed_ms !== undefined && (
              <small>
                {(answer.elapsed_ms / 1000).toFixed(1)} {t('с', 's')}
              </small>
            )}
          </div>
          <p>{answer.answer}</p>
          {answer.provenance?.period?.from && (
            <div className="ai-result-period">
              {periodLabel}: {answer.provenance.period.from} — {answer.provenance.period.to}
            </div>
          )}
          {!!answer.rows.length && (
            <>
              <div className="table-scroll">
                <table className="report-table">
                  <thead>
                    <tr>
                      {answer.columns.map((c) => (
                        <th key={c.key}>
                          {c.label}
                          {c.unit ? `, ${c.unit}` : ''}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {answer.rows.map((row, i) => (
                      <tr key={i}>
                        {answer.columns.map((c) => (
                          <td key={c.key}>
                            {c.key === 'deal_id' && row[c.key] ? (
                              <button
                                className="deal-link"
                                onClick={() => onDeal(Number(row[c.key]))}
                              >
                                #{String(row[c.key])}
                              </button>
                            ) : (
                              formatCell(row[c.key], c.kind)
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button
                className="ai-export"
                onClick={() =>
                  csvDownload(
                    'uzex-ai-result.csv',
                    answer.columns.map((c) => c.label + (c.unit ? `, ${c.unit}` : '')),
                    answer.rows.map((r) => answer.columns.map((c) => r[c.key])),
                  )
                }
              >
                <Download size={14} />
                {t('Выгрузить результат', 'Natijani yuklash')} CSV
              </button>
            </>
          )}
          {answer.provenance && (
            <>
              <button
                className="sources-toggle"
                onClick={() => setSources((s) => !s)}
                aria-expanded={sources}
              >
                <ShieldCheck size={15} />
                {t('Доказательства и расчёт', 'Dalillar va hisob-kitob')}
                <ChevronDown size={15} className={sources ? 'rotate' : ''} />
              </button>
              {sources && (
                <div className="sources-panel">
                  <p>
                    {t('Источники', 'Manbalar')}: {answer.provenance.sources.join(' · ')}
                  </p>
                  <p>
                    {t('Строк учтено', 'Hisoblangan qatorlar')}:{' '}
                    {integer(answer.provenance.row_count)} · {t('Срез', 'Holat')}:{' '}
                    {answer.provenance.snapshot}
                  </p>
                  {answer.provenance.period && (
                    <p>
                      {periodLabel}: {answer.provenance.period.from} — {answer.provenance.period.to}
                    </p>
                  )}
                  <pre>{answer.provenance.sql}</pre>
                  <p className="mono">{JSON.stringify(answer.provenance.parameters)}</p>
                  {answer.provider && (
                    <p>
                      {answer.provider.kind === 'local'
                        ? t('Локальный проверенный расчёт', 'Mahalliy tekshirilgan hisob-kitob')
                        : `Gemini: ${answer.provider.model}`}
                      {answer.provider.used_backup && answer.provider.kind !== 'local'
                        ? ' · ' +
                          t(
                            'использована резервная модель или ключ',
                            'zaxira model yoki kalit ishlatilgan',
                          )
                        : ''}
                    </p>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
      <div className="ai-footnote">
        <ShieldCheck size={13} />
        {t(
          'Модель разбирает вопрос. Числа рассчитываются в базе. Отсутствие данных и сбой модели различаются.',
          'Model savolni tahlil qiladi. Raqamlar bazada hisoblanadi. Ma’lumot yo‘qligi va model nosozligi farqlanadi.',
        )}
      </div>
    </section>
  );
}
