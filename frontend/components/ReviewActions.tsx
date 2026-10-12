'use client';

import React, { useState } from 'react';
import { AlertStatus, SecurityAlert } from '../types/alert';
import {
  CheckCircle2,
  AlertOctagon,
  XCircle,
  FileText,
  Send,
  Loader2,
  ShieldCheck,
  AlertTriangle,
} from 'lucide-react';

interface ReviewActionsProps {
  alert: SecurityAlert;
  isOffline: boolean;
  onUpdateStatus: (alertId: string, newStatus: AlertStatus, notes: string) => void;
}

export const ReviewActions: React.FC<ReviewActionsProps> = ({
  alert,
  isOffline,
  onUpdateStatus,
}) => {
  const [notes, setNotes] = useState(alert.reviewHistory.notes || '');
  const [submittingStatus, setSubmittingStatus] = useState<AlertStatus | null>(null);
  const [actionSuccessMsg, setActionSuccessMsg] = useState<string | null>(null);

  const handleAction = async (status: AlertStatus) => {
    if (isOffline) {
      if (typeof window !== 'undefined') {
        window.alert('Cannot perform review action in Offline mode. Please reconnect first.');
      }
      return;
    }

    setSubmittingStatus(status);
    setActionSuccessMsg(null);

    // Simulate async API response delay (180ms)
    setTimeout(() => {
      onUpdateStatus(alert.id, status, notes);
      setSubmittingStatus(null);
      setActionSuccessMsg(`Status successfully transitioned to ${status.toUpperCase()}`);
      setTimeout(() => setActionSuccessMsg(null), 3000);
    }, 180);
  };

  const applyTemplate = (tpl: string) => {
    setNotes((prev) => (prev ? `${prev} | ${tpl}` : tpl));
  };

  return (
    <div className="review-actions-wrapper" id="review-actions-panel">
      <div className="section-title-row">
        <div className="title-left">
          <ShieldCheck size={16} className="text-highlight" />
          <h3 className="section-title">Incident Review & Operator Action</h3>
        </div>
        <span className="current-state-tag">
          Current: <strong>{alert.status.toUpperCase()}</strong>
        </span>
      </div>

      {actionSuccessMsg && (
        <div className="success-banner" role="status" aria-live="polite">
          <CheckCircle2 size={14} />
          <span>{actionSuccessMsg}</span>
        </div>
      )}

      {isOffline && (
        <div className="offline-warning-box">
          <AlertTriangle size={14} />
          <span>Console is currently in Offline Simulation mode. Review actions disabled.</span>
        </div>
      )}

      <div className="notes-container">
        <div className="notes-header">
          <label htmlFor="reviewer-notes-input" className="notes-label">
            <FileText size={13} />
            <span>Operator Reviewer Notes (Optional)</span>
          </label>
          <div className="quick-templates">
            <button
              type="button"
              className="tpl-btn"
              onClick={() => applyTemplate('Security guards dispatched to floor.')}
            >
              + Dispatched
            </button>
            <button
              type="button"
              className="tpl-btn"
              onClick={() => applyTemplate('Resident verified. False alarm.')}
            >
              + False Alarm
            </button>
            <button
              type="button"
              className="tpl-btn"
              onClick={() => applyTemplate('Escalated to Chief Warden.')}
            >
              + Escalated
            </button>
          </div>
        </div>

        <textarea
          id="reviewer-notes-input"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Document incident verification rationale, guard dispatch status, or resident details..."
          rows={3}
          disabled={isOffline}
          className="notes-textarea"
        />
      </div>

      <div className="action-buttons-grid">
        <button
          type="button"
          id="btn-action-acknowledge"
          disabled={isOffline || submittingStatus !== null || alert.status === 'acknowledged'}
          onClick={() => handleAction('acknowledged')}
          className={`action-btn acknowledge ${alert.status === 'acknowledged' ? 'active' : ''}`}
          aria-label="Acknowledge Alert"
        >
          {submittingStatus === 'acknowledged' ? (
            <Loader2 size={16} className="spin" />
          ) : (
            <CheckCircle2 size={16} />
          )}
          <span>Acknowledge</span>
        </button>

        <button
          type="button"
          id="btn-action-confirm"
          disabled={isOffline || submittingStatus !== null || alert.status === 'confirmed'}
          onClick={() => handleAction('confirmed')}
          className={`action-btn confirm ${alert.status === 'confirmed' ? 'active' : ''}`}
          aria-label="Confirm Incident"
        >
          {submittingStatus === 'confirmed' ? (
            <Loader2 size={16} className="spin" />
          ) : (
            <AlertOctagon size={16} />
          )}
          <span>Confirm Incident</span>
        </button>

        <button
          type="button"
          id="btn-action-dismiss"
          disabled={isOffline || submittingStatus !== null || alert.status === 'dismissed'}
          onClick={() => handleAction('dismissed')}
          className={`action-btn dismiss ${alert.status === 'dismissed' ? 'active' : ''}`}
          aria-label="Dismiss Alert"
        >
          {submittingStatus === 'dismissed' ? (
            <Loader2 size={16} className="spin" />
          ) : (
            <XCircle size={16} />
          )}
          <span>Dismiss</span>
        </button>
      </div>

      <style jsx>{`
        .review-actions-wrapper {
          background: rgba(15, 23, 42, 0.7);
          border: 1px solid var(--border-subtle);
          border-radius: 8px;
          padding: 18px 20px;
          display: flex;
          flex-direction: column;
          gap: 14px;
        }

        .section-title-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
        }

        .title-left {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .section-title {
          font-size: 0.92rem;
          font-weight: 700;
          color: var(--text-primary);
        }

        .current-state-tag {
          font-size: 0.75rem;
          color: var(--text-secondary);
        }

        .current-state-tag strong {
          color: var(--accent-cyan);
        }

        .success-banner {
          background: rgba(16, 185, 129, 0.15);
          border: 1px solid rgba(16, 185, 129, 0.35);
          color: #6ee7b7;
          font-size: 0.8rem;
          padding: 8px 12px;
          border-radius: 6px;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .offline-warning-box {
          background: rgba(239, 68, 68, 0.12);
          border: 1px solid rgba(239, 68, 68, 0.3);
          color: #fca5a5;
          font-size: 0.78rem;
          padding: 8px 12px;
          border-radius: 6px;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .notes-container {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .notes-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          flex-wrap: wrap;
          gap: 8px;
        }

        .notes-label {
          font-size: 0.78rem;
          font-weight: 600;
          color: var(--text-secondary);
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .quick-templates {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .tpl-btn {
          font-size: 0.68rem;
          padding: 2px 7px;
          background: rgba(30, 41, 59, 0.8);
          border: 1px solid rgba(148, 163, 184, 0.18);
          border-radius: 4px;
          color: var(--text-secondary);
          transition: all 0.15s ease;
        }

        .tpl-btn:hover {
          color: var(--text-primary);
          border-color: rgba(148, 163, 184, 0.4);
          background: rgba(51, 65, 85, 0.9);
        }

        .notes-textarea {
          width: 100%;
          resize: vertical;
          min-height: 64px;
          background: rgba(11, 15, 25, 0.75);
          border: 1px solid var(--border-medium);
          border-radius: 6px;
          color: var(--text-primary);
          padding: 8px 12px;
          font-size: 0.82rem;
          line-height: 1.4;
        }

        .action-buttons-grid {
          display: grid;
          grid-template-columns: 1fr 1fr 1fr;
          gap: 10px;
        }

        @media (max-width: 600px) {
          .action-buttons-grid {
            grid-template-columns: 1fr;
          }
        }

        .action-btn {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          padding: 10px 14px;
          border-radius: 6px;
          font-weight: 600;
          font-size: 0.84rem;
          transition: all 0.18s ease;
          border: 1px solid transparent;
        }

        .action-btn:disabled {
          opacity: 0.45;
          cursor: not-allowed;
        }

        /* Acknowledge Button */
        .action-btn.acknowledge {
          background: rgba(59, 130, 246, 0.16);
          color: #93c5fd;
          border-color: rgba(59, 130, 246, 0.35);
        }
        .action-btn.acknowledge:not(:disabled):hover {
          background: rgba(59, 130, 246, 0.28);
          border-color: #60a5fa;
          box-shadow: 0 0 12px rgba(59, 130, 246, 0.25);
        }
        .action-btn.acknowledge.active {
          background: rgba(59, 130, 246, 0.35);
          border-color: #3b82f6;
          color: #ffffff;
        }

        /* Confirm Incident Button */
        .action-btn.confirm {
          background: rgba(239, 68, 68, 0.16);
          color: #fca5a5;
          border-color: rgba(239, 68, 68, 0.35);
        }
        .action-btn.confirm:not(:disabled):hover {
          background: rgba(239, 68, 68, 0.28);
          border-color: #f87171;
          box-shadow: 0 0 14px rgba(239, 68, 68, 0.3);
        }
        .action-btn.confirm.active {
          background: rgba(239, 68, 68, 0.35);
          border-color: #ef4444;
          color: #ffffff;
        }

        /* Dismiss Button */
        .action-btn.dismiss {
          background: rgba(100, 116, 139, 0.16);
          color: #cbd5e1;
          border-color: rgba(100, 116, 139, 0.35);
        }
        .action-btn.dismiss:not(:disabled):hover {
          background: rgba(100, 116, 139, 0.28);
          border-color: #94a3b8;
        }
        .action-btn.dismiss.active {
          background: rgba(100, 116, 139, 0.35);
          border-color: #64748b;
          color: #ffffff;
        }

        :global(.spin) {
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
};
