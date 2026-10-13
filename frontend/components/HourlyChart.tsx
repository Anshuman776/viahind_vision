'use client';

import { useEffect, useRef, useState } from 'react';
import type { HourBucket } from '@/lib/types';

const H = 190;
const PAD = { top: 12, right: 8, bottom: 26, left: 30 };

function hourLabel(h: number): string {
  const suffix = h < 12 ? 'AM' : 'PM';
  const v = h % 12 === 0 ? 12 : h % 12;
  return `${v} ${suffix}`;
}

function niceMax(v: number): number {
  if (v <= 4) return 4;
  const step = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * step >= v) return m * step;
  return 10 * step;
}

/** Entries and exits per hour of the site day. Grouped bars on one shared axis. */
export function HourlyChart({ data, currentHour }: { data: HourBucket[]; currentHour?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  // Draw at the container's real width so axis text stays at its CSS size.
  const ref = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(560);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(([entry]) => setW(Math.max(280, Math.round(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const labelHours = W < 420 ? [0, 6, 12, 18] : [0, 3, 6, 9, 12, 15, 18, 21];
  const max = niceMax(Math.max(0, ...data.map((d) => Math.max(d.entries, d.exits))));
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const slot = plotW / 24;
  const barW = Math.max(3, slot / 2 - 3);
  const y = (v: number) => PAD.top + plotH - (v / max) * plotH;
  const ticks = [0, max / 2, max];
  const total = data.reduce((s, d) => s + d.entries + d.exits, 0);
  const hovered = hover !== null ? data[hover] : null;

  return (
    <div className="chart" ref={ref}>
      <div className="chart-legend" style={{ marginBottom: 6 }}>
        <span>
          <span className="legend-swatch" style={{ background: 'var(--series-entry)' }} />
          Entries
        </span>
        <span>
          <span className="legend-swatch" style={{ background: 'var(--series-exit)' }} />
          Exits
        </span>
        {total === 0 && <span className="muted">No entries or exits recorded yet today.</span>}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Entries and exits per hour today" onMouseLeave={() => setHover(null)}>
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
          {labelHours.map((h) => (
            <text key={h} x={PAD.left + slot * h + slot / 2} y={H - 8} textAnchor="middle">
              {hourLabel(h)}
            </text>
          ))}
        </g>
        {data.map((d, i) => {
          const x0 = PAD.left + slot * i + (slot - barW * 2 - 2) / 2;
          const future = currentHour !== undefined && i > currentHour;
          return (
            <g key={d.hour} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)} tabIndex={d.entries + d.exits > 0 ? 0 : -1}>
              {/* Hit target spans the whole hour column. */}
              <rect x={PAD.left + slot * i} y={PAD.top} width={slot} height={plotH} fill={hover === i ? 'rgba(30,58,95,0.05)' : 'transparent'} />
              {d.entries > 0 && <Bar x={x0} y={y(d.entries)} w={barW} h={PAD.top + plotH - y(d.entries)} color="var(--series-entry)" />}
              {d.exits > 0 && <Bar x={x0 + barW + 2} y={y(d.exits)} w={barW} h={PAD.top + plotH - y(d.exits)} color="var(--series-exit)" />}
              {future && <rect x={PAD.left + slot * i} y={PAD.top + plotH - 1} width={slot} height={1} fill="#e3e0d8" />}
            </g>
          );
        })}
        <line x1={PAD.left} x2={W - PAD.right} y1={PAD.top + plotH} y2={PAD.top + plotH} stroke="#cfcbc0" />
      </svg>
      {hovered && hover !== null && (
        <div className="chart-tooltip" style={{ left: `${((PAD.left + slot * hover + slot / 2) / W) * 100}%`, top: 24 }}>
          <strong>
            {hourLabel(hover)}–{hourLabel((hover + 1) % 24)}
          </strong>
          <br />
          {hovered.entries} entr{hovered.entries === 1 ? 'y' : 'ies'} · {hovered.exits} exit{hovered.exits === 1 ? '' : 's'}
        </div>
      )}
      <table className="sr-only">
        <caption>Entries and exits per hour today</caption>
        <thead>
          <tr>
            <th>Hour</th>
            <th>Entries</th>
            <th>Exits</th>
          </tr>
        </thead>
        <tbody>
          {data
            .filter((d) => d.entries + d.exits > 0)
            .map((d) => (
              <tr key={d.hour}>
                <td>{hourLabel(d.hour)}</td>
                <td>{d.entries}</td>
                <td>{d.exits}</td>
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
