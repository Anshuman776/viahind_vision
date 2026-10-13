import { ArrowDownToLine, ArrowUpFromLine, CircleHelp } from 'lucide-react';
import { EVENT_LABELS, REVIEW_LABELS } from '@/lib/format';
import type { CameraStatus, EventType, ReviewStatus } from '@/lib/types';

const CAMERA_STATUS: Record<CameraStatus, { label: string; tone: string }> = {
  live: { label: 'Live', tone: 'badge-ok' },
  connecting: { label: 'Connecting', tone: 'badge-info' },
  disconnected: { label: 'Disconnected', tone: 'badge-warn' },
  error: { label: 'Error', tone: 'badge-err' },
  stopped: { label: 'Stopped', tone: '' },
  ended: { label: 'Clip ended', tone: '' },
};

export function CameraStatusBadge({ status }: { status: CameraStatus }) {
  const s = CAMERA_STATUS[status] ?? CAMERA_STATUS.stopped;
  return (
    <span className={`badge ${s.tone}`}>
      <span className="dot" aria-hidden="true" />
      {s.label}
    </span>
  );
}

const REVIEW_TONE: Record<ReviewStatus, string> = {
  auto: '',
  needs_review: 'badge-warn',
  confirmed: 'badge-ok',
  corrected: 'badge-info',
  rejected: 'badge-err',
};

export function ReviewBadge({ status }: { status: ReviewStatus }) {
  return <span className={`badge ${REVIEW_TONE[status]}`}>{REVIEW_LABELS[status] ?? status}</span>;
}

export function EventTag({ type, unmatched }: { type: EventType; unmatched?: boolean }) {
  const Icon = type === 'entry' ? ArrowDownToLine : type === 'exit' ? ArrowUpFromLine : CircleHelp;
  return (
    <span className={`event-tag event-${type}`}>
      <Icon size={14} aria-hidden="true" />
      {EVENT_LABELS[type]}
      {unmatched && (
        <span className="badge small" title="No reliable link to an entry; an operator can link it to a visit.">
          Unmatched
        </span>
      )}
    </span>
  );
}
