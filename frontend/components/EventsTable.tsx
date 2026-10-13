'use client';

import { ImageOff } from 'lucide-react';
import { snapshotUrl } from '@/lib/api';
import { formatDate, formatTime } from '@/lib/format';
import type { SurveillanceEvent } from '@/lib/types';
import { EventTag, ReviewBadge } from './Status';

export function Snapshot({ event, className = 'thumb' }: { event: SurveillanceEvent; className?: string }) {
  if (!event.has_snapshot) {
    return (
      <span className={className} title={event.is_demo ? 'Demo records have no photos' : 'No snapshot stored'}>
        <ImageOff size={14} aria-hidden="true" />
        <span className="sr-only">No snapshot</span>
      </span>
    );
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img className={className} src={snapshotUrl(event.id)} alt={`Snapshot of ${event.person_label}`} loading="lazy" />;
}

export function EventsTable({
  events,
  timezone,
  onOpen,
  selectedId,
  compact = false,
}: {
  events: SurveillanceEvent[];
  timezone: string;
  onOpen?: (e: SurveillanceEvent) => void;
  selectedId?: string | null;
  compact?: boolean;
}) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Snapshot</th>
            <th scope="col">Person label</th>
            <th scope="col">Event</th>
            {!compact && <th scope="col">Date</th>}
            <th scope="col">Time</th>
            <th scope="col">Camera</th>
            <th scope="col">Review status</th>
            {onOpen && (
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr
              key={e.id}
              className={`${onOpen ? 'clickable' : ''} ${selectedId === e.id ? 'selected' : ''}`}
              onClick={onOpen ? () => onOpen(e) : undefined}
            >
              <td>
                <Snapshot event={e} />
              </td>
              <td className="nowrap" style={{ fontWeight: 600 }}>
                {e.person_label}
              </td>
              <td>
                <EventTag type={e.event_type} unmatched={e.match_status === 'unmatched'} />
              </td>
              {!compact && <td className="nowrap">{formatDate(e.occurred_at, timezone)}</td>}
              <td className="nowrap mono">{formatTime(e.occurred_at, timezone)}</td>
              <td>{e.camera_name ?? '—'}</td>
              <td>
                <ReviewBadge status={e.review_status} />
              </td>
              {onOpen && (
                <td style={{ textAlign: 'right' }}>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={(ev) => {
                      ev.stopPropagation();
                      onOpen(e);
                    }}
                    aria-label={`Open details for ${e.person_label} ${e.event_type}`}
                  >
                    Details
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
