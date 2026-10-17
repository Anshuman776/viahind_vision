'use client';

import { useCallback, useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, CircleAlert, ShieldCheck } from 'lucide-react';
import { api, queryString, snapshotUrl } from '@/lib/api';
import { EVENT_LABELS, formatDateTime, siteToday } from '@/lib/format';
import type { Page, SurveillanceEvent } from '@/lib/types';
import { useSystem } from '@/components/SystemProvider';
import { EventTag, ReviewBadge } from '@/components/Status';
import { EventDrawer } from '@/components/EventDrawer';

const PAGE_SIZE = 24;

/** Searchable gallery of event snapshots (one crop per recorded crossing; never continuous video). */
export default function EvidenceView() {
  const { timezone, cameras, dataVersion, locationId, settings } = useSystem();
  const today = siteToday(timezone);
  const [from, setFrom] = useState(today);
  const [to, setTo] = useState(today);
  const [eventType, setEventType] = useState('');
  const [cameraId, setCameraId] = useState('');
  const [label, setLabel] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Page<SurveillanceEvent> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openEvent, setOpenEvent] = useState<string | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setQ(label.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(t);
  }, [label]);

  const load = useCallback(async () => {
    try {
      const params = { with_snapshot: 'true', date_from: from, date_to: to, event_type: eventType, camera_id: cameraId, q, location_id: locationId, page, page_size: PAGE_SIZE };
      setData(await api<Page<SurveillanceEvent>>(`/events${queryString(params)}`));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [from, to, eventType, cameraId, q, locationId, page]);

  useEffect(() => {
    load();
  }, [load, dataVersion]);

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const set = (setter: (v: string) => void) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setter(e.target.value);
    setPage(1);
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Event evidence</h1>
          <p>Snapshots saved at recorded entries and exits. Access is logged in the audit trail where images are changed or deleted.</p>
        </div>
      </div>

      <div className="banner banner-info" role="note">
        <ShieldCheck size={16} />
        <span>
          Labels such as “Unknown Person 07” are temporary tracking labels. They do not identify anyone and restart when a camera
          reconnects. Images are kept for {settings?.site.snapshot_retention_days ?? '—'} day(s), then deleted automatically.
        </span>
      </div>

      {error && (
        <div className="banner banner-err" role="alert">
          <CircleAlert size={16} /> {error}
        </div>
      )}

      <section className="panel">
        <div className="filters">
          <div className="field">
            <label htmlFor="ev-from">From</label>
            <input id="ev-from" className="input" type="date" value={from} max={to} onChange={set(setFrom)} />
          </div>
          <div className="field">
            <label htmlFor="ev-to">To</label>
            <input id="ev-to" className="input" type="date" value={to} min={from} onChange={set(setTo)} />
          </div>
          <div className="field">
            <label htmlFor="ev-type">Event</label>
            <select id="ev-type" className="select" value={eventType} onChange={set(setEventType)}>
              <option value="">All</option>
              <option value="entry">Entry</option>
              <option value="exit">Exit</option>
              <option value="uncertain">Uncertain</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="ev-cam">Camera</label>
            <select id="ev-cam" className="select" value={cameraId} onChange={set(setCameraId)}>
              <option value="">All</option>
              {cameras
                .filter((c) => locationId === null || c.location_id === locationId)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="ev-label">Label</label>
            <input id="ev-label" className="input" placeholder="Unknown Person 07" value={label} maxLength={64} onChange={(e) => setLabel(e.target.value)} />
          </div>
        </div>

        {!data ? (
          <p className="empty">Loading…</p>
        ) : data.items.length === 0 ? (
          <div className="empty">
            <strong>No snapshots for these filters</strong>
            Snapshots are saved only when an entry or exit is recorded, and are removed after the retention period.
          </div>
        ) : (
          <ul className="gallery">
            {data.items.map((e) => (
              <li key={e.id}>
                <button type="button" className="gallery-card" onClick={() => setOpenEvent(e.id)} aria-label={`${e.person_label}, ${EVENT_LABELS[e.event_type]}, ${formatDateTime(e.occurred_at, timezone)}`}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={snapshotUrl(e.id)} alt="" loading="lazy" />
                  <div className="gallery-meta">
                    <div className="control-row" style={{ justifyContent: 'space-between' }}>
                      <EventTag type={e.event_type} />
                      {e.review_status !== 'auto' && <ReviewBadge status={e.review_status} />}
                    </div>
                    <div className="small" style={{ fontWeight: 600 }}>{e.person_label}</div>
                    <div className="small muted">
                      {formatDateTime(e.occurred_at, timezone)}
                      {e.camera_name && ` · ${e.camera_name}`}
                    </div>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
        {data && data.total > PAGE_SIZE && (
          <div className="pagination">
            <span>{data.total} snapshots</span>
            <div className="control-row">
              <button type="button" className="btn btn-sm" onClick={() => setPage((p) => p - 1)} disabled={page <= 1} aria-label="Previous page">
                <ChevronLeft size={14} />
              </button>
              <span>
                Page {page} of {pages}
              </span>
              <button type="button" className="btn btn-sm" onClick={() => setPage((p) => p + 1)} disabled={page >= pages} aria-label="Next page">
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </section>

      {openEvent && <EventDrawer eventId={openEvent} timezone={timezone} onClose={() => setOpenEvent(null)} onChanged={load} />}
    </>
  );
}
