'use client';

import { useCallback, useEffect, useState } from 'react';
import { CircleAlert, Download, Minus, Printer, TrendingDown, TrendingUp } from 'lucide-react';
import { api, queryString } from '@/lib/api';
import { CATEGORY_LABELS, formatChange, formatDuration, hourRange, presetRange, SEVERITY_ORDER, siteToday, WEEKDAYS } from '@/lib/format';
import type { PeriodReport } from '@/lib/types';
import { useSystem } from '@/components/SystemProvider';
import { SeriesChart } from '@/components/SeriesChart';
import { SeverityBadge } from '@/components/AlertBadges';

type Preset = 'today' | 'yesterday' | '7d' | '30d' | 'month' | 'last_month' | 'custom';

const PRESETS: [Preset, string][] = [
  ['today', 'Today'],
  ['yesterday', 'Yesterday'],
  ['7d', 'Last 7 days'],
  ['30d', 'Last 30 days'],
  ['month', 'This month'],
  ['last_month', 'Last month'],
  ['custom', 'Custom'],
];

const ENTRY = { key: 'entries', label: 'Entries', color: 'var(--series-entry)' };
const EXIT = { key: 'exits', label: 'Exits', color: 'var(--series-exit)' };

function shortDate(iso: string): string {
  const [, m, d] = iso.split('-').map(Number);
  return `${d} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m - 1]}`;
}

