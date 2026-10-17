import { CircleAlert, CircleCheck, CircleDot, CircleMinus, Info, OctagonAlert, TriangleAlert } from 'lucide-react';
import { ALERT_STATUS_LABELS, SEVERITY_LABELS } from '@/lib/format';
import type { AlertStatus, Severity } from '@/lib/types';

const SEVERITY_STYLE: Record<Severity, { tone: string; Icon: typeof Info }> = {
  critical: { tone: 'badge-err', Icon: OctagonAlert },
  high: { tone: 'badge-err', Icon: CircleAlert },
  medium: { tone: 'badge-warn', Icon: TriangleAlert },
  low: { tone: 'badge-info', Icon: Info },
  info: { tone: '', Icon: Info },
};

/** Severity always carries an icon and a word, never colour alone. */
export function SeverityBadge({ severity }: { severity: Severity }) {
  const { tone, Icon } = SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.info;
  return (
    <span className={`badge ${tone}`}>
      <Icon size={12} aria-hidden="true" />
      {SEVERITY_LABELS[severity] ?? severity}
    </span>
  );
}

const STATUS_STYLE: Record<AlertStatus, { tone: string; Icon: typeof Info }> = {
  new: { tone: 'badge-warn', Icon: CircleDot },
  acknowledged: { tone: 'badge-info', Icon: CircleDot },
  resolved: { tone: 'badge-ok', Icon: CircleCheck },
  dismissed: { tone: '', Icon: CircleMinus },
};

export function AlertStatusBadge({ status }: { status: AlertStatus }) {
  const { tone, Icon } = STATUS_STYLE[status] ?? STATUS_STYLE.new;
  return (
    <span className={`badge ${tone}`}>
      <Icon size={12} aria-hidden="true" />
      {ALERT_STATUS_LABELS[status] ?? status}
    </span>
  );
}
