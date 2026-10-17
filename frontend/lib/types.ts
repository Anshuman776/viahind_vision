export type Role = 'admin' | 'operator' | 'viewer';

export interface User {
  id: number;
  username: string;
  role: Role;
  email?: string | null;
  organization_id?: number;
  organization?: { id: number; name: string; plan: string; max_cameras: number | null };
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export type CameraStatus = 'stopped' | 'connecting' | 'live' | 'disconnected' | 'error' | 'ended';
export type DetectionStatus = 'off' | 'unavailable' | 'loading' | 'active' | 'no_line' | 'error';
export type SourceType = 'browser' | 'device' | 'network' | 'file';

export interface CameraRuntime {
  camera_id: string;
  status: CameraStatus;
  message: string;
  last_frame_at: number | null; // unix seconds
  fps: number;
  detection_status: DetectionStatus;
  detection_message: string;
  tracked_people: number;
  events_recorded: number;
  started_at: number | null;
  frame_size: [number, number] | null;
  quality?: { brightness: number; contrast: number; sharpness: number; measured_at: number } | null;
}

export interface EntranceLine {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  entry_side: 1 | -1;
}

export interface Camera {
  id: string;
  name: string;
  location: string;
  source_type: SourceType;
  location_id: number;
  source_description: string | null;
  source_configured: boolean;
  enabled: boolean;
  detection_enabled: boolean;
  counting_enabled: boolean;
  zones: Zone[];
  last_error: string | null;
  last_error_at: string | null;
  desired_running: boolean;
  line: EntranceLine | null;
  runtime: CameraRuntime;
}

export type EventType = 'entry' | 'exit' | 'uncertain';
export type ReviewStatus = 'auto' | 'needs_review' | 'confirmed' | 'corrected' | 'rejected';
export type MatchStatus = 'not_applicable' | 'matched' | 'unmatched';

export interface SurveillanceEvent {
  id: string;
  camera_id: string | null;
  camera_name: string | null;
  occurred_at: string;
  event_type: EventType;
  original_event_type: EventType;
  person_label: string;
  visit_id: number | null;
  confidence: number | null;
  has_snapshot: boolean;
  snapshot_status: string;
  review_status: ReviewStatus;
  match_status: MatchStatus;
  uncertain_reason: string | null;
  notes: string | null;
  is_demo: boolean;
  location_id?: number | null;
  source_node_id?: string | null;
}

export interface Visit {
  id: number;
  person_label: string;
  status: 'inside' | 'exited' | 'needs_review' | 'voided';
  entry_event_id: string | null;
  exit_event_id: string | null;
  entry_at: string | null;
  exit_at: string | null;
  entry_camera_id: string | null;
  exit_camera_id: string | null;
  match_method: 'tracker' | 'manual' | null;
  duration_seconds: number | null;
  operator_note: string | null;
  identified_by_operator: boolean;
}

export interface AuditEntry {
  id: number;
  occurred_at: string;
  username: string;
  action: string;
  entity_type: string;
  entity_id: string;
  details: Record<string, unknown>;
}

export interface EventDetail extends SurveillanceEvent {
  visit: Visit | null;
  audit: AuditEntry[];
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Occupancy {
  count: number;
  estimated: boolean;
  reasons: string[];
  last_reconciled_at: string | null;
  last_reconciled_value: number | null;
}

export interface HourBucket {
  hour: number;
  entries: number;
  exits: number;
}

export interface DaySummary {
  date: string;
  timezone: string;
  entries: number;
  exits: number;
  uncertain: number;
  unknown_visitors: number;
  footfall?: number;
  peak_hour?: number | null;
  hourly: HourBucket[];
}

export interface Overview {
  occupancy: LocationOccupancy & { locations: LocationOccupancy[] };
  today: DaySummary;
  yesterday_same_time: { entries: number; exits: number; until_local_time: string };
  alerts: { open: number; new: number; by_severity: Partial<Record<Severity, number>> };
  freshness: Freshness;
  recent_events: SurveillanceEvent[];
}

export interface SiteSettings {
  site_name: string;
  timezone: string;
  snapshot_retention_days: number;
  event_retention_days: number;
  min_confidence: number;
  cooldown_seconds: number;
  track_timeout_seconds: number;
  min_track_hits: number;
  min_side_frames: number;
  line_band: number;
  anchor_point: 'bottom' | 'center';
  snapshot_jpeg_quality: number;
  snapshot_max_width: number;
  snapshot_storage_limit_mb: number;
  alert_retention_days: number;
  updated_at: string;
}

export interface AnomalyHealth {
  enabled: boolean;
  status: 'disabled' | 'not_initialized' | 'ready' | 'motion' | 'placeholder' | 'error' | string;
  mode?: 'model' | 'motion' | 'placeholder' | 'disabled' | string;
  message?: string;
  model_name?: string;
  model_version?: string | null;
  threshold?: number;
  holdout_metrics?: { accuracy: number; precision: number; recall: number; f1: number; threshold: number } | null;
  trained_at?: string | null;
  min_consecutive_clips?: number;
  connection_point?: string;
  processed_clips?: number;
  positive_clips?: number;
  dropped_clips?: number;
  failed_inferences?: number;
  last_inference_at?: number | null;
  last_inference_ms?: number | null;
}

export interface SettingsResponse {
  site: SiteSettings;
  system: {
    environment: string;
    demo_mode: boolean;
    deployment_mode: string;
    person_detector: { available: boolean; message: string };
    // Administrator-only details:
    anomaly?: AnomalyHealth;
    storage?: { free_mb: number | null; low: boolean; min_free_mb: number; evidence_used_mb: number };
    file_sources_allowed?: boolean;
    test_video_dir?: string;
    email_configured?: boolean;
    camera_allowed_networks?: string;
  };
}

export interface LiveTrack {
  track_id: number | null;
  box: [number, number, number, number];
  side: 'inside' | 'outside' | 'unknown';
  last_event: EventType | null;
  label: string | null;
}

export interface LiveFrame {
  type: 'frame';
  camera_id: string;
  ts: number;
  width: number;
  height: number;
  image: string;
  tracks: LiveTrack[];
  line: EntranceLine | null;
  zones?: { id: number; name: string; kind: 'restricted' | 'monitored'; polygon: [number, number][]; count: number }[];
}

// ---- Business intelligence additions -------------------------------------------------------

export type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical';
export type AlertStatus = 'new' | 'acknowledged' | 'resolved' | 'dismissed';
export type DayKey = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun';
export type BusinessHours = Partial<Record<DayKey, [string, string][]>>;

export interface Location {
  id: number;
  name: string;
  address: string;
  capacity: number | null;
  business_hours: BusinessHours | null;
  is_active: boolean;
  camera_count: number;
}

export interface Zone {
  id: number;
  camera_id: string;
  name: string;
  kind: 'restricted' | 'monitored';
  polygon: [number, number][];
  dwell_seconds: number | null;
  enabled: boolean;
}

export interface Alert {
  id: string;
  rule_type: string;
  category: string;
  severity: Severity;
  title: string;
  reason: string;
  metrics: Record<string, unknown>;
  model_score: number | null;
  location_id: number | null;
  location_name: string | null;
  camera_id: string | null;
  camera_name: string | null;
  zone_id: number | null;
  zone_name: string | null;
  event_id: string | null;
  track_label: string | null;
  has_snapshot: boolean;
  snapshot_status: string;
  status: AlertStatus;
  occurrences: number;
  first_seen_at: string;
  last_seen_at: string;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
}

export interface Delivery {
  id: number;
  alert_id: string | null;
  channel_id: number;
  kind: string;
  subject: string;
  status: 'pending' | 'sent' | 'failed' | 'suppressed';
  attempts: number;
  last_error: string | null;
  next_attempt_at: string;
  sent_at: string | null;
  created_at: string;
}

export interface AlertDetail extends Alert {
  audit: AuditEntry[];
  deliveries: Delivery[];
}

export interface AlertPage extends Page<Alert> {
  categories: string[];
}

export interface AlertRule {
  rule_type: string;
  title: string;
  description: string;
  category: string;
  enabled: boolean;
  severity: Severity;
  cooldown_seconds: number;
  params: Record<string, number | boolean>;
  param_specs: Record<string, { type: 'int' | 'float' | 'bool'; default: number | boolean; min: number | null; max: number | null; label: string }>;
}

export interface Channel {
  id: number;
  kind: 'email' | 'webhook' | 'telegram';
  name: string;
  enabled: boolean;
  min_severity: Severity;
  categories: string[] | null;
  rate_limit_per_hour: number;
  target: string;
  config_ok: boolean;
  attach_snapshot: boolean;
}

export interface ReportSchedule {
  id: number;
  name: string;
  frequency: 'daily' | 'weekly' | 'monthly';
  location_id: number | null;
  channel_id: number;
  enabled: boolean;
  last_period_end: string | null;
  last_run_at: string | null;
}

export interface CountRow {
  entries: number;
  exits: number;
  uncertain: number;
}

export interface PeriodReport {
  date_from: string;
  date_to: string;
  days: number;
  timezone: string;
  totals: CountRow & { footfall: number; avg_daily_footfall: number };
  comparison: {
    previous_from: string;
    previous_to: string;
    previous: CountRow;
    entries_change_pct: number | null;
    exits_change_pct: number | null;
  };
  daily: (CountRow & { date: string })[];
  hourly: HourBucket[];
  weekday: { weekday: number; entries: number }[];
  peak_hours: HourBucket[];
  cameras: (CountRow & { camera_id: string | null; camera_name: string })[];
  locations: (CountRow & { location_id: number | null; location_name: string })[];
  dwell: { linked_visits: number; median_seconds: number | null };
  alerts: { total: number; by_category: Record<string, number>; by_severity: Record<string, number>; by_status: Record<string, number> };
}

export interface ModelInfo {
  id: number;
  version: string;
  algorithm: string;
  status: 'ready' | 'insufficient_data' | 'failed' | 'retired';
  active: boolean;
  n_samples: number;
  message: string;
  trained_by: string | null;
  trained_at: string;
  last_inference_at: string | null;
  contamination: number | null;
  data_quality: { usable_hours: number; days_covered: number; events: number } | null;
  has_artifact: boolean;
}

export interface ModelStatus {
  enabled: boolean;
  available: boolean;
  message: string;
  requirements: { min_hours: number; min_days: number; min_events: number };
  features: string[];
  active: ModelInfo | null;
  history: ModelInfo[];
  review_feedback: { alerts: number; open: number; resolved: number; dismissed: number; dismissed_rate: number | null };
}

export interface LocationOccupancy extends Occupancy {
  location_id: number | null;
  location_name: string | null;
  capacity: number | null;
}

export interface Freshness {
  last_event_at: string | null;
  last_frame_at: number | null;
  cameras_total: number;
  cameras_live: number;
  cameras_problem: number;
  pending_writes: number;
  deployment_mode: string;
  sync: { pending: number; last_sent_at: string | null; oldest_pending_at: string | null; last_error: string | null } | null;
}

// -- Guard room ------------------------------------------------------------------------------------

export type GuardState = 'on_duty' | 'reporting_in' | 'off_duty' | 'unreachable' | 'disabled';

export interface Guard {
  camera_id: string;
  camera_name: string;
  position: string;
  location_id: number;
  guard_name: string;
  custom_name: string;
  post: string;
  post_label: string;
  duties: string[];
  custom_duties: boolean;
  state: GuardState;
  status_message: string;
  tracked_people: number;
  fps: number;
  detection_status: string;
  reports_today: number;
  last_report: { title: string; severity: Severity; at: string } | null;
  has_line: boolean;
}

export interface GuardIncident {
  id: string;
  kind: 'security' | 'system';
  title: string;
  severity: Severity;
  status: 'open' | 'acknowledged' | 'resolved';
  summary: string;
  actions: string[];
  location_id: number | null;
  location_name: string | null;
  guards: { camera_id: string; camera_name: string; guard_name: string }[];
  alert_ids: string[];
  snapshot_alert_id: string | null;
  report_count: number;
  first_seen_at: string;
  last_seen_at: string;
  escalated_at: string | null;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
}

export interface HeadGuardConfig {
  enabled: boolean;
  correlation_minutes: number;
  corroboration_boost: boolean;
  briefing_enabled: boolean;
  briefing_hour: number;
  auto_resolve_minutes: number;
  last_briefing?: string | null;
}

export interface Recommendation {
  priority: 'urgent' | 'high' | 'medium' | 'low';
  text: string;
  link: string;
}

export interface GuardRoom {
  summary: string;
  head_guard: HeadGuardConfig;
  guards: Guard[];
  incidents: GuardIncident[];
  recommendations: Recommendation[];
  capacity: { max_cameras_per_server: number; running: number; video_model_enabled: boolean; person_detector: boolean };
}

export interface GuardCatalogue {
  posts: { key: string; label: string; description: string; duties: string[] }[];
  duties: { key: string; label: string; description: string; needs: string }[];
}

export interface MailServer {
  configured: boolean;
  source: 'console' | 'environment' | null;
  host: string;
  port: number;
  security: 'starttls' | 'ssl' | 'none';
  username: string;
  has_password: boolean;
  from_address: string;
  from_name: string;
  error: string | null;
  presets: Record<string, { host: string; port: number; security: 'starttls' | 'ssl' | 'none'; hint: string }>;
}
