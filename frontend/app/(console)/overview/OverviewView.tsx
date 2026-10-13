'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowDownToLine, ArrowUpFromLine, TriangleAlert, UserRound, UsersRound } from 'lucide-react';
import { api } from '@/lib/api';
import { formatAgo, formatDateTime, SOURCE_LABELS } from '@/lib/format';
import type { Overview } from '@/lib/types';
import { useSystem } from '@/components/SystemProvider';
import { CameraStatusBadge } from '@/components/Status';
import { LiveFeed } from '@/components/LiveFeed';
import { HourlyChart } from '@/components/HourlyChart';
import { EventsTable } from '@/components/EventsTable';
import { EventDrawer } from '@/components/EventDrawer';
import { Dialog } from '@/components/Dialog';

export default function OverviewView() {
  const { timezone, cameras, selectedCameraId, dataVersion } = useSystem();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openEvent, setOpenEvent] = useState<string | null>(null);
  const [reconcileOpen, setReconcileOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api<Overview>('/overview'));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, dataVersion]);

  useEffect(() => {
    const t = window.setInterval(load, 30000); // also picks up the date change at midnight
    return () => window.clearInterval(t);
  }, [load]);

  const camera = cameras.find((c) => c.id === selectedCameraId) ?? cameras[0];
  const occ = data?.occupancy;
  const currentHour = Number(new Intl.DateTimeFormat('en-GB', { hour: '2-digit', hour12: false, timeZone: timezone }).format(new Date())) % 24;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Overview</h1>
          <p>Today at the entrance, from recorded events{data ? ` · ${data.today.timezone}` : ''}.</p>
        </div>
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
            <UsersRound size={15} aria-hidden="true" /> People currently inside
          </div>
          <div className="metric-value">{occ ? occ.count : '—'}</div>
          <div className="metric-foot">
            {occ?.estimated ? (
              <span className="badge badge-warn" title={occ.reasons.join(' ')}>
                <TriangleAlert size={12} aria-hidden="true" /> Estimated
              </span>
            ) : occ ? (
              <span>{occ.last_reconciled_at ? `Head count ${formatAgo(Date.parse(occ.last_reconciled_at) / 1000)}` : 'From entries and exits'}</span>
            ) : null}
            {occ && (
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => setReconcileOpen(true)} style={{ height: 22 }}>
                Reconcile
              </button>
            )}
          </div>
        </div>
        <Metric icon={<ArrowDownToLine size={15} />} label="Total entries today" value={data?.today.entries} />
        <Metric icon={<ArrowUpFromLine size={15} />} label="Total exits today" value={data?.today.exits} />
        <Metric
          icon={<UserRound size={15} />}
          label="Unknown visitors today"
          value={data?.today.unknown_visitors}
          foot={data && data.today.uncertain > 0 ? `${data.today.uncertain} uncertain event(s)` : undefined}
        />
      </section>

      {occ?.estimated && (
        <div className="banner banner-warn" role="status">
          <TriangleAlert size={16} />
          <div>
            <strong>Occupancy is an estimate.</strong> {occ.reasons.join(' ')}
          </div>
          <div className="banner-actions">
            <button type="button" className="btn btn-sm" onClick={() => setReconcileOpen(true)}>
              Reconcile with head count
            </button>
          </div>
        </div>
      )}

      <div className="overview-grid">
        <section className="panel" aria-labelledby="preview-title">
          <div className="panel-head">
            <h2 id="preview-title">
              Live preview {camera && <span className="sub">· {camera.name}</span>}
            </h2>
            <Link href="/live" className="btn btn-sm">
              Open Live Camera
            </Link>
          </div>
          <div className="panel-body">
            {camera ? (
              <LiveFeed camera={camera} timezone={timezone} />
            ) : (
              <div className="empty">
                <strong>No cameras configured</strong>
                Add the entrance camera in <Link href="/settings#cameras">Settings</Link>.
              </div>
            )}
          </div>
        </section>

        <section className="panel" aria-labelledby="cameras-title">
          <div className="panel-head">
            <h2 id="cameras-title">Camera connection</h2>
          </div>
          {cameras.length === 0 ? (
            <div className="empty">No cameras yet.</div>
          ) : (
            <ul className="camera-list">
              {cameras.map((c) => (
                <li key={c.id}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="name">{c.name}</div>
                    <div className="meta">
                      {SOURCE_LABELS[c.source_type]} · last frame {formatAgo(c.runtime.last_frame_at)}
                      {c.runtime.status === 'live' && !c.line && ' · entrance line not set'}
                    </div>
                  </div>
                  <CameraStatusBadge status={c.runtime.status} />
                </li>
              ))}
            </ul>
          )}
          <div className="panel-head" style={{ borderTop: '1px solid var(--border)' }}>
            <h2>
              Entries and exits by hour <span className="sub">· today</span>
            </h2>
          </div>
          <div className="panel-body">{data ? <HourlyChart data={data.today.hourly} currentHour={currentHour} /> : <p className="muted">Loading…</p>}</div>
        </section>
      </div>

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
              Entries and exits appear here once a camera is live and the entrance line is set.
            </div>
          ) : (
            <EventsTable events={data.recent_events} timezone={timezone} onOpen={(e) => setOpenEvent(e.id)} compact />
          )}
        </div>
      </section>

      {openEvent && <EventDrawer eventId={openEvent} timezone={timezone} onClose={() => setOpenEvent(null)} onChanged={load} />}
      {occ && <ReconcileDialog open={reconcileOpen} current={occ.count} timezone={timezone} lastAt={occ.last_reconciled_at} onClose={() => setReconcileOpen(false)} onDone={load} />}
    </>
  );
}

function Metric({ icon, label, value, foot }: { icon: React.ReactNode; label: string; value?: number; foot?: string }) {
  return (
    <div className="metric">
      <div className="metric-label">
        <span aria-hidden="true">{icon}</span> {label}
      </div>
      <div className="metric-value">{value ?? '—'}</div>
      <div className="metric-foot">{foot ?? <span>&nbsp;</span>}</div>
    </div>
  );
}

function ReconcileDialog({
  open,
  current,
  lastAt,
  timezone,
  onClose,
  onDone,
}: {
  open: boolean;
  current: number;
  lastAt: string | null;
  timezone: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const [mode, setMode] = useState<'set' | 'adjust'>('set');
  const [count, setCount] = useState(String(current));
  const [delta, setDelta] = useState('1');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setCount(String(current));
      setReason('');
      setError(null);
    }
  }, [open, current]);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (mode === 'set') await api('/occupancy/reconcile', { method: 'POST', body: { count: Number(count), reason } });
      else await api('/occupancy/adjust', { method: 'POST', body: { delta: Number(delta), reason } });
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
          <button type="button" className="btn btn-primary" onClick={save} disabled={busy || reason.trim().length < 3}>
            Save
          </button>
        </>
      }
    >
      <p className="muted small">
        Use after a head count, a restart or a camera outage. The change is recorded in the audit log.
        {lastAt && ` Last head count: ${formatDateTime(lastAt, timezone)}.`}
      </p>
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
        <input id="occ-reason" className="input" value={reason} maxLength={500} placeholder="e.g. Night roll call by warden" onChange={(e) => setReason(e.target.value)} />
      </div>
      {error && (
        <div className="banner banner-err" role="alert" style={{ marginBottom: 0 }}>
          {error}
        </div>
      )}
    </Dialog>
  );
}
