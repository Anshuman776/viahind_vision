'use client';

import { useCallback, useEffect, useState } from 'react';
import { Check, Flag, Link2, Unlink, X, XCircle } from 'lucide-react';
import { api, snapshotUrl } from '@/lib/api';
import { EVENT_LABELS, UNCERTAIN_REASONS, formatDateTime, formatDuration } from '@/lib/format';
import type { EventDetail, EventType, Page, Visit } from '@/lib/types';
import { EventTag, ReviewBadge } from './Status';
import { useSession } from './SessionProvider';

const ACTION_LABELS: Record<string, string> = {
  'event.update': 'Updated',
  'event.linked_to_visit': 'Linked to visit',
  'event.unlink_exit': 'Unlinked from visit',
};

export function EventDrawer({
  eventId,
  timezone,
  onClose,
  onChanged,
}: {
  eventId: string;
  timezone: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState('');
  const [openVisits, setOpenVisits] = useState<Visit[] | null>(null);
  const [linkVisitId, setLinkVisitId] = useState('');
  const { isAdmin } = useSession();

  const load = useCallback(async () => {
    setError(null);
    try {
      const d = await api<EventDetail>(`/events/${eventId}`);
      setDetail(d);
      setNotes(d.notes ?? '');
    } catch (err) {
      setError((err as Error).message);
    }
  }, [eventId]);

  useEffect(() => {
    setDetail(null);
    setOpenVisits(null);
    setLinkVisitId('');
    load();
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const canLink = detail?.event_type === 'exit' && detail.match_status === 'unmatched' && detail.review_status !== 'rejected';
  useEffect(() => {
    if (!canLink) return;
    api<Page<Visit>>('/visits?status=inside&page_size=100')
      .then((p) =>
        setOpenVisits(p.items.filter((v) => v.entry_at && detail && Date.parse(v.entry_at) <= Date.parse(detail.occurred_at))),
      )
      .catch(() => setOpenVisits([]));
  }, [canLink, detail]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const patch = (body: Record<string, unknown>) => run(() => api(`/events/${eventId}`, { method: 'PATCH', body }));

  const visit = detail?.visit;
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="event-drawer-title">
        <div className="drawer-head">
          <h2 id="event-drawer-title">{detail ? `${detail.person_label} — ${EVENT_LABELS[detail.event_type]}` : 'Event details'}</h2>
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
              {detail.has_snapshot ? (
                <div style={{ display: 'grid', gap: 6 }}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img className="snapshot-large" src={snapshotUrl(detail.id)} alt={`Snapshot of ${detail.person_label} at ${detail.event_type}`} />
                  {isAdmin && (
                    <button
                      type="button"
                      className="btn btn-sm btn-danger"
                      style={{ justifySelf: 'start' }}
                      disabled={busy}
                      onClick={() => window.confirm('Permanently delete this image? The event record is kept and the deletion is audited.') && run(() => api(`/events/${eventId}/snapshot`, { method: 'DELETE' }))}
                    >
                      Delete image
                    </button>
                  )}
                </div>
              ) : (
                <div className="snapshot-missing">
                  {detail.snapshot_status === 'purged'
                    ? 'Snapshot deleted by the retention policy.'
                    : detail.snapshot_status === 'skipped_low_storage'
                      ? 'Snapshot not saved: the server was low on disk space.'
                      : detail.snapshot_status === 'skipped_storage_limit'
                        ? 'Snapshot not saved: the evidence storage limit was reached (Settings, Evidence).'
                        : detail.snapshot_status === 'deleted'
                          ? 'Snapshot deleted by an administrator.'
                      : detail.snapshot_status === 'failed'
                        ? 'Snapshot could not be written to storage.'
                        : detail.is_demo
                          ? 'Demo records have no photos.'
                          : 'No snapshot was captured for this event.'}
                </div>
              )}

              {detail.event_type === 'uncertain' && (
                <div className="banner banner-warn" role="note">
                  {UNCERTAIN_REASONS[detail.uncertain_reason ?? ''] ?? 'Direction could not be determined reliably.'} Review the
                  snapshot and set the correct event type.
                </div>
              )}

              <dl className="kv">
                <dt>Event</dt>
                <dd>
                  <EventTag type={detail.event_type} />
                  {detail.original_event_type !== detail.event_type && (
                    <span className="muted small"> (recorded as {EVENT_LABELS[detail.original_event_type]})</span>
                  )}
                </dd>
                <dt>Time</dt>
                <dd>{formatDateTime(detail.occurred_at, timezone)}</dd>
                <dt>Camera</dt>
                <dd>{detail.camera_name ?? 'Deleted camera'}</dd>
                <dt>Confidence</dt>
                <dd>{detail.confidence !== null ? `${Math.round(detail.confidence * 100)}%` : '—'}</dd>
                <dt>Review</dt>
                <dd>
                  <ReviewBadge status={detail.review_status} />
                </dd>
                <dt>Event ID</dt>
                <dd className="mono small">{detail.id}</dd>
              </dl>

              <section>
                <p className="section-title">Visit</p>
                {visit ? (
                  <dl className="kv">
                    <dt>Label</dt>
                    <dd>{visit.person_label}</dd>
                    <dt>Entry</dt>
                    <dd>{visit.entry_at ? formatDateTime(visit.entry_at, timezone) : '—'}</dd>
                    <dt>Exit</dt>
                    <dd>{visit.exit_at ? formatDateTime(visit.exit_at, timezone) : 'Still inside'}</dd>
                    <dt>Duration</dt>
                    <dd>{formatDuration(visit.duration_seconds)}</dd>
                    <dt>Linked by</dt>
                    <dd>
                      {visit.match_method === 'tracker'
                        ? 'Continuous tracking on the same camera'
                        : visit.match_method === 'manual'
                          ? 'Operator'
                          : visit.exit_at
                            ? '—'
                            : 'Not yet exited'}
                    </dd>
                    <dt>Status</dt>
                    <dd style={{ textTransform: 'capitalize' }}>{visit.status.replace('_', ' ')}</dd>
                  </dl>
                ) : detail.event_type === 'exit' ? (
                  <p className="muted">
                    Unmatched exit: this person could not be linked to an entry automatically. Durations are only shown for reliably
                    linked visits.
                  </p>
                ) : (
                  <p className="muted">No visit is associated with this event.</p>
                )}
                {canLink && (
                  <div className="form-actions">
                    <select className="select" value={linkVisitId} onChange={(e) => setLinkVisitId(e.target.value)} aria-label="Open visit to link">
                      <option value="">Link to an open visit…</option>
                      {(openVisits ?? []).map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.person_label} — entered {v.entry_at ? formatDateTime(v.entry_at, timezone) : ''}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="btn"
                      disabled={!linkVisitId || busy}
                      onClick={() => run(() => api(`/visits/${linkVisitId}/link-exit`, { method: 'POST', body: { event_id: detail.id } }))}
                    >
                      <Link2 size={14} /> Link
                    </button>
                    {openVisits?.length === 0 && <span className="muted small">No open visits before this exit.</span>}
                  </div>
                )}
                {detail.event_type === 'exit' && visit?.match_method === 'manual' && (
                  <div className="form-actions">
                    <button type="button" className="btn btn-sm" disabled={busy} onClick={() => run(() => api(`/events/${detail.id}/unlink`, { method: 'POST' }))}>
                      <Unlink size={14} /> Unlink from visit
                    </button>
                  </div>
                )}
              </section>

              <section>
                <p className="section-title">Review</p>
                <div className="control-row">
                  <button type="button" className="btn" disabled={busy || detail.review_status === 'confirmed'} onClick={() => patch({ review_status: 'confirmed' })}>
                    <Check size={14} /> Confirm
                  </button>
                  <button type="button" className="btn" disabled={busy || detail.review_status === 'needs_review'} onClick={() => patch({ review_status: 'needs_review' })}>
                    <Flag size={14} /> Mark for review
                  </button>
                  {detail.review_status === 'rejected' ? (
                    <button type="button" className="btn" disabled={busy} onClick={() => patch({ review_status: 'confirmed' })}>
                      Restore
                    </button>
                  ) : (
                    <button type="button" className="btn btn-danger" disabled={busy} onClick={() => patch({ review_status: 'rejected' })} title="Not a real person crossing (false detection)">
                      <XCircle size={14} /> Reject
                    </button>
                  )}
                </div>
                <div className="form-actions">
                  <label className="field-label" htmlFor="correct-type">
                    Correct event type
                  </label>
                  <select
                    id="correct-type"
                    className="select"
                    value={detail.event_type}
                    disabled={busy || detail.review_status === 'rejected'}
                    onChange={(e) => patch({ event_type: e.target.value as EventType })}
                  >
                    <option value="entry">Entry</option>
                    <option value="exit">Exit</option>
                    <option value="uncertain">Uncertain</option>
                  </select>
                </div>
                <div className="field" style={{ marginTop: 12 }}>
                  <label htmlFor="event-notes">Operator notes</label>
                  <textarea id="event-notes" className="textarea" value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} />
                  <div>
                    <button type="button" className="btn btn-sm" disabled={busy || notes === (detail.notes ?? '')} onClick={() => patch({ notes })}>
                      Save notes
                    </button>
                  </div>
                </div>
              </section>

              <section>
                <p className="section-title">Audit trail</p>
                {detail.audit.length === 0 ? (
                  <p className="muted small">No changes recorded.</p>
                ) : (
                  <ul className="audit-list">
                    {detail.audit.map((a) => (
                      <li key={a.id}>
                        <strong>{ACTION_LABELS[a.action] ?? a.action}</strong> by {a.username} · {formatDateTime(a.occurred_at, timezone)}
                        <AuditDetails details={a.details} />
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </div>
      </aside>
    </>
  );
}

function AuditDetails({ details }: { details: Record<string, unknown> }) {
  const before = details.before as Record<string, unknown> | undefined;
  const after = details.after as Record<string, unknown> | undefined;
  if (!before || !after) return null;
  const changed = Object.keys(after).filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]) && k !== 'visit_id');
  if (changed.length === 0) return null;
  return (
    <div className="muted">
      {changed.map((k) => (
        <div key={k}>
          {k.replace(/_/g, ' ')}: {String(before[k] ?? '—')} → {String(after[k] ?? '—')}
        </div>
      ))}
    </div>
  );
}
