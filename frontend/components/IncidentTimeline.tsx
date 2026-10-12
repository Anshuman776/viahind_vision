'use client';

import React from 'react';
import { TimelineEntry } from '../types/alert';
import { Cpu, ShieldCheck, UserCheck, AlertCircle } from 'lucide-react';

interface IncidentTimelineProps {
  entries: TimelineEntry[];
}

export const IncidentTimeline: React.FC<IncidentTimelineProps> = ({ entries }) => {
  const getIcon = (type: string) => {
    switch (type) {
      case 'model':
        return <Cpu size={14} className="timeline-node-icon model" />;
      case 'user':
        return <UserCheck size={14} className="timeline-node-icon user" />;
      default:
        return <ShieldCheck size={14} className="timeline-node-icon system" />;
    }
  };

  return (
    <div className="timeline-component-container" aria-label="Incident Audit Timeline">
      <div className="timeline-track">
        {entries.map((entry, index) => {
          const isLast = index === entries.length - 1;
          return (
            <div key={entry.id || index} className="timeline-row">
              <div className="node-column">
                <div className={`node-bullet ${entry.type}`}>
                  {getIcon(entry.type)}
                </div>
                {!isLast && <div className="node-line" />}
              </div>

              <div className="content-column">
                <div className="content-header">
                  <span className="entry-title">{entry.title}</span>
                  <span className="entry-time">{entry.timestamp}</span>
                </div>
                <p className="entry-description">{entry.description}</p>
                <div className="entry-actor-tag">
                  <span className="actor-label">Actor:</span>
                  <span className="actor-name">{entry.actor}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <style jsx>{`
        .timeline-component-container {
          padding: 8px 0;
        }

        .timeline-track {
          display: flex;
          flex-direction: column;
        }

        .timeline-row {
          display: flex;
          gap: 14px;
          min-height: 58px;
        }

        .node-column {
          display: flex;
          flex-direction: column;
          align-items: center;
          width: 28px;
        }

        .node-bullet {
          width: 26px;
          height: 26px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #0f172a;
          border: 1px solid var(--border-medium);
          z-index: 2;
        }

        .node-bullet.system {
          border-color: rgba(59, 130, 246, 0.4);
          background: rgba(59, 130, 246, 0.1);
        }

        .node-bullet.model {
          border-color: rgba(6, 182, 212, 0.5);
          background: rgba(6, 182, 212, 0.15);
        }

        .node-bullet.user {
          border-color: rgba(16, 185, 129, 0.5);
          background: rgba(16, 185, 129, 0.15);
        }

        :global(.timeline-node-icon.system) {
          color: var(--accent-blue);
        }
        :global(.timeline-node-icon.model) {
          color: var(--accent-cyan);
        }
        :global(.timeline-node-icon.user) {
          color: var(--accent-emerald);
        }

        .node-line {
          width: 2px;
          flex: 1;
          background: rgba(148, 163, 184, 0.15);
          margin: 4px 0;
        }

        .content-column {
          flex: 1;
          padding-bottom: 16px;
        }

        .content-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          margin-bottom: 3px;
        }

        .entry-title {
          font-weight: 600;
          font-size: 0.85rem;
          color: var(--text-primary);
        }

        .entry-time {
          font-family: var(--font-mono);
          font-size: 0.74rem;
          color: var(--text-muted);
        }

        .entry-description {
          font-size: 0.8rem;
          color: var(--text-secondary);
          line-height: 1.4;
          margin-bottom: 4px;
        }

        .entry-actor-tag {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-size: 0.7rem;
          background: rgba(15, 23, 42, 0.6);
          padding: 1px 6px;
          border-radius: 4px;
          border: 1px solid rgba(148, 163, 184, 0.1);
        }

        .actor-label {
          color: var(--text-muted);
        }

        .actor-name {
          color: var(--text-secondary);
          font-weight: 500;
        }
      `}</style>
    </div>
  );
};
