export interface LogFilters {
  range: 'today' | 'custom' | 'all';
  from: string;
  to: string;
  eventType: string;
  cameraId: string;
  q: string;
  review: string;
}

/** Filter state -> backend query parameters (dates are site-local calendar days). */
export function filterParams(f: LogFilters, today: string): Record<string, string> {
  const params: Record<string, string> = {};
  if (f.range === 'today') {
    params.date_from = today;
    params.date_to = today;
  } else if (f.range === 'custom') {
    if (f.from) params.date_from = f.from;
    if (f.to) params.date_to = f.to;
  }
  if (f.eventType) params.event_type = f.eventType;
  if (f.cameraId) params.camera_id = f.cameraId;
  if (f.q.trim()) params.q = f.q.trim();
  if (f.review) params.review_status = f.review;
  return params;
}
