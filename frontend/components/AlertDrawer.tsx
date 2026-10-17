'use client';

import { useCallback, useEffect, useState } from 'react';
import { Check, CircleCheck, RotateCcw, X, XCircle } from 'lucide-react';
import { api } from '@/lib/api';
import { CATEGORY_LABELS, formatDateTime } from '@/lib/format';
import type { AlertDetail } from '@/lib/types';
import { AlertStatusBadge, SeverityBadge } from './AlertBadges';

const ACTION_LABELS: Record<string, string> = {
  'alert.acknowledge': 'Acknowledged',
  'alert.resolve': 'Resolved',
  'alert.dismiss': 'Dismissed',
  'alert.reopen': 'Reopened',
};

function metricLabel(key: string): string {
  return key.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
}

function metricValue(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v === 'object') return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${metricLabel(k)}: ${String(x)}`).join(', ');
  return String(v);
}

export const alertSnapshotUrl = (id: string) => `/api/v1/alerts/${encodeURIComponent(id)}/snapshot`;

export function AlertDrawer({ alertId, timezone, onClose, onChanged }: { alertId: string; timezone: string; onClose: () => void; onChanged: () => void }) {
  const [detail, setDetail] = useState<AlertDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');

  const load = useCallback(async () => {
    setError(null);
    try {
      const d = await api<AlertDetail>(`/alerts/${encodeURIComponent(alertId)}`);
      setDetail(d);
      setNote(d.resolution_note ?? '');
    } catch (err) {
      setError((err as Error).message);
    }
  }, [alertId]);

  useEffect(() => {
    setDetail(null);
    load();
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const act = async (action: 'acknowledge' | 'resolve' | 'dismiss' | 'reopen') => {
    setBusy(true);
    setError(null);
    try {
      await api(`/alerts/${encodeURIComponent(alertId)}/actions`, { method: 'POST', body: { action, note: note.trim() || null } });
      await load();
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const open = detail && (detail.status === 'new' || detail.status === 'acknowledged');
  const metrics = detail ? Object.entries(detail.metrics) : [];

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="alert-drawer-title">
        <div className="drawer-head">
          <h2 id="alert-drawer-title">{detail ? detail.title : 'Alert details'}</h2>
          <button type="button" className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close details" autoFocus>
            <X size={18} />
          </button>
        </div>
        <div className="drawer-body">
          {error && (
            <div className="banner banner-err" role="alert">
              {error}
            </div>
          )}
          {!detail && !error && <p className="muted">Loading…</p>}
          {detail && (
            <>
              <div className="control-row">
                <SeverityBadge severity={detail.severity} />
                <AlertStatusBadge status={detail.status} />
                <span className="badge">{CATEGORY_LABELS[detail.category] ?? detail.category}</span>
                {detail.occurrences > 1 && <span className="badge">{detail.occurrences} occurrences</span>}
              </div>

              <div>
                <p className="section-title">Why this alert was raised</p>
                <p>{detail.reason}</p>
              </div>

              {detail.has_snapshot ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img className="snapshot-large" src={alertSnapshotUrl(detail.id)} alt={`Evidence snapshot for ${detail.title}`} />
              ) : detail.snapshot_status !== 'none' ? (
                <div className="snapshot-missing">
                  {detail.snapshot_status === 'purged' ? 'Snapshot deleted by the retention policy.' : 'No snapshot could be saved for this alert.'}
                </div>
              ) : null}

              <dl className="kv">
                <dt>Location</dt>
                <dd>{detail.location_name ?? '—'}</dd>
                <dt>Camera</dt>
                <dd>{detail.camera_name ?? '—'}</dd>
                {detail.zone_name && (
                  <>
                    <dt>Zone</dt>
                    <dd>{detail.zone_name}</dd>
                  </>
                )}
                {detail.track_label && (
                  <>
                    <dt>Person label</dt>
                    <dd>
                      {detail.track_label} <span className="muted small">(temporary tracking label, not an identity)</span>
                    </dd>
                  </>
                )}
                <dt>First seen</dt>
                <dd>{formatDateTime(detail.first_seen_at, timezone)}</dd>
                <dt>Last seen</dt>
                <dd>{formatDateTime(detail.last_seen_at, timezone)}</dd>
                {detail.model_score !== null && (
                  <>
                    <dt>Model score</dt>
                    <dd>{detail.model_score.toFixed(3)}</dd>
                  </>
                )}
                <dt>Alert ID</dt>
                <dd className="mono small">{detail.id}</dd>
              </dl>

              {metrics.length > 0 && (
                <div>
                  <p className="section-title">Measured values</p>
                  <dl className="kv">
                    {metrics.map(([k, v]) => (
                      <div key={k} style={{ display: 'contents' }}>
                        <dt>{metricLabel(k)}</dt>
                        <dd>{metricValue(v)}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}

              <p className="small muted">
                Alerts describe measured conditions for a person to review. They do not identify anyone, and must not be
                treated as proof of wrongdoing.
              </p>

              <div className="field">
                <label htmlFor="alert-note">Review note</label>
                <textarea id="alert-note" className="textarea" maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What did you find? (optional)" />
              </div>
              <div className="control-row">
                {detail.status === 'new' && (
                  <button type="button" className="btn" onClick={() => act('acknowledge')} disabled={busy}>
                    <Check size={14} /> Acknowledge
                  </button>
                )}
                {open && (
                  <>
                    <button type="button" className="btn btn-primary" onClick={() => act('resolve')} disabled={busy}>
                      <CircleCheck size={14} /> Resolve
                    </button>
                    <button type="button" className="btn" onClick={() => act('dismiss')} disabled={busy} title="Not a real issue (false positive)">
                      <XCircle size={14} /> Dismiss
                    </button>
                  </>
                )}
                {!open && (
                  <button type="button" className="btn" onClick={() => act('reopen')} disabled={busy}>
                    <RotateCcw size={14} /> Reopen
                  </button>
                )}
              </div>
              {detail.resolved_by && (
                <p className="small muted">
                  {detail.status === 'dismissed' ? 'Dismissed' : 'Resolved'} by {detail.resolved_by}
                  {detail.resolved_at && ` on ${formatDateTime(detail.resolved_at, timezone)}`}.
                </p>
              )}

              {detail.deliveries.length > 0 && (
                <div>
                  <p className="section-title">Notifications</p>
                  <ul className="audit-list">
                    {detail.deliveries.map((d) => (
                      <li key={d.id}>
                        {d.status === 'sent' ? 'Sent' : d.status === 'pending' ? 'Pending' : d.status === 'failed' ? 'Failed' : 'Suppressed'} · channel {d.channel_id}
                        {d.attempts > 1 && ` · ${d.attempts} attempts`}
                        {d.last_error && <span className="muted"> · {d.last_error}</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {detail.audit.length > 0 && (
                <div>
                  <p className="section-title">History</p>
                  <ul className="audit-list">
                    {detail.audit.map((a) => (
                      <li key={a.id}>
                        <strong>{ACTION_LABELS[a.action] ?? a.action}</strong> by {a.username} · {formatDateTime(a.occurred_at, timezone)}
                        {typeof a.details.note === 'string' && a.details.note && <div className="muted">“{a.details.note}”</div>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </aside>
    </>
  );
}
