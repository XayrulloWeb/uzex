import type { Lang, Scope } from './types';

export function params(scope: Scope, extra: Record<string, string | number> = {}) {
  const p = new URLSearchParams({ year: String(scope.year), status: scope.status });
  if (scope.region) p.set('region', scope.region);
  if (scope.commodity) p.set('commodity', scope.commodity);
  Object.entries(extra).forEach(([k, v]) => p.set(k, String(v)));
  return p.toString();
}

export async function api<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

export function integer(value: number | string) {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(Number(value));
}

// Decimal strings are formatted without converting large money values to binary floats.
export function exact(value: string | number, decimals = 2) {
  let input = String(value);
  const negative = input.startsWith('-');
  if (negative) input = input.slice(1);
  const [whole = '0', raw = ''] = input.split('.');
  const digits = raw.padEnd(decimals + 1, '0');
  let scaled =
    BigInt(whole || '0') * 10n ** BigInt(decimals) + BigInt(digits.slice(0, decimals) || '0');
  if (Number(digits[decimals] || '0') >= 5) scaled += 1n;
  const str = scaled.toString().padStart(decimals + 1, '0');
  const head = decimals ? str.slice(0, -decimals) : str;
  return `${negative ? '−' : ''}${head.replace(/\B(?=(\d{3})+(?!\d))/g, '\u202f')}${decimals ? ',' + str.slice(-decimals) : ''}`;
}

export function compact(value: string | number, lang: Lang = 'ru') {
  const n = Number(value);
  const unit =
    n >= 1e12
      ? lang === 'ru'
        ? 'трлн'
        : 'trln'
      : n >= 1e9
        ? lang === 'ru'
          ? 'млрд'
          : 'mlrd'
        : n >= 1e6
          ? lang === 'ru'
            ? 'млн'
            : 'mln'
          : n >= 1e3
            ? lang === 'ru'
              ? 'тыс.'
              : 'ming'
            : '';
  const scale = n >= 1e12 ? 1e12 : n >= 1e9 ? 1e9 : n >= 1e6 ? 1e6 : n >= 1e3 ? 1e3 : 1;
  return {
    value: new Intl.NumberFormat('ru-RU', { maximumFractionDigits: scale === 1 ? 0 : 2 }).format(
      n / scale,
    ),
    unit,
  };
}

export function dateLabel(value: string | null, lang: Lang = 'ru') {
  if (!value) return '—';
  return new Intl.DateTimeFormat(lang === 'ru' ? 'ru-RU' : 'uz-UZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'Asia/Tashkent',
  }).format(new Date(value + 'T00:00:00+05:00'));
}

export function csvDownload(name: string, headers: string[], rows: (string | number | null)[][]) {
  const escape = (v: string | number | null) => {
    let s = String(v ?? '');
    if (/^[=+@\-]/.test(s)) s = "'" + s;
    return '"' + s.replaceAll('"', '""') + '"';
  };
  const blob = new Blob(
    ['\uFEFF' + [headers, ...rows].map((r) => r.map(escape).join(',')).join('\r\n')],
    { type: 'text/csv;charset=utf-8;' },
  );
  const a = document.createElement('a');
  const url = URL.createObjectURL(blob);
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const STATUS_UZ: Record<string, string> = {
  Исполнен: 'Bajarilgan',
  'Исполнен(Частично)': 'Qisman bajarilgan',
  'Аннулирован(Не оплачен)': 'Bekor qilingan',
  Оплачен: 'To‘langan',
  Заключен: 'Tuzilgan',
  'Ждёт оплату': 'To‘lov kutilmoqda',
  'Не подписан': 'Imzolanmagan',
  Новый: 'Yangi',
};
