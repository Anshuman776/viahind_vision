'use client';

import React, { useState } from 'react';
import { AlertStatus, SecurityAlert } from '../types/alert';
import { IncidentTimeline } from './IncidentTimeline';
import { ReviewActions } from './ReviewActions';
import {
  X,
  Play,
  Pause,
  Maximize2,
  VolumeX,
  Camera,
  Layers,
  MapPin,
  Clock,
  Shield,
  Cpu,
  Info,
  Sliders,
  ExternalLink,
  Flame,
  AlertTriangle,
} from 'lucide-react';

interface IncidentDetailProps {
  alert: SecurityAlert | null;
  isLoading?: boolean;
  isOffline?: boolean;
  onClose?: () => void;
  onUpdateStatus: (alertId: string, newStatus: AlertStatus, notes: string) => void;
}

export const IncidentDetail: React.FC<IncidentDetailProps> = ({
  alert,
  isLoading = false,
  isOffline = false,
  onClose,
  onUpdateStatus,
}) => {
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(6);
  const [showRawLogs, setShowRawLogs] = useState(false);

  if (isLoading) {
    return (
      <div className="incident-detail-panel loading" id="incident-detail-loading">
        <div className="skeleton-hero shimmer" />
        <div className="skeleton-grid">
          <div className="skeleton-box shimmer" />
          <div className="skeleton-box shimmer" />
          <div className="skeleton-box shimmer" />
        </div>
        <div className="skeleton-timeline shimmer" />
        <style jsx>{`
          .incident-detail-panel.loading {
            height: 100%;
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 16px;
            background: var(--bg-surface);
          }
          .skeleton-hero {
            height: 280px;
            border-radius: 8px;
            background: rgba(30, 41, 59, 0.4);
          }
          .skeleton-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
          }
          .skeleton-box {
            height: 70px;
            border-radius: 6px;
            background: rgba(30, 41, 59, 0.3);
          }
          .skeleton-timeline {
            flex: 1;
            border-radius: 8px;
            background: rgba(30, 41, 59, 0.25);
          }
          .shimmer {
            animation: shimmerEffect 1.5s infinite linear;
            background: linear-gradient(
              90deg,
              rgba(30, 41, 59, 0.3) 0%,
              rgba(51, 65, 85, 0.5) 50%,
              rgba(30, 41, 59, 0.3) 100%
            );
            background-size: 200% 100%;
          }
          @keyframes shimmerEffect {
            0% { background-position: -200% 0; }
            100% { background-position: 200% 0; }
          }
        `}</style>
      </div>
    );
  }

  if (!alert) {
    return (
      <div className="incident-detail-panel empty" id="incident-detail-empty">
        <div className="empty-content">
          <div className="icon-circle">
            <Camera size={32} className="text-muted" />
          </div>
          <h3 className="empty-title">No Incident Selected</h3>
          <p className="empty-desc">
            Select an alert card from the list on the left to inspect video evidence, AI classifier telemetry, and incident review history.
          </p>
        </div>
        <style jsx>{`
          .incident-detail-panel.empty {
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: var(--bg-surface);
            padding: 32px;
          }
          .empty-content {
            text-align: center;
            max-width: 360px;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 12px;
          }
          .icon-circle {
            width: 64px;
            height: 64px;
            border-radius: 50%;
            background: rgba(30, 41, 59, 0.5);
            border: 1px dashed var(--border-medium);
            display: flex;
            align-items: center;
            justify-content: center;
          }
          .empty-title {
            font-size: 1.05rem;
            color: var(--text-primary);
            font-weight: 600;
          }
          .empty-desc {
            font-size: 0.85rem;
            color: var(--text-secondary);
            line-height: 1.5;
          }
        `}</style>
      </div>
    );
  }

  const confidencePct = (alert.aiClassification.confidenceScore * 100).toFixed(1);
  const isHighConfidence = alert.aiClassification.confidenceScore >= alert.aiClassification.threshold;

  return (
    <div className="incident-detail-panel" id={`incident-detail-${alert.id}`}>
      {/* Header bar */}
      <div className="panel-header">
        <div className="header-meta">
          <div className="id-badge-group">
            <span className="incident-id-tag">{alert.id}</span>
            <span className={`status-pill ${alert.status}`}>{alert.status.toUpperCase()}</span>
            <span className={`severity-pill ${alert.severity}`}>{alert.severity.toUpperCase()}</span>
          </div>
          <h2 className="incident-title">{alert.eventType} Detected</h2>
        </div>

        {onClose && (
          <button
            type="button"
            className="close-panel-btn"
            onClick={onClose}
            aria-label="Close Incident Detail Panel"
            id="btn-close-detail-panel"
          >
            <X size={18} />
          </button>
        )}
      </div>

      <div className="panel-scroll-content">
        {/* Synthetic Mock Banner */}
        <div className="evidence-disclaimer-banner">
          <Info size={14} className="banner-icon" />
          <span>
            <strong>AUTHORIZED EVIDENCE ACCESS ONLY</strong>: Logged under supervisor access controls. {alert.evidence.syntheticDemoNotice}.
          </span>
        </div>

        {/* Video Player Mockup */}
        <section className="video-evidence-card" aria-label="Surveillance Video Evidence">
          <div className="cctv-screen-mockup">
            {/* Live Camera Watermarks */}
            <div className="cctv-hud-top">
              <div className="cctv-hud-rec">
                <span className="rec-dot" />
                <span className="rec-label">EVIDENCE RECORDING</span>
              </div>
              <div className="cctv-cam-tag">
                {alert.camera.id} • {alert.camera.floor.toUpperCase()}
              </div>
              <div className="cctv-timestamp-tag">
                {alert.detectedAtFormatted}
              </div>
            </div>

            {/* Synthetic Canvas Player Area */}
            <div className="cctv-viewport">
              <div className="cctv-crosshair-center" />
              <div className="cctv-motion-box">
                <span className="motion-label">AI BOUNDING BOX: {confidencePct}%</span>
              </div>
              <div className="surveillance-noise-grid" />
              <div className="cctv-watermark-center">VIAHIND SECURE CCTV ARCHIVE</div>
            </div>

            {/* Video Controls Bar */}
            <div className="cctv-control-bar">
              <button
                type="button"
                className="cctv-ctrl-btn"
                onClick={() => setIsPlaying(!isPlaying)}
                aria-label={isPlaying ? 'Pause evidence playback' : 'Play evidence playback'}
                id="btn-toggle-video-playback"
              >
                {isPlaying ? <Pause size={15} /> : <Play size={15} />}
              </button>

              <div className="timecode-display">
                00:0{currentTime} / 00:{alert.evidence.videoDurationSeconds < 10 ? `0${alert.evidence.videoDurationSeconds}` : alert.evidence.videoDurationSeconds}
              </div>

              <input
                type="range"
                min="0"
                max={alert.evidence.videoDurationSeconds}
                value={currentTime}
                onChange={(e) => setCurrentTime(Number(e.target.value))}
                className="cctv-scrubber"
                aria-label="Video scrubber"
              />

              <div className="cctv-right-controls">
                <span className="res-badge">1080P 30FPS</span>
                <span title="Surveillance audio muted"><VolumeX size={15} className="ctrl-icon text-muted" /></span>
                <span title="Maximize view"><Maximize2 size={15} className="ctrl-icon" /></span>
              </div>
            </div>
          </div>
        </section>

        {/* AI Fight Classifier Telemetry Banner (Required: Clearly labeled as model output) */}
        <section
          className="ai-model-output-card"
          aria-label="AI Fight-Classifier Inference Telemetry"
          id="ai-classifier-telemetry"
        >
          <div className="ai-card-header">
            <div className="ai-header-title">
              <Cpu size={16} className="text-highlight" />
              <h3 className="ai-heading">Fight-Classifier Model Output</h3>
            </div>
            <span className="model-version-tag">{alert.aiClassification.modelVersion}</span>
          </div>

          <div className="ai-score-row">
            <div className="score-meter-col">
              <div className="score-labels">
                <span className="score-title">Model Confidence Score:</span>
                <span className="score-value-big">
                  {confidencePct}%
                </span>
              </div>
              <div className="meter-track">
                <div
                  className={`meter-fill ${isHighConfidence ? 'critical' : 'warning'}`}
                  style={{ width: `${confidencePct}%` }}
                />
                <div
                  className="threshold-marker"
                  style={{ left: `${alert.aiClassification.threshold * 100}%` }}
                  title={`Trigger threshold: ${alert.aiClassification.threshold * 100}%`}
                />
              </div>
              <div className="meter-legend">
                <span>0% Safe</span>
                <span className="threshold-label">Threshold: {alert.aiClassification.threshold * 100}%</span>
                <span>100% Violent Incident</span>
              </div>
            </div>
          </div>

          <div className="model-mandatory-notice" role="alert">
            <AlertTriangle size={15} className="notice-icon" />
            <div className="notice-text">
              <strong>[AI MODEL OUTPUT - REQUIRES HUMAN REVIEW]</strong>: The score above is an automated algorithmic classification produced by <code>{alert.aiClassification.modelName}</code>. It is NOT final proof of an incident and must be validated by an authorized security supervisor before action.
            </div>
          </div>

          <button
            type="button"
            className="toggle-raw-log-btn"
            onClick={() => setShowRawLogs(!showRawLogs)}
            id="btn-toggle-raw-log"
          >
            <Sliders size={13} />
            <span>{showRawLogs ? 'Hide Raw Inference Tensor' : 'View Raw Inference Tensor & Optical Flow'}</span>
          </button>

          {showRawLogs && (
            <pre className="raw-log-box" tabIndex={0}>
              {alert.aiClassification.rawLog}
            </pre>
          )}
        </section>

        {/* Metadata Grid */}
        <section className="metadata-grid-section" aria-label="Incident Camera and Location Metadata">
          <div className="meta-card">
            <div className="meta-card-header">
              <Camera size={14} className="text-secondary" />
              <span>Camera ID</span>
            </div>
            <div className="meta-card-value font-mono">{alert.camera.id}</div>
            <div className="meta-card-sub">{alert.camera.name}</div>
          </div>

          <div className="meta-card">
            <div className="meta-card-header">
              <Layers size={14} className="text-secondary" />
              <span>Floor Level</span>
            </div>
            <div className="meta-card-value">{alert.camera.floor}</div>
            <div className="meta-card-sub">Multi-Floor PG Analytics</div>
          </div>

          <div className="meta-card">
            <div className="meta-card-header">
              <MapPin size={14} className="text-secondary" />
              <span>Exact Location</span>
            </div>
            <div className="meta-card-value location-text">{alert.camera.location}</div>
            <div className="meta-card-sub">Restricted PG Area</div>
          </div>

          <div className="meta-card">
            <div className="meta-card-header">
              <Clock size={14} className="text-secondary" />
              <span>Incident Timestamp</span>
            </div>
            <div className="meta-card-value font-mono">{alert.detectedAtFormatted}</div>
            <div className="meta-card-sub">UTC Sync Active</div>
          </div>
        </section>

        {/* Operator Review & Actions */}
        <ReviewActions
          alert={alert}
          isOffline={isOffline}
          onUpdateStatus={onUpdateStatus}
        />

        {/* Chronological Incident Timeline */}
        <section className="timeline-section" aria-label="Chronological Audit Timeline">
          <h3 className="timeline-section-title">Incident Progression & Audit Log</h3>
          <IncidentTimeline entries={alert.timeline} />
        </section>
      </div>

      <style jsx>{`
        .incident-detail-panel {
          background: var(--bg-surface);
          border-left: 1px solid var(--border-subtle);
          height: 100%;
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }

        .panel-header {
          padding: 16px 20px;
          border-bottom: 1px solid var(--border-subtle);
          background: rgba(11, 15, 25, 0.7);
          backdrop-filter: blur(8px);
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
        }

        .header-meta {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .id-badge-group {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .incident-id-tag {
          font-family: var(--font-mono);
          font-size: 0.74rem;
          color: var(--text-highlight);
          background: rgba(6, 182, 212, 0.12);
          border: 1px solid rgba(6, 182, 212, 0.25);
          padding: 2px 6px;
          border-radius: 4px;
        }

        .status-pill {
          font-size: 0.68rem;
          font-weight: 700;
          letter-spacing: 0.03em;
          padding: 2px 7px;
          border-radius: 4px;
        }
        .status-pill.pending {
          background: rgba(245, 158, 11, 0.18);
          color: #fcd34d;
        }
        .status-pill.acknowledged {
          background: rgba(59, 130, 246, 0.18);
          color: #93c5fd;
        }
        .status-pill.confirmed {
          background: rgba(16, 185, 129, 0.18);
          color: #6ee7b7;
        }
        .status-pill.dismissed {
          background: rgba(100, 116, 139, 0.18);
          color: #cbd5e1;
        }

        .severity-pill {
          font-size: 0.68rem;
          font-weight: 700;
          padding: 2px 7px;
          border-radius: 4px;
        }
        .severity-pill.critical {
          background: var(--badge-critical-bg);
          color: var(--badge-critical-text);
          border: 1px solid var(--badge-critical-border);
        }
        .severity-pill.high {
          background: var(--badge-high-bg);
          color: var(--badge-high-text);
        }
        .severity-pill.medium {
          background: var(--badge-medium-bg);
          color: var(--badge-medium-text);
        }
        .severity-pill.low {
          background: var(--badge-low-bg);
          color: var(--badge-low-text);
        }

        .incident-title {
          font-size: 1.1rem;
          font-weight: 700;
          color: var(--text-primary);
        }

        .close-panel-btn {
          color: var(--text-secondary);
          padding: 6px;
          border-radius: 6px;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.15s ease;
        }

        .close-panel-btn:hover {
          color: var(--text-primary);
          background: rgba(255, 255, 255, 0.08);
        }

        .panel-scroll-content {
          flex: 1;
          overflow-y: auto;
          padding: 20px;
          display: flex;
          flex-direction: column;
          gap: 18px;
        }

        .evidence-disclaimer-banner {
          background: rgba(245, 158, 11, 0.08);
          border: 1px solid rgba(245, 158, 11, 0.25);
          border-radius: 6px;
          padding: 8px 12px;
          font-size: 0.75rem;
          color: #fde68a;
          display: flex;
          align-items: flex-start;
          gap: 8px;
        }

        .video-evidence-card {
          background: #000000;
          border: 1px solid var(--border-medium);
          border-radius: 8px;
          overflow: hidden;
          box-shadow: var(--shadow-elevated);
        }

        .cctv-screen-mockup {
          position: relative;
          background: #050811;
        }

        .cctv-hud-top {
          position: absolute;
          top: 10px;
          left: 12px;
          right: 12px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          z-index: 10;
          font-family: var(--font-mono);
          font-size: 0.72rem;
          color: #e2e8f0;
          text-shadow: 0 1px 3px rgba(0, 0, 0, 0.9);
        }

        .cctv-hud-rec {
          display: flex;
          align-items: center;
          gap: 6px;
          background: rgba(0, 0, 0, 0.7);
          padding: 2px 8px;
          border-radius: 4px;
        }

        .rec-dot {
          width: 8px;
          height: 8px;
          background: #ef4444;
          border-radius: 50%;
          animation: pulse-rec 1.2s infinite;
        }

        @keyframes pulse-rec {
          0% { opacity: 0.3; }
          50% { opacity: 1; }
          100% { opacity: 0.3; }
        }

        .cctv-cam-tag,
        .cctv-timestamp-tag {
          background: rgba(0, 0, 0, 0.7);
          padding: 2px 8px;
          border-radius: 4px;
        }

        .cctv-viewport {
          height: 250px;
          position: relative;
          display: flex;
          align-items: center;
          justify-content: center;
          background: radial-gradient(circle at center, #111a2e 0%, #060912 100%);
          overflow: hidden;
        }

        .cctv-motion-box {
          position: absolute;
          width: 140px;
          height: 120px;
          border: 2px solid #ef4444;
          background: rgba(239, 68, 68, 0.1);
          animation: scanPulse 3s infinite alternate ease-in-out;
        }

        .motion-label {
          position: absolute;
          top: -18px;
          left: 0;
          background: #ef4444;
          color: #ffffff;
          font-size: 0.6rem;
          font-family: var(--font-mono);
          font-weight: 700;
          padding: 1px 4px;
        }

        @keyframes scanPulse {
          0% { transform: translate(-30px, -10px); }
          100% { transform: translate(40px, 15px); }
        }

        .surveillance-noise-grid {
          position: absolute;
          inset: 0;
          background-image: linear-gradient(rgba(255, 255, 255, 0.02) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px);
          background-size: 20px 20px;
          pointer-events: none;
        }

        .cctv-watermark-center {
          position: absolute;
          bottom: 12px;
          right: 14px;
          font-size: 0.68rem;
          font-family: var(--font-mono);
          letter-spacing: 0.05em;
          color: rgba(255, 255, 255, 0.25);
          pointer-events: none;
        }

        .cctv-control-bar {
          height: 40px;
          background: rgba(11, 15, 25, 0.95);
          border-top: 1px solid rgba(148, 163, 184, 0.1);
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 0 14px;
        }

        .cctv-ctrl-btn {
          color: var(--text-primary);
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .timecode-display {
          font-family: var(--font-mono);
          font-size: 0.72rem;
          color: var(--text-secondary);
        }

        .cctv-scrubber {
          flex: 1;
          accent-color: var(--accent-cyan);
          cursor: pointer;
          height: 4px;
        }

        .cctv-right-controls {
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .res-badge {
          font-size: 0.65rem;
          font-family: var(--font-mono);
          background: rgba(30, 41, 59, 0.8);
          border: 1px solid rgba(148, 163, 184, 0.2);
          color: var(--text-secondary);
          padding: 1px 5px;
          border-radius: 3px;
        }

        /* AI Model Output Section */
        .ai-model-output-card {
          background: rgba(15, 23, 42, 0.85);
          border: 1px solid rgba(56, 189, 248, 0.25);
          border-radius: 8px;
          padding: 16px 18px;
          display: flex;
          flex-direction: column;
          gap: 12px;
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
        }

        .ai-card-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
        }

        .ai-header-title {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .ai-heading {
          font-size: 0.92rem;
          font-weight: 700;
          color: var(--text-primary);
        }

        .model-version-tag {
          font-family: var(--font-mono);
          font-size: 0.7rem;
          color: var(--accent-cyan);
          background: rgba(6, 182, 212, 0.12);
          padding: 2px 7px;
          border-radius: 4px;
          border: 1px solid rgba(6, 182, 212, 0.25);
        }

        .score-meter-col {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .score-labels {
          display: flex;
          align-items: baseline;
          justify-content: space-between;
        }

        .score-title {
          font-size: 0.8rem;
          color: var(--text-secondary);
        }

        .score-value-big {
          font-size: 1.25rem;
          font-weight: 800;
          font-family: var(--font-mono);
          color: #f87171;
        }

        .meter-track {
          position: relative;
          height: 10px;
          background: rgba(30, 41, 59, 0.8);
          border-radius: 999px;
          overflow: hidden;
        }

        .meter-fill {
          height: 100%;
          border-radius: 999px;
          transition: width 0.3s ease;
        }
        .meter-fill.critical {
          background: linear-gradient(90deg, #f59e0b 0%, #ef4444 100%);
        }
        .meter-fill.warning {
          background: linear-gradient(90deg, #3b82f6 0%, #f59e0b 100%);
        }

        .threshold-marker {
          position: absolute;
          top: 0;
          bottom: 0;
          width: 2px;
          background: #ffffff;
          box-shadow: 0 0 6px #ffffff;
          z-index: 5;
        }

        .meter-legend {
          display: flex;
          justify-content: space-between;
          font-size: 0.68rem;
          color: var(--text-muted);
        }

        .threshold-label {
          color: #fcd34d;
        }

        .model-mandatory-notice {
          background: rgba(239, 68, 68, 0.12);
          border: 1px solid rgba(239, 68, 68, 0.3);
          border-radius: 6px;
          padding: 10px 12px;
          display: flex;
          align-items: flex-start;
          gap: 10px;
        }

        :global(.notice-icon) {
          color: #f87171;
          margin-top: 2px;
          flex-shrink: 0;
        }

        .notice-text {
          font-size: 0.77rem;
          color: #fecaca;
          line-height: 1.45;
        }

        .notice-text code {
          background: rgba(0, 0, 0, 0.4);
          padding: 1px 4px;
          border-radius: 3px;
          color: #ffffff;
          font-family: var(--font-mono);
        }

        .toggle-raw-log-btn {
          align-self: flex-start;
          display: inline-flex;
          align-items: center;
          gap: 6px;
          font-size: 0.74rem;
          color: var(--text-secondary);
          transition: color 0.15s ease;
        }

        .toggle-raw-log-btn:hover {
          color: var(--text-primary);
        }

        .raw-log-box {
          background: #050811;
          border: 1px solid var(--border-subtle);
          border-radius: 6px;
          padding: 10px;
          font-family: var(--font-mono);
          font-size: 0.72rem;
          color: #a5f3fc;
          white-space: pre-wrap;
          word-break: break-all;
        }

        /* Metadata Grid */
        .metadata-grid-section {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 10px;
        }

        .meta-card {
          background: rgba(15, 23, 42, 0.6);
          border: 1px solid var(--border-subtle);
          border-radius: 6px;
          padding: 10px 12px;
          display: flex;
          flex-direction: column;
          gap: 3px;
        }

        .meta-card-header {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.73rem;
          color: var(--text-secondary);
        }

        .meta-card-value {
          font-weight: 600;
          font-size: 0.88rem;
          color: var(--text-primary);
        }

        .meta-card-value.location-text {
          font-size: 0.82rem;
          line-height: 1.3;
        }

        .meta-card-sub {
          font-size: 0.7rem;
          color: var(--text-muted);
        }

        .font-mono {
          font-family: var(--font-mono);
        }

        .timeline-section {
          background: rgba(15, 23, 42, 0.6);
          border: 1px solid var(--border-subtle);
          border-radius: 8px;
          padding: 16px 18px;
        }

        .timeline-section-title {
          font-size: 0.9rem;
          font-weight: 700;
          margin-bottom: 12px;
          color: var(--text-primary);
        }
      `}</style>
    </div>
  );
};
