'use client';

import React, { useState, useEffect } from 'react';
import { Sidebar } from '../../components/Sidebar';
import { AlertList } from '../../components/AlertList';
import { IncidentDetail } from '../../components/IncidentDetail';
import { SecurityAlert, AlertFilterState, AlertStatus } from '../../types/alert';
import { initialMockAlerts, MOCK_DATASET_DISCLAIMER } from '../../data/mockAlerts';
import {
  ShieldAlert,
  Wifi,
  WifiOff,
  RefreshCw,
  SlidersHorizontal,
  Flame,
  AlertCircle,
  CheckCircle2,
  Clock,
  Layers,
} from 'lucide-react';

export default function SecurityAlertsPage() {
  const [alerts, setAlerts] = useState<SecurityAlert[]>(initialMockAlerts);
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(initialMockAlerts[0]?.id || null);

  // Filter state
  const [filters, setFilters] = useState<AlertFilterState>({
    status: 'all',
    severity: 'all',
    floor: 'all',
    searchQuery: '',
    startDate: '',
    endDate: '',
  });

  // State toggles for testing requirements (loading, error, offline)
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isError, setIsError] = useState<boolean>(false);
  const [isOffline, setIsOffline] = useState<boolean>(false);
  const [showStateTester, setShowStateTester] = useState<boolean>(false);

  // Selected alert object
  const selectedAlert = alerts.find((a) => a.id === selectedAlertId) || null;

  // Handle Review Action (Acknowledge, Confirm, Dismiss)
  const handleUpdateStatus = (alertId: string, newStatus: AlertStatus, notes: string) => {
    const timestampNow = new Date();
    const formattedTime = timestampNow.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const formattedDate = timestampNow.toLocaleDateString('en-GB', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    });

    setAlerts((prevAlerts) =>
      prevAlerts.map((alert) => {
        if (alert.id !== alertId) return alert;

        const updatedTimeline = [
          ...alert.timeline,
          {
            id: `t-${Date.now()}`,
            timestamp: formattedTime,
            title: `Incident Status set to ${newStatus.toUpperCase()}`,
            description: notes ? `Notes: ${notes}` : `Operator marked status as ${newStatus}.`,
            actor: 'Security Supervisor (Active Session)',
            type: 'user' as const,
          },
        ];

        return {
          ...alert,
          status: newStatus,
          reviewHistory: {
            reviewedBy: 'Security Supervisor (Active Session)',
            reviewedAt: `${formattedDate}, ${formattedTime}`,
            notes: notes || alert.reviewHistory.notes,
            lastStatusTransition: newStatus,
          },
          timeline: updatedTimeline,
        };
      })
    );
  };

  const handleFilterChange = (partial: Partial<AlertFilterState>) => {
    setFilters((prev) => ({ ...prev, ...partial }));
  };

  const handleResetFilters = () => {
    setFilters({
      status: 'all',
      severity: 'all',
      floor: 'all',
      searchQuery: '',
      startDate: '',
      endDate: '',
    });
  };

  // Quick stats
  const pendingCount = alerts.filter((a) => a.status === 'pending').length;
  const criticalCount = alerts.filter((a) => a.severity === 'critical').length;
  const confirmedCount = alerts.filter((a) => a.status === 'confirmed').length;

  return (
    <div className="app-container">
      {/* Sidebar Navigation */}
      <Sidebar
        pendingAlertCount={pendingCount}
        isOffline={isOffline}
        onToggleOffline={() => setIsOffline(!isOffline)}
      />

      <main className="main-content">
        {/* Top Header */}
        <header className="top-header" role="banner">
          <div className="header-left">
            <div className="header-title-group">
              <h1>
                <ShieldAlert size={20} className="text-highlight" />
                Security Alerts Command Center
              </h1>
              <p className="header-subtitle">
                Multi-Floor PG CCTV Video Analytics • Block A AI Surveillance
              </p>
            </div>
          </div>

          <div className="header-right">
            {/* Quick Metrics Bar */}
            <div className="header-stats-bar">
              <span className="stat-item pending" title="Pending Alerts">
                <Clock size={13} />
                <strong>{pendingCount}</strong> Pending
              </span>
              <span className="stat-item critical" title="Critical Severities">
                <Flame size={13} />
                <strong>{criticalCount}</strong> Critical
              </span>
              <span className="stat-item confirmed" title="Confirmed Incidents">
                <CheckCircle2 size={13} />
                <strong>{confirmedCount}</strong> Confirmed
              </span>
            </div>

            {/* Offline / Online System Status Indicator */}
            <div
              className={`system-status-pill ${isOffline ? 'offline' : 'online'}`}
              id="system-connectivity-badge"
            >
              <span className={`pulse-dot ${isOffline ? 'offline' : 'online'}`} />
              <span>{isOffline ? 'OFFLINE (DISCONNECTED)' : 'EDGE LIVE (30 FPS)'}</span>
            </div>

            {/* State Tester Toggle Button */}
            <button
              type="button"
              className="state-tester-toggle-btn"
              onClick={() => setShowStateTester(!showStateTester)}
              title="Test UI states: Loading, Error, Offline"
              id="btn-toggle-state-tester"
            >
              <SlidersHorizontal size={14} />
              <span>UI State Simulator</span>
            </button>
          </div>
        </header>

        {/* State Simulator Toolbar */}
        {showStateTester && (
          <div className="state-simulator-bar" role="region" aria-label="UI State Simulation Controls">
            <div className="sim-title">
              <strong>Simulate System States:</strong>
            </div>
            <div className="sim-actions">
              <button
                type="button"
                className={`sim-btn ${isLoading ? 'active' : ''}`}
                onClick={() => {
                  setIsLoading(true);
                  setTimeout(() => setIsLoading(false), 2000);
                }}
                id="btn-sim-loading"
              >
                <RefreshCw size={12} className={isLoading ? 'spin' : ''} />
                <span>Simulate Loading (2s)</span>
              </button>

              <button
                type="button"
                className={`sim-btn ${isError ? 'active' : ''}`}
                onClick={() => setIsError(!isError)}
                id="btn-sim-error"
              >
                <AlertCircle size={12} />
                <span>{isError ? 'Dismiss Simulated Error' : 'Trigger Edge Error State'}</span>
              </button>

              <button
                type="button"
                className={`sim-btn ${isOffline ? 'active' : ''}`}
                onClick={() => setIsOffline(!isOffline)}
                id="btn-sim-offline"
              >
                {isOffline ? <Wifi size={12} /> : <WifiOff size={12} />}
                <span>{isOffline ? 'Restore Online Stream' : 'Trigger Offline Mode'}</span>
              </button>
            </div>
          </div>
        )}

        {/* Mandatory Mock Dataset Disclaimer Strip */}
        <div className="mock-notice-strip" role="note">
          <span>
            <strong>SIMULATION DEMO DATASET</strong>: {MOCK_DATASET_DISCLAIMER}
          </span>
          <span className="api-ready-tag">API-READY SPEC: /api/v1/alerts</span>
        </div>

        {/* Alerts Page Layout: AlertList feed + IncidentDetail panel */}
        <div className="alerts-page-layout">
          <AlertList
            alerts={alerts}
            selectedAlertId={selectedAlertId}
            filters={filters}
            isLoading={isLoading}
            isError={isError}
            errorMessage="Edge CCTV WebSocket broker disconnected. (Simulated test failure)"
            isOffline={isOffline}
            onSelectAlert={(alert) => setSelectedAlertId(alert.id)}
            onFilterChange={handleFilterChange}
            onResetFilters={handleResetFilters}
            onRetry={() => setIsError(false)}
          />

          <IncidentDetail
            alert={selectedAlert}
            isLoading={isLoading}
            isOffline={isOffline}
            onClose={() => setSelectedAlertId(null)}
            onUpdateStatus={handleUpdateStatus}
          />
        </div>
      </main>

      <style jsx>{`
        .header-stats-bar {
          display: flex;
          align-items: center;
          gap: 12px;
          background: rgba(15, 23, 42, 0.7);
          padding: 4px 12px;
          border-radius: 6px;
          border: 1px solid var(--border-subtle);
          font-size: 0.76rem;
        }

        .stat-item {
          display: flex;
          align-items: center;
          gap: 5px;
        }

        .stat-item.pending {
          color: #fcd34d;
        }
        .stat-item.critical {
          color: #f87171;
        }
        .stat-item.confirmed {
          color: #6ee7b7;
        }

        .stat-item strong {
          font-family: var(--font-mono);
          color: #ffffff;
        }

        .state-tester-toggle-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 6px 10px;
          border-radius: 6px;
          font-size: 0.75rem;
          font-weight: 600;
          background: rgba(30, 41, 59, 0.7);
          color: var(--text-secondary);
          border: 1px solid var(--border-medium);
          transition: all 0.15s ease;
        }

        .state-tester-toggle-btn:hover {
          color: var(--text-primary);
          border-color: var(--accent-cyan);
        }

        .state-simulator-bar {
          background: #0f172a;
          border-bottom: 1px solid rgba(56, 189, 248, 0.25);
          padding: 8px 24px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          font-size: 0.78rem;
          color: #e2e8f0;
          animation: fadeIn 0.15s ease-out;
        }

        .sim-actions {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .sim-btn {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          padding: 4px 10px;
          border-radius: 4px;
          font-size: 0.72rem;
          background: rgba(30, 41, 59, 0.9);
          color: var(--text-secondary);
          border: 1px solid var(--border-medium);
          transition: all 0.15s ease;
        }

        .sim-btn:hover {
          color: var(--text-primary);
          border-color: rgba(148, 163, 184, 0.5);
        }

        .sim-btn.active {
          background: rgba(6, 182, 212, 0.2);
          border-color: var(--accent-cyan);
          color: #a5f3fc;
        }

        .api-ready-tag {
          font-family: var(--font-mono);
          font-size: 0.68rem;
          color: #94a3b8;
        }
      `}</style>
    </div>
  );
}
