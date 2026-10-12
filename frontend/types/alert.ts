export type AlertStatus = 'pending' | 'acknowledged' | 'confirmed' | 'dismissed';

export type AlertSeverity = 'critical' | 'high' | 'medium' | 'low';

export type EventType =
  | 'Physical Altercation'
  | 'Crowd Gathering'
  | 'Unauthorized Access'
  | 'Suspicious Loitering'
  | 'Late-Night Movement'
  | 'Perimeter Breach';

export type FloorIdentifier = 'Basement' | 'Ground Floor' | 'Floor 1' | 'Floor 2' | 'Floor 3' | 'Rooftop';

export interface TimelineEntry {
  id: string;
  timestamp: string;
  title: string;
  description: string;
  actor: string;
  type: 'system' | 'model' | 'user';
}

export interface SecurityAlert {
  id: string;
  camera: {
    id: string;
    name: string;
    location: string;
    floor: FloorIdentifier;
    rtspStreamUrl?: string;
  };
  eventType: EventType;
  severity: AlertSeverity;
  status: AlertStatus;
  timestamp: string; // ISO 8601 string
  detectedAtFormatted: string;
  
  // Fight-classifier AI output (Model inference)
  aiClassification: {
    label: string;
    modelName: string;
    modelVersion: string;
    confidenceScore: number; // 0.00 to 1.00 (e.g. 0.942 -> 94.2%)
    threshold: number;
    rawLog: string;
    requiresHumanVerification: boolean;
  };

  // Evidence metadata
  evidence: {
    videoDurationSeconds: number;
    videoThumbnailUrl: string;
    hasWatermark: boolean;
    authorizedRoles: string[];
    syntheticDemoNotice: string;
  };

  // Review & audit history
  reviewHistory: {
    reviewedBy?: string;
    reviewedAt?: string;
    notes?: string;
    lastStatusTransition?: string;
  };

  timeline: TimelineEntry[];
}

export interface AlertFilterState {
  status: AlertStatus | 'all';
  severity: AlertSeverity | 'all';
  floor: FloorIdentifier | 'all';
  searchQuery: string;
  startDate: string;
  endDate: string;
}
