'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowDownToLine, ArrowUpFromLine, Bell, Clock, TriangleAlert, UsersRound } from 'lucide-react';
import { api, queryString } from '@/lib/api';
import { formatAgo, formatChange, formatDateTime, hourRange, SEVERITY_ORDER, SOURCE_LABELS } from '@/lib/format';
import type { Overview } from '@/lib/types';
import { useSession } from '@/components/SessionProvider';
import { useSystem } from '@/components/SystemProvider';
import { CameraStatusBadge } from '@/components/Status';
import { SeverityBadge } from '@/components/AlertBadges';
import { LiveFeed } from '@/components/LiveFeed';
import { HourlyChart } from '@/components/HourlyChart';
import { EventsTable } from '@/components/EventsTable';
import { EventDrawer } from '@/components/EventDrawer';
import { Dialog } from '@/components/Dialog';

function pct(today: number, before: number): number | null {
  if (before === 0) return null;
  return Math.round(((today - before) / before) * 1000) / 10;
}

export default function OverviewView() {
  const { isOperator } = useSession();
  const { timezone, cameras, selectedCameraId, dataVersion, alertVersion, locationId, locations } = useSystem();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openEvent, setOpenEvent] = useState<string | null>(null);
  const [reconcileOpen, setReconcileOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api<Overview>(`/overview${queryString({ location_id: locationId })}`));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [locationId]);

  useEffect(() => {
    load();
  }, [load, dataVersion, alertVersion]);

  useEffect(() => {
    const t = window.setInterval(load, 30000); // also picks up the date change at midnight
    return () => window.clearInterval(t);
  }, [load]);

  const scopedCameras = locationId === null ? cameras : cameras.filter((c) => c.location_id === locationId);
  const camera = scopedCameras.find((c) => c.id === selectedCameraId) ?? scopedCameras[0];
  const occ = data?.occupancy;
  const currentHour = Number(new Intl.DateTimeFormat('en-GB', { hour: '2-digit', hour12: false, timeZone: timezone }).format(new Date())) % 24;
  const locationName = locationId === null ? (locations.length > 1 ? 'All locations' : null) : locations.find((l) => l.id === locationId)?.name;
  const yesterday = data?.yesterday_same_time;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Overview</h1>
          <p>
            Today{locationName ? ` · ${locationName}` : ''}, from recorded events{data ? ` · ${data.today.timezone}` : ''}.
          </p>
        </div>
        {data && <FreshnessLine data={data} timezone={timezone} />}
      </div>

      {error && (
        <div className="banner banner-err" role="alert">
          <TriangleAlert size={16} />
          <span>{error}</span>
          <div className="banner-actions">
            <button type="button" className="btn btn-sm" onClick={load}>
              Retry
            </button>
          </div>
        </div>
      )}

      <section className="metrics" aria-label="Today's figures">
        <div className="metric">
          <div className="metric-label">
            <UsersRound size={15} aria-hidden="true" /> Estimated occupancy
          </div>
          <div className="metric-value">
            {occ ? occ.count : '—'}
            {occ?.capacity ? <span className="metric-unit"> / {occ.capacity}</span> : null}
          </div>
          <div className="metric-foot">
            {occ?.estimated ? (
              <span className="badge badge-warn" title={occ.reasons.join(' ')}>
                <TriangleAlert size={12} aria-hidden="true" /> Needs reconciling
              </span>
            ) : occ ? (
              <span>{occ.last_reconciled_at ? `Head count ${formatAgo(Date.parse(occ.last_reconciled_at) / 1000)}` : 'From entries and exits'}</span>
            ) : null}
            {occ && isOperator && (
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => setReconcileOpen(true)} style={{ height: 22 }}>
                Reconcile
              </button>
            )}
          </div>
        </div>
        <Metric
          icon={<ArrowDownToLine size={15} />}
          label="Entries today (footfall)"
          value={data?.today.entries}
          foot={yesterday ? `${formatChange(pct(data!.today.entries, yesterday.entries))} vs yesterday by ${yesterday.until_local_time}` : undefined}
        />
        <Metric
          icon={<ArrowUpFromLine size={15} />}
          label="Exits today"
          value={data?.today.exits}
          foot={data && data.today.uncertain > 0 ? `${data.today.uncertain} unclassified crossing(s) to review` : yesterday ? `${yesterday.exits} by this time yesterday` : undefined}
        />
        {isOperator ? (
          <div className="metric">
            <div className="metric-label">
              <Bell size={15} aria-hidden="true" /> Open alerts
            </div>
            <div className="metric-value">{data ? data.alerts.open : '—'}</div>
            <div className="metric-foot">
              {data && data.alerts.open > 0 ? (
                <>
                  {SEVERITY_ORDER.filter((s) => data.alerts.by_severity[s]).slice(0, 2).map((s) => (
                    <span key={s}>
                      {data.alerts.by_severity[s]} <SeverityBadge severity={s} />
                    </span>
                  ))}
                  <Link href="/alerts">Review</Link>
                </>
              ) : (
                <span>{data ? 'Nothing waiting for review' : ''}</span>
              )}
            </div>
          </div>
        ) : (
          <Metric
            icon={<Clock size={15} />}
            label="Busiest hour so far"
            value={undefined}
            text={data?.today.peak_hour !== null && data?.today.peak_hour !== undefined ? hourRange(data.today.peak_hour) : data ? 'No entries yet' : undefined}
          />
        )}
      </section>

      {occ?.estimated && (
        <div className="banner banner-warn" role="status">
          <TriangleAlert size={16} />
          <div>
            <strong>Occupancy is an estimate.</strong> {occ.reasons.join(' ')}
          </div>
          {isOperator && (
            <div className="banner-actions">
              <button type="button" className="btn btn-sm" onClick={() => setReconcileOpen(true)}>
                Reconcile with head count
              </button>
            </div>
          )}
        </div>
      )}

      {occ && occ.locations.length > 1 && (
        <section className="panel" aria-labelledby="loc-occ-title" style={{ marginBottom: 16 }}>
          <div className="panel-head">
            <h2 id="loc-occ-title">By location</h2>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Location</th>
                  <th className="num">Estimated occupancy</th>
                  <th className="num">Capacity</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {occ.locations.map((l) => (
                  <tr key={l.location_id}>
                    <td>{l.location_name}</td>
                    <td className="num">{l.count}</td>
                    <td className="num">{l.capacity ?? '—'}</td>
                    <td>
                      {l.estimated ? (
                        <span className="badge badge-warn" title={l.reasons.join(' ')}>
                          <TriangleAlert size={12} aria-hidden="true" /> Needs reconciling
                        </span>
                      ) : (
                        <span className="badge badge-ok">Reconciled</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div className="overview-grid">
        <section className="panel" aria-labelledby="preview-title">
          <div className="panel-head">
            <h2 id="preview-title">
              {isOperator ? 'Live preview' : 'Entries and exits by hour'} {isOperator && camera && <span className="sub">· {camera.name}</span>}
              {!isOperator && <span className="sub">· today</span>}
            </h2>
            {isOperator && (
              <Link href="/live" className="btn btn-sm">
                Open Live Cameras
              </Link>
            )}
          </div>
          <div className="panel-body">
            {!isOperator ? (
              data ? <HourlyChart data={data.today.hourly} currentHour={currentHour} /> : <p className="muted">Loading…</p>
            ) : camera ? (
              <LiveFeed camera={camera} timezone={timezone} />
            ) : (
              <div className="empty">
                <strong>No cameras configured</strong>
                Add a camera in <Link href="/settings#cameras">Settings</Link>.
              </div>
            )}
          </div>
        </section>

        <section className="panel" aria-labelledby="cameras-title">
          <div className="panel-head">
            <h2 id="cameras-title">Camera status</h2>
            {data && (
              <span className="sub small">
                {data.freshness.cameras_live} of {data.freshness.cameras_total} live
              </span>
            )}
          </div>
          {scopedCameras.length === 0 ? (
            <div className="empty">No cameras yet.</div>
          ) : (
            <ul className="camera-list">
              {scopedCameras.map((c) => (
                <li key={c.id}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="name">{c.name}</div>
                    <div className="meta">
                      {SOURCE_LABELS[c.source_type]} · last frame {formatAgo(c.runtime.last_frame_at)}
                      {c.runtime.status === 'live' && !c.line && c.counting_enabled && ' · counting line not set'}
                      {c.runtime.status !== 'live' && c.last_error && ` · ${c.last_error}`}
                    </div>
                  </div>
                  <CameraStatusBadge status={c.runtime.status} />
                </li>
              ))}
            </ul>
          )}
          {isOperator && (
            <>
              <div className="panel-head" style={{ borderTop: '1px solid var(--border)' }}>
                <h2>
                  Entries and exits by hour <span className="sub">· today</span>
                </h2>
              </div>
              <div className="panel-body">{data ? <HourlyChart data={data.today.hourly} currentHour={currentHour} /> : <p className="muted">Loading…</p>}</div>
            </>
          )}
        </section>
      </div>

      {isOperator && (
        <section className="panel" aria-labelledby="recent-title">
          <div className="panel-head">
            <h2 id="recent-title">Recent activity</h2>
            <Link href="/logs" className="btn btn-sm">
              All logs
            </Link>
          </div>
          <div className="panel-body flush">
            {!data ? (
              <p className="empty">Loading…</p>
            ) : data.recent_events.length === 0 ? (
              <div className="empty">
                <strong>No events recorded yet</strong>
                Entries and exits appear here once a camera is live and its counting line is set.
              </div>
            ) : (
              <EventsTable events={data.recent_events} timezone={timezone} onOpen={(e) => setOpenEvent(e.id)} compact />
            )}
          </div>
        </section>
      )}

      {openEvent && <EventDrawer eventId={openEvent} timezone={timezone} onClose={() => setOpenEvent(null)} onChanged={load} />}
      {occ && (
        <ReconcileDialog
          open={reconcileOpen}
          occupancy={occ}
          timezone={timezone}
          onClose={() => setReconcileOpen(false)}
          onDone={load}
        />
      )}
    </>
  );
}

function FreshnessLine({ data, timezone }: { data: Overview; timezone: string }) {
  const f = data.freshness;
  const stale = f.cameras_total > 0 && f.cameras_live === 0;
  return (
    <div className="freshness" aria-label="Data freshness">
      <span>
        Last event: {f.last_event_at ? formatDateTime(f.last_event_at, timezone) : 'none yet'}
      </span>
      {f.cameras_problem > 0 && (
        <span className="badge badge-warn">
          <TriangleAlert size={12} aria-hidden="true" /> {f.cameras_problem} camera(s) not delivering video
        </span>
      )}
      {stale && f.cameras_problem === 0 && <span className="badge">No camera live: figures are historical</span>}
      {f.pending_writes > 0 && <span className="badge badge-warn">{f.pending_writes} event(s) waiting to be saved</span>}
      {f.sync && (
        <span className={`badge ${f.sync.pending > 0 ? 'badge-warn' : 'badge-ok'}`} title={f.sync.last_error ?? undefined}>
          Cloud sync: {f.sync.pending > 0 ? `${f.sync.pending} pending` : 'up to date'}
        </span>
      )}
    </div>
  );
}

function Metric({ icon, label, value, foot, text }: { icon: React.ReactNode; label: string; value?: number; foot?: string; text?: string }) {
  return (
    <div className="metric">
      <div className="metric-label">
        <span aria-hidden="true">{icon}</span> {label}
      </div>
      <div className="metric-value">{text ?? value ?? '—'}</div>
      <div className="metric-foot">{foot ?? <span>&nbsp;</span>}</div>
    </div>
  );
}

function ReconcileDialog({
  open,
  occupancy,
  timezone,
  onClose,
  onDone,
}: {
  open: boolean;
  occupancy: Overview['occupancy'];
  timezone: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const parts = occupancy.locations;
  const [locId, setLocId] = useState<number | null>(parts.length === 1 ? parts[0].location_id : null);
  const target = parts.find((p) => p.location_id === locId) ?? null;
  const [mode, setMode] = useState<'set' | 'adjust'>('set');
  const [count, setCount] = useState('0');
  const [delta, setDelta] = useState('1');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      const first = parts.length === 1 ? parts[0].location_id : occupancy.location_id;
      setLocId(first);
      setReason('');
      setError(null);
    }
  }, [open, parts, occupancy.location_id]);

  useEffect(() => {
    if (target) setCount(String(target.count));
  }, [target]);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (mode === 'set') await api('/occupancy/reconcile', { method: 'POST', body: { location_id: locId, count: Number(count), reason } });
      else await api('/occupancy/adjust', { method: 'POST', body: { location_id: locId, delta: Number(delta), reason } });
      onDone();
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      title="Reconcile occupancy"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={save} disabled={busy || reason.trim().length < 3 || locId === null}>
            Save
          </button>
        </>
      }
    >
      <p className="muted small">
        Use after a head count, a restart or a camera outage. The change is recorded in the audit log.
        {target?.last_reconciled_at && ` Last head count: ${formatDateTime(target.last_reconciled_at, timezone)}.`}
      </p>
      {parts.length > 1 && (
        <div className="field">
          <label htmlFor="occ-loc">Location</label>
          <select id="occ-loc" className="select" value={locId ?? ''} onChange={(e) => setLocId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">Choose a location</option>
            {parts.map((p) => (
              <option key={p.location_id} value={p.location_id ?? ''}>
                {p.location_name} (now {p.count})
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="segmented" role="group" aria-label="Type of correction">
        <button type="button" aria-pressed={mode === 'set'} onClick={() => setMode('set')}>
          Set head count
        </button>
        <button type="button" aria-pressed={mode === 'adjust'} onClick={() => setMode('adjust')}>
          Adjust by
        </button>
      </div>
      {mode === 'set' ? (
        <div className="field">
          <label htmlFor="occ-count">People inside now</label>
          <input id="occ-count" className="input" type="number" min={0} max={10000} value={count} onChange={(e) => setCount(e.target.value)} />
        </div>
      ) : (
        <div className="field">
          <label htmlFor="occ-delta">Change (use a negative number to subtract)</label>
          <input id="occ-delta" className="input" type="number" min={-100} max={100} value={delta} onChange={(e) => setDelta(e.target.value)} />
        </div>
      )}
      <div className="field">
        <label htmlFor="occ-reason">Reason</label>
        <input id="occ-reason" className="input" value={reason} maxLength={500} placeholder="e.g. Closing head count by the store manager" onChange={(e) => setReason(e.target.value)} />
      </div>
      {error && (
        <div className="banner banner-err" role="alert" style={{ marginBottom: 0 }}>
          {error}
        </div>
      )}
    </Dialog>
  );
}