export default function ReportsView() {
  const { timezone, cameras, locations, locationId, selectLocation } = useSystem();
  const today = siteToday(timezone);
  const [preset, setPreset] = useState<Preset>('7d');
  const [range, setRange] = useState<[string, string]>(() => presetRange('7d', today));
  const [cameraId, setCameraId] = useState('');
  const [data, setData] = useState<PeriodReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const choose = (p: Preset) => {
    setPreset(p);
    if (p !== 'custom') setRange(presetRange(p, today));
  };

  const params = { date_from: range[0], date_to: range[1], location_id: locationId, camera_id: cameraId };
  const key = JSON.stringify(params);

  const load = useCallback(async () => {
    if (!range[0] || !range[1]) return;
    setLoading(true);
    try {
      setData(await api<PeriodReport>(`/reports/summary${queryString(JSON.parse(key))}`));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [key, range]);

  useEffect(() => {
    load();
  }, [load]);

  const csv = (section: string) => `/api/v1/reports/export.csv${queryString({ ...params, section })}`;
  const scopeCameras = cameras.filter((c) => locationId === null || c.location_id === locationId);
  const locationName = locationId === null ? 'All locations' : locations.find((l) => l.id === locationId)?.name;
  const cameraName = cameraId ? cameras.find((c) => c.id === cameraId)?.name : null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Reports</h1>
          <p>
            Footfall and activity from recorded events · {locationName}
            {cameraName ? ` · ${cameraName}` : ''} · {timezone}
          </p>
        </div>
        <div className="control-row no-print">
          <button type="button" className="btn" onClick={() => window.print()} disabled={!data}>
            <Printer size={14} /> Print / PDF
          </button>
        </div>
      </div>

      <section className="panel no-print" style={{ marginBottom: 16 }}>
        <div className="filters" style={{ borderBottom: 'none' }}>
          <div className="field">
            <span className="field-label">Period</span>
            <div className="segmented" role="group" aria-label="Report period">
              {PRESETS.map(([p, label]) => (
                <button key={p} type="button" aria-pressed={preset === p} onClick={() => choose(p)}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          {preset === 'custom' && (
            <>
              <div className="field">
                <label htmlFor="r-from">From</label>
                <input id="r-from" className="input" type="date" value={range[0]} max={range[1]} onChange={(e) => setRange([e.target.value, range[1]])} />
              </div>
              <div className="field">
                <label htmlFor="r-to">To</label>
                <input id="r-to" className="input" type="date" value={range[1]} min={range[0]} max={today} onChange={(e) => setRange([range[0], e.target.value])} />
              </div>
            </>
          )}
          {locations.length > 1 && (
            <div className="field">
              <label htmlFor="r-loc">Location</label>
              <select
                id="r-loc"
                className="select"
                value={locationId ?? ''}
                onChange={(e) => {
                  selectLocation(e.target.value ? Number(e.target.value) : null);
                  setCameraId('');
                }}
              >
                <option value="">All locations</option>
                {locations.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="field">
            <label htmlFor="r-cam">Camera</label>
            <select id="r-cam" className="select" value={cameraId} onChange={(e) => setCameraId(e.target.value)}>
              <option value="">All cameras</option>
              {scopeCameras.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      {error && (
        <div className="banner banner-err" role="alert">
          <CircleAlert size={16} /> {error}
          <div className="banner-actions">
            <button type="button" className="btn btn-sm" onClick={load}>
              Retry
            </button>
          </div>
        </div>
      )}

      {!data ? (
        <p className="muted">{loading ? 'Building report…' : ''}</p>
      ) : (
        <div className="report" aria-busy={loading}>
          <p className="print-only report-title">
            VIAHIND Vision report · {data.date_from} to {data.date_to} · {locationName}
            {cameraName ? ` · ${cameraName}` : ''}
          </p>
          <section className="metrics" aria-label="Period totals">
            <Kpi label="Footfall (entries)" value={data.totals.entries} change={data.comparison.entries_change_pct} previous={data.comparison.previous.entries} />
            <Kpi label="Exits" value={data.totals.exits} change={data.comparison.exits_change_pct} previous={data.comparison.previous.exits} />
            <div className="metric">
              <div className="metric-label">Average per day</div>
              <div className="metric-value">{data.totals.avg_daily_footfall}</div>
              <div className="metric-foot">over {data.days} day(s)</div>
            </div>
            <div className="metric">
              <div className="metric-label">Peak hour</div>
              <div className="metric-value metric-text">{data.peak_hours[0] ? hourRange(data.peak_hours[0].hour) : '—'}</div>
              <div className="metric-foot">{data.peak_hours[0] ? `${data.peak_hours[0].entries} entries in total` : 'No entries in this period'}</div>
            </div>
          </section>
          <p className="small muted" style={{ margin: '-8px 0 16px' }}>
            Compared with {data.comparison.previous_from === data.comparison.previous_to ? data.comparison.previous_from : `${data.comparison.previous_from} to ${data.comparison.previous_to}`}.
            {data.totals.uncertain > 0 && ` ${data.totals.uncertain} unclassified crossing(s) are excluded until reviewed.`}
          </p>

          <div className="report-grid">
            {data.days > 1 && (
              <section className="panel span-2">
                <div className="panel-head">
                  <h2>Entries and exits by day</h2>
                  <a className="btn btn-sm no-print" href={csv('daily')}>
                    <Download size={13} /> CSV
                  </a>
                </div>
                <div className="panel-body">
                  <SeriesChart
                    ariaLabel="Entries and exits by day"
                    series={[ENTRY, EXIT]}
                    data={data.daily.map((d) => ({ label: shortDate(d.date), title: d.date, values: { entries: d.entries, exits: d.exits } }))}
                  />
                </div>
              </section>
            )}
            <section className="panel">
              <div className="panel-head">
                <h2>
                  By hour of day <span className="sub">· total for the period</span>
                </h2>
                <a className="btn btn-sm no-print" href={csv('hourly')}>
                  <Download size={13} /> CSV
                </a>
              </div>
              <div className="panel-body">
                <SeriesChart
                  ariaLabel="Entries and exits by hour of day"
                  series={[ENTRY, EXIT]}
                  data={data.hourly.map((h) => ({ label: `${h.hour}`, title: hourRange(h.hour), values: { entries: h.entries, exits: h.exits } }))}
                  maxLabels={8}
                />
                {data.peak_hours.length > 0 && (
                  <p className="small muted" style={{ marginTop: 8 }}>
                    Busiest: {data.peak_hours.map((h) => `${hourRange(h.hour)} (${h.entries})`).join(', ')}
                  </p>
                )}
              </div>
            </section>
            {data.days >= 7 && (
              <section className="panel">
                <div className="panel-head">
                  <h2>
                    Entries by weekday <span className="sub">· total</span>
                  </h2>
                </div>
                <div className="panel-body">
                  <SeriesChart
                    ariaLabel="Entries by day of the week"
                    series={[ENTRY]}
                    data={data.weekday.map((w) => ({ label: WEEKDAYS[w.weekday], values: { entries: w.entries } }))}
                  />
                </div>
              </section>
            )}

            <section className="panel">
              <div className="panel-head">
                <h2>By camera</h2>
                <a className="btn btn-sm no-print" href={csv('cameras')}>
                  <Download size={13} /> CSV
                </a>
              </div>
              <CountTable rows={data.cameras.map((c) => ({ name: c.camera_name, ...c }))} nameLabel="Camera" />
            </section>
            {locations.length > 1 && locationId === null && (
              <section className="panel">
                <div className="panel-head">
                  <h2>By location</h2>
                  <a className="btn btn-sm no-print" href={csv('locations')}>
                    <Download size={13} /> CSV
                  </a>
                </div>
                <CountTable rows={data.locations.map((l) => ({ name: l.location_name, ...l }))} nameLabel="Location" />
              </section>
            )}

            <section className="panel">
              <div className="panel-head">
                <h2>Alerts raised</h2>
              </div>
              <div className="panel-body">
                {data.alerts.total === 0 ? (
                  <p className="muted">No alerts in this period.</p>
                ) : (
                  <div style={{ display: 'grid', gap: 12 }}>
                    <div className="control-row">
                      {SEVERITY_ORDER.filter((s) => data.alerts.by_severity[s]).map((s) => (
                        <span key={s} className="nowrap">
                          {data.alerts.by_severity[s]} <SeverityBadge severity={s} />
                        </span>
                      ))}
                    </div>
                    <dl className="kv">
                      {Object.entries(data.alerts.by_category)
                        .sort((a, b) => b[1] - a[1])
                        .map(([c, n]) => (
                          <div key={c} style={{ display: 'contents' }}>
                            <dt>{CATEGORY_LABELS[c] ?? c}</dt>
                            <dd>{n}</dd>
                          </div>
                        ))}
                    </dl>
                    <p className="small muted">
                      {data.alerts.by_status.dismissed ?? 0} dismissed as false positives · {(data.alerts.by_status.new ?? 0) + (data.alerts.by_status.acknowledged ?? 0)} still open
                    </p>
                  </div>
                )}
              </div>
            </section>

            <section className="panel">
              <div className="panel-head">
                <h2>Visit duration</h2>
              </div>
              <div className="panel-body">
                {data.dwell.linked_visits === 0 ? (
                  <p className="muted">
                    No visits with a reliably linked entry and exit in this period. Durations are only shown when the same tracked person
                    was followed from entry to exit.
                  </p>
                ) : (
                  <p>
                    Median <strong>{formatDuration(data.dwell.median_seconds)}</strong> across {data.dwell.linked_visits} linked visit(s).{' '}
                    <span className="muted small">Most exits cannot be linked to an entry; treat this as indicative.</span>
                  </p>
                )}
              </div>
            </section>
          </div>

          <p className="small muted report-foot">
            Figures count line crossings recorded by cameras. Camera outages, occlusion, groups crossing together and uncounted
            entrances make them estimates; uncertain crossings are excluded until reviewed.
          </p>
        </div>
      )}
    </>
  );
}

function Kpi({ label, value, change, previous }: { label: string; value: number; change: number | null; previous: number }) {
  const Icon = change === null || change === 0 ? Minus : change > 0 ? TrendingUp : TrendingDown;
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-foot">
        <Icon size={13} aria-hidden="true" /> {formatChange(change)} <span className="muted">(previously {previous})</span>
      </div>
    </div>
  );
}

function CountTable({ rows, nameLabel }: { rows: { name: string; entries: number; exits: number; uncertain: number }[]; nameLabel: string }) {
  if (rows.length === 0) return <div className="empty">No recorded events in this period.</div>;
  const total = rows.reduce((s, r) => s + r.entries, 0) || 1;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>{nameLabel}</th>
            <th className="num">Entries</th>
            <th className="num">Share</th>
            <th className="num">Exits</th>
            <th className="num">Unclassified</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}>
              <td>{r.name}</td>
              <td className="num">{r.entries}</td>
              <td className="num">{Math.round((r.entries / total) * 100)}%</td>
              <td className="num">{r.exits}</td>
              <td className="num">{r.uncertain}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
