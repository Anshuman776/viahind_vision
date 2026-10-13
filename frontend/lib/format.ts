/** Display helpers. All times are shown in the site's configured timezone. */

const cache = new Map<string, Intl.DateTimeFormat>();

function formatter(timeZone: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = timeZone + JSON.stringify(options);
  let f = cache.get(key);
  if (!f) {
    try {
      f = new Intl.DateTimeFormat('en-IN', { timeZone, ...options });
    } catch {
      f = new Intl.DateTimeFormat('en-IN', { timeZone: 'UTC', ...options });
    }
    cache.set(key, f);
  }
  return f;
}

export function toDate(value: string | number | Date): Date {
  if (value instanceof Date) return value;
  return typeof value === 'number' ? new Date(value * 1000) : new Date(value);
}

export function formatTime(value: string | number | Date, timeZone: string, seconds = true): string {
  return formatter(timeZone, { hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}), hour12: true })
    .format(toDate(value))
    .toUpperCase();
}

export function formatDate(value: string | number | Date, timeZone: string): string {
  return formatter(timeZone, { day: '2-digit', month: 'short', year: 'numeric' }).format(toDate(value));
}

export function formatDateTime(value: string | number | Date, timeZone: string): string {
  return `${formatDate(value, timeZone)}, ${formatTime(value, timeZone)}`;
}

/** YYYY-MM-DD of "now" in the site timezone (for date filters). */
export function siteToday(timeZone: string, now: Date = new Date()): string {
  const parts = formatter(timeZone, { year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? '';
  return `${get('year')}-${get('month')}-${get('day')}`;
}

export function formatDuration(totalSeconds: number | null | undefined): string {
  if (totalSeconds === null || totalSeconds === undefined) return '—';
  const s = Math.max(0, Math.round(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h} h ${m} min`;
  if (m > 0) return `${m} min`;
  return `${s} s`;
}

export function formatAgo(unixSeconds: number | null | undefined, now: number = Date.now() / 1000): string {
  if (!unixSeconds) return 'never';
  const d = Math.max(0, now - unixSeconds);
  if (d < 2) return 'just now';
  if (d < 60) return `${Math.floor(d)} s ago`;
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  return `${Math.floor(d / 3600)} h ago`;
}

export const EVENT_LABELS: Record<string, string> = { entry: 'Entry', exit: 'Exit', uncertain: 'Uncertain' };

export const REVIEW_LABELS: Record<string, string> = {
  auto: 'Not reviewed',
  needs_review: 'Needs review',
  confirmed: 'Confirmed',
  corrected: 'Corrected',
  rejected: 'Rejected',
};

export const UNCERTAIN_REASONS: Record<string, string> = {
  lost_while_crossing: 'Person was lost from view while crossing the line',
  direction_reversal: 'Direction reversed immediately after a crossing',
};

export const SOURCE_LABELS: Record<string, string> = {
  browser: 'Browser camera',
  device: 'USB camera on server',
  network: 'IP / CCTV (RTSP or HTTP)',
  file: 'Test clip',
};
