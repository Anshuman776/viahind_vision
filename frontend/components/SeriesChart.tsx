'use client';

import { useEffect, useRef, useState } from 'react';

export interface SeriesDef {
  key: string;
  label: string;
  color: string;
}

export interface SeriesPoint {
  label: string;
  /** Longer label for the tooltip and the accessible table. */
  title?: string;
  values: Record<string, number | null>;
}

const H = 200;
const PAD = { top: 12, right: 8, bottom: 26, left: 34 };

function niceMax(v: number): number {
  if (v <= 4) return 4;
  const step = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * step >= v) return m * step;
  return 10 * step;
}

/**
 * Grouped bars on one shared y-axis (never two scales). One or two series; a legend is shown
 * for two series, the panel title names a single one. Hover/focus shows a tooltip; a hidden
 * table carries the same numbers for screen readers.
 */
export function SeriesChart({
  data,
  series,
  ariaLabel,
  emptyText = 'No data for this period.',
  maxLabels = 12,
}: {
  data: SeriesPoint[];
  series: SeriesDef[];
  ariaLabel: string;
  emptyText?: string;
  maxLabels?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(560);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(([entry]) => setW(Math.max(280, Math.round(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const n = Math.max(1, data.length);
  const values = data.flatMap((d) => series.map((s) => d.values[s.key] ?? 0));
  const total = values.reduce((a, b) => a + b, 0);
  const max = niceMax(Math.max(0, ...values));
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const slot = plotW / n;
  const gap = 2;
  const barW = Math.max(2, Math.min(28, (slot - 4 - gap * (series.length - 1)) / series.length));
  const y = (v: number) => PAD.top + plotH - (v / max) * plotH;
  const ticks = [0, max / 2, max];
  const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(Math.min(maxLabels, W / 56)))));
  const hovered = hover !== null ? data[hover] : null;

  return (
    <div className="chart" ref={ref}>
      {series.length > 1 && (
        <div className="chart-legend" style={{ marginBottom: 6 }}>
          {series.map((s) => (
            <span key={s.key}>
              <span className="legend-swatch" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
      {total === 0 && <p className="muted small" style={{ marginBottom: 6 }}>{emptyText}</p>}
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={ariaLabel} onMouseLeave={() => setHover(null)}>
        <g className="grid">
          {ticks.map((t) => (
            <line key={t} x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} />
          ))}
        </g>
        <g className="axis">
          {ticks.map((t) => (
            <text key={t} x={PAD.left - 6} y={y(t) + 4} textAnchor="end">
              {Number.isInteger(t) ? t : t.toFixed(1)}
            </text>
          ))}
          {data.map((d, i) =>
            i % every === 0 ? (
              <text key={i} x={PAD.left + slot * i + slot / 2} y={H - 8} textAnchor="middle">
                {d.label}
              </text>
            ) : null,
          )}
        </g>
        {data.map((d, i) => {
          const groupW = barW * series.length + gap * (series.length - 1);
          const x0 = PAD.left + slot * i + (slot - groupW) / 2;
          const has = series.some((s) => (d.values[s.key] ?? 0) > 0);
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)} tabIndex={has ? 0 : -1}>
              <rect x={PAD.left + slot * i} y={PAD.top} width={slot} height={plotH} fill={hover === i ? 'rgba(30,58,95,0.05)' : 'transparent'} />
              {series.map((s, k) => {
                const v = d.values[s.key] ?? 0;
                return v > 0 ? <Bar key={s.key} x={x0 + k * (barW + gap)} y={y(v)} w={barW} h={PAD.top + plotH - y(v)} color={s.color} /> : null;
              })}
            </g>
          );
        })}
        <line x1={PAD.left} x2={W - PAD.right} y1={PAD.top + plotH} y2={PAD.top + plotH} stroke="#cfcbc0" />
      </svg>
      {hovered && hover !== null && (
        <div className="chart-tooltip" style={{ left: `${((PAD.left + slot * hover + slot / 2) / W) * 100}%`, top: 24 }}>
          <strong>{hovered.title ?? hovered.label}</strong>
          {series.map((s) => (
            <div key={s.key}>
              {s.label}: {hovered.values[s.key] ?? '—'}
            </div>
          ))}
        </div>
      )}
      <table className="sr-only">
        <caption>{ariaLabel}</caption>
        <thead>
          <tr>
            <th>Period</th>
            {series.map((s) => (
              <th key={s.key}>{s.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((d, i) => (
            <tr key={i}>
              <td>{d.title ?? d.label}</td>
              {series.map((s) => (
                <td key={s.key}>{d.values[s.key] ?? '—'}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Bar with a 4px rounded top, square at the baseline. */
function Bar({ x, y, w, h, color }: { x: number; y: number; w: number; h: number; color: string }) {
  const r = Math.min(4, w / 2, h);
  const d = `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`;
  return <path d={d} fill={color} />;
}
