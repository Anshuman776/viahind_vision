export type Role = 'admin' | 'operator';

export interface User {
  id: number;
  username: string;
  role: Role;
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
  source_description: string;
  source_configured: boolean;
  enabled: boolean;
  detection_enabled: boolean;
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
  hourly: HourBucket[];
}

export interface Overview {
  occupancy: Occupancy;
  today: DaySummary;
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
  updated_at: string;
}

export interface AnomalyHealth {
  enabled: boolean;
  status: string;
  message?: string;
  model_name?: string;
  model_version?: string;
  connection_point?: string;
  processed_clips?: number;
  dropped_clips?: number;
}

export interface SettingsResponse {
  site: SiteSettings;
  system: {
    environment: string;
    demo_mode: boolean;
    person_detector: { available: boolean; message: string };
    anomaly: AnomalyHealth;
    storage: { free_mb: number | null; low: boolean; min_free_mb: number };
    file_sources_allowed: boolean;
    test_video_dir: string;
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
}
