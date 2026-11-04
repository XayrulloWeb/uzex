import { useState } from 'react';
import type { Lang, Monthly } from './types';
import { compact, exact, integer } from './lib';

export default function Chart({
  data,
  lang,
  mode = 'amount',
}: {
  data: Monthly[];
  lang: Lang;
  mode?: 'amount' | 'deals';
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 900,
    height = 230,
    pad = 15;
  const values = data.map((r) => Number(mode === 'amount' ? r.amount_uzs : r.deals));
  const max = Math.max(1, ...values) * 1.15;
  const points = values.map((v, i) => ({
    x: pad + (i / Math.max(1, values.length - 1)) * (width - pad * 2),
    y: height - 20 - (v / max) * (height - 45),
  }));
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${p.x} ${p.y}`).join(' ');
  const area = points.length
    ? `${path} L${points[points.length - 1].x} ${height - 15} L${points[0].x} ${height - 15} Z`
    : '';
  const monthName = (p: string) =>
    new Intl.DateTimeFormat(lang === 'ru' ? 'ru-RU' : 'uz-UZ', {
      month: 'short',
      year: data.length > 14 ? '2-digit' : undefined,
      timeZone: 'UTC',
    }).format(new Date(p + '-15T00:00:00Z'));
  if (!data.length)
    return (
      <div className="empty-chart">
        {lang === 'ru' ? 'За выбранный период сделок нет' : 'Tanlangan davrda bitimlar yo‘q'}
      </div>
    );
  return (
    <div className="chart" onMouseLeave={() => setHover(null)}>
      <div className="chart-grid-labels">
        {[1, 0.66, 0.33].map((v) => {
          const f = compact(max * v, lang);
          return (
            <span key={v}>
              {f.value} {f.unit}
            </span>
          );
        })}
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={
          lang === 'ru'
            ? 'Динамика зарегистрированных сделок по месяцам'
            : 'Qayd etilgan bitimlarning oylar bo‘yicha dinamikasi'
        }
      >
        <defs>
          <linearGradient id="chart-area" x1="0" y1="0" x2="0" y2="1">
            <stop stopColor="#667d4b" stopOpacity=".19" />
            <stop offset="1" stopColor="#667d4b" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.13, 0.43, 0.73].map((v) => (
          <line
            key={v}
            x1="0"
            y1={height * v}
            x2={width}
            y2={height * v}
            stroke="#dce0d5"
            strokeWidth="1"
            strokeDasharray="3 6"
          />
        ))}
        <path d={area} fill="url(#chart-area)" />
        <path
          d={path}
          fill="none"
          stroke="#536f38"
          strokeWidth="2.5"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
        {hover !== null && points[hover] && (
          <>
            <line
              x1={points[hover].x}
              x2={points[hover].x}
              y1="0"
              y2={height}
              stroke="#526c39"
              strokeDasharray="4 4"
              opacity=".5"
            />
            <circle
              cx={points[hover].x}
              cy={points[hover].y}
              r="5"
              fill="#536f38"
              stroke="#f7f8f2"
              strokeWidth="3"
            />
          </>
        )}
        {points.map((p, i) => (
          <rect
            key={i}
            x={p.x - width / points.length / 2}
            y="0"
            width={width / points.length}
            height={height}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
            onTouchStart={() => setHover(i)}
          />
        ))}
      </svg>
      {hover !== null && data[hover] && (
        <div
          className="chart-tooltip"
          style={{
            left: `${Math.min(77, Math.max(3, (hover / Math.max(1, data.length - 1)) * 87))}%`,
          }}
        >
          <span>{monthName(data[hover].period)}</span>
          <strong>
            {mode === 'amount' ? exact(data[hover].amount_uzs) : integer(data[hover].deals)}{' '}
            {mode === 'amount' ? (lang === 'ru' ? 'сум' : 'so‘m') : ''}
          </strong>
        </div>
      )}
      <div className="chart-months">
        {data.map((r, i) => (
          <span
            key={r.period}
            style={{
              visibility:
                data.length > 14 && i % Math.ceil(data.length / 12) !== 0 ? 'hidden' : 'visible',
            }}
          >
            {monthName(r.period)}
          </span>
        ))}
      </div>
    </div>
  );
}
