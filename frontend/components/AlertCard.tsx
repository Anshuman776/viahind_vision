'use client';

import React from 'react';
import { SecurityAlert } from '../types/alert';
import {
  AlertTriangle,
  Users,
  ShieldAlert,
  Clock,
  Eye,
  Camera,
  Layers,
  ChevronRight,
  Flame,
} from 'lucide-react';

interface AlertCardProps {
  alert: SecurityAlert;
  isSelected: boolean;
  onSelect: (alert: SecurityAlert) => void;
}

export const AlertCard: React.FC<AlertCardProps> = ({ alert, isSelected, onSelect }) => {
  const getEventIcon = (type: string) => {
    switch (type) {
      case 'Physical Altercation':
        return <Flame className="card-icon fight" size={16} />;
      case 'Crowd Gathering':
        return <Users className="card-icon crowd" size={16} />;
      case 'Unauthorized Access':
      case 'Perimeter Breach':
        return <ShieldAlert className="card-icon breach" size={16} />;
      default:
        return <AlertTriangle className="card-icon default" size={16} />;
    }
  };

  const getSeverityBadgeClass = (severity: string) => {
    switch (severity) {
      case 'critical':
        return 'severity-badge critical';
      case 'high':
        return 'severity-badge high';
      case 'medium':
        return 'severity-badge medium';
      default:
        return 'severity-badge low';
    }
  };

  const getStatusBadgeClass = (status: string) => {
    switch (status) {
      case 'pending':
        return 'status-badge pending';
      case 'acknowledged':
        return 'status-badge acknowledged';
      case 'confirmed':
        return 'status-badge confirmed';
      case 'dismissed':
        return 'status-badge dismissed';
      default:
        return 'status-badge';
    }
  };

  const confidencePercentage = Math.round(alert.aiClassification.confidenceScore * 100);

  return (
    <article
      id={`alert-card-${alert.id}`}
      tabIndex={0}
      role="button"
      aria-selected={isSelected}
      aria-label={`Alert ${alert.id}, ${alert.eventType} at ${alert.camera.location}, status ${alert.status}`}
      onClick={() => onSelect(alert)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(alert);
        }
      }}
      className={`alert-card-item ${isSelected ? 'selected' : ''} ${alert.severity === 'critical' ? 'critical-glow' : ''}`}
    >
      <div className="card-top-row">
        <div className="event-type-wrapper">
          {getEventIcon(alert.eventType)}
          <span className="event-type-label">{alert.eventType}</span>
        </div>
        <div className="badges-wrapper">
          <span className={getSeverityBadgeClass(alert.severity)}>
            {alert.severity.toUpperCase()}
          </span>
          <span className={getStatusBadgeClass(alert.status)}>
            {alert.status}
          </span>
        </div>
      </div>

      <div className="card-middle-row">
        <div className="camera-info">
          <Camera size={13} className="text-secondary" />
          <span className="camera-id">{alert.camera.id}</span>
          <span className="dot-sep">•</span>
          <span className="camera-loc">{alert.camera.location}</span>
        </div>
        <div className="floor-info">
          <Layers size={13} className="text-secondary" />
          <span className="floor-name">{alert.camera.floor}</span>
        </div>
      </div>

      <div className="card-bottom-row">
        <div className="timestamp-info">
          <Clock size={12} className="text-muted" />
          <time dateTime={alert.timestamp}>{alert.detectedAtFormatted}</time>
        </div>

        <div className="ai-preview-pill" title="AI Model Classifier score (Human verification required)">
          <span className="ai-tag">AI</span>
          <span className="score-val">{confidencePercentage}%</span>
        </div>

        <ChevronRight size={14} className="card-arrow text-muted" />
      </div>

      <style jsx>{`
        .alert-card-item {
          background: var(--bg-card);
          border: 1px solid var(--border-subtle);
          border-radius: 8px;
          padding: 14px 16px;
          cursor: pointer;
          transition: all 0.18s ease;
          position: relative;
          outline: none;
          display: flex;
          flex-direction: column;
          gap: 10px;
        }

        .alert-card-item:hover {
          background: var(--bg-card-hover);
          border-color: rgba(148, 163, 184, 0.3);
          transform: translateY(-1px);
        }

        .alert-card-item:focus-visible {
          border-color: var(--accent-blue);
          box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.35);
        }

        .alert-card-item.selected {
          background: var(--bg-card-active);
          border-color: var(--accent-blue);
          box-shadow: 0 0 0 1px var(--accent-blue), 0 4px 16px rgba(59, 130, 246, 0.15);
        }

        .alert-card-item.critical-glow {
          border-left: 4px solid var(--accent-red);
        }

        .card-top-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
        }

        .event-type-wrapper {
          display: flex;
          align-items: center;
          gap: 7px;
        }

        .event-type-label {
          font-weight: 600;
          font-size: 0.92rem;
          color: var(--text-primary);
        }

        .card-icon.fight {
          color: var(--accent-red);
        }
        .card-icon.crowd {
          color: var(--accent-amber);
        }
        .card-icon.breach {
          color: #f43f5e;
        }
        .card-icon.default {
          color: var(--accent-cyan);
        }

        .badges-wrapper {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .severity-badge {
          font-size: 0.68rem;
          font-weight: 700;
          letter-spacing: 0.04em;
          padding: 2px 7px;
          border-radius: 4px;
        }
        .severity-badge.critical {
          background: var(--badge-critical-bg);
          color: var(--badge-critical-text);
          border: 1px solid var(--badge-critical-border);
        }
        .severity-badge.high {
          background: var(--badge-high-bg);
          color: var(--badge-high-text);
          border: 1px solid var(--badge-high-border);
        }
        .severity-badge.medium {
          background: var(--badge-medium-bg);
          color: var(--badge-medium-text);
          border: 1px solid var(--badge-medium-border);
        }
        .severity-badge.low {
          background: var(--badge-low-bg);
          color: var(--badge-low-text);
          border: 1px solid var(--badge-low-border);
        }

        .status-badge {
          font-size: 0.7rem;
          font-weight: 600;
          text-transform: capitalize;
          padding: 2px 7px;
          border-radius: 4px;
        }
        .status-badge.pending {
          background: rgba(245, 158, 11, 0.15);
          color: #fcd34d;
          border: 1px solid rgba(245, 158, 11, 0.3);
        }
        .status-badge.acknowledged {
          background: rgba(59, 130, 246, 0.15);
          color: #93c5fd;
          border: 1px solid rgba(59, 130, 246, 0.3);
        }
        .status-badge.confirmed {
          background: rgba(16, 185, 129, 0.15);
          color: #6ee7b7;
          border: 1px solid rgba(16, 185, 129, 0.3);
        }
        .status-badge.dismissed {
          background: rgba(100, 116, 139, 0.15);
          color: #94a3b8;
          border: 1px solid rgba(100, 116, 139, 0.3);
        }

        .card-middle-row {
          display: flex;
          flex-direction: column;
          gap: 4px;
          font-size: 0.8rem;
          color: var(--text-secondary);
        }

        .camera-info,
        .floor-info {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .camera-id {
          font-family: var(--font-mono);
          color: var(--text-primary);
          font-size: 0.78rem;
        }

        .dot-sep {
          color: var(--text-muted);
        }

        .camera-loc {
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .floor-name {
          color: var(--text-secondary);
        }

        .card-bottom-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding-top: 6px;
          border-top: 1px solid rgba(148, 163, 184, 0.08);
          font-size: 0.75rem;
        }

        .timestamp-info {
          display: flex;
          align-items: center;
          gap: 5px;
          color: var(--text-muted);
        }

        .ai-preview-pill {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          background: rgba(15, 23, 42, 0.9);
          border: 1px solid rgba(56, 189, 248, 0.25);
          padding: 2px 7px;
          border-radius: 4px;
        }

        .ai-tag {
          font-size: 0.65rem;
          font-weight: 700;
          color: var(--accent-cyan);
          letter-spacing: 0.04em;
        }

        .score-val {
          font-family: var(--font-mono);
          font-size: 0.74rem;
          color: #e2e8f0;
          font-weight: 600;
        }

        .card-arrow {
          transition: transform 0.15s ease;
        }

        .alert-card-item:hover .card-arrow {
          transform: translateX(2px);
          color: var(--text-primary);
        }
      `}</style>
    </article>
  );
};
