'use client';

import React, { useMemo } from 'react';
import { SecurityAlert, AlertFilterState, AlertStatus, AlertSeverity, FloorIdentifier } from '../types/alert';
import { AlertCard } from './AlertCard';
import {
  Search,
  Filter,
  Calendar,
  Layers,
  RotateCcw,
  AlertTriangle,
  Inbox,
  ShieldCheck,
  Flame,
  CheckCircle2,
  Clock,
  XCircle,
} from 'lucide-react';

interface AlertListProps {
  alerts: SecurityAlert[];
  selectedAlertId: string | null;
  filters: AlertFilterState;
  isLoading: boolean;
  isError: boolean;
  errorMessage?: string;
  isOffline: boolean;
  onSelectAlert: (alert: SecurityAlert) => void;
  onFilterChange: (newFilters: Partial<AlertFilterState>) => void;
  onResetFilters: () => void;
  onRetry?: () => void;
}

export const AlertList: React.FC<AlertListProps> = ({
  alerts,
  selectedAlertId,
  filters,
  isLoading,
  isError,
  errorMessage,
  isOffline,
  onSelectAlert,
  onFilterChange,
  onResetFilters,
  onRetry,
}) => {
  // Compute counts for status tabs
  const counts = useMemo(() => {
    return {
      all: alerts.length,
      pending: alerts.filter((a) => a.status === 'pending').length,
      acknowledged: alerts.filter((a) => a.status === 'acknowledged').length,
      confirmed: alerts.filter((a) => a.status === 'confirmed').length,
      dismissed: alerts.filter((a) => a.status === 'dismissed').length,
    };
  }, [alerts]);

  // Filter alerts by status, severity, floor, search query, date
  const filteredAlerts = useMemo(() => {
    return alerts.filter((alert) => {
      // Status filter
      if (filters.status !== 'all' && alert.status !== filters.status) {
        return false;
      }

      // Severity filter
      if (filters.severity !== 'all' && alert.severity !== filters.severity) {
        return false;
      }

      // Floor filter
      if (filters.floor !== 'all' && alert.camera.floor !== filters.floor) {
        return false;
      }

      // Text search
      if (filters.searchQuery.trim()) {
        const query = filters.searchQuery.toLowerCase();
        const matchesEvent = alert.eventType.toLowerCase().includes(query);
        const matchesCam = alert.camera.id.toLowerCase().includes(query);
        const matchesLoc = alert.camera.location.toLowerCase().includes(query);
        const matchesFloor = alert.camera.floor.toLowerCase().includes(query);
        const matchesId = alert.id.toLowerCase().includes(query);
        if (!matchesEvent && !matchesCam && !matchesLoc && !matchesFloor && !matchesId) {
          return false;
        }
      }

      // Date range filter
      if (filters.startDate) {
        const alertDate = alert.timestamp.slice(0, 10);
        if (alertDate < filters.startDate) return false;
      }
      if (filters.endDate) {
        const alertDate = alert.timestamp.slice(0, 10);
        if (alertDate > filters.endDate) return false;
      }

      return true;
    });
  }, [alerts, filters]);

  const statusTabs: Array<{ id: AlertStatus | 'all'; label: string; count: number }> = [
    { id: 'all', label: 'All Alerts', count: counts.all },
    { id: 'pending', label: 'Pending', count: counts.pending },
    { id: 'acknowledged', label: 'Acknowledged', count: counts.acknowledged },
    { id: 'confirmed', label: 'Confirmed', count: counts.confirmed },
    { id: 'dismissed', label: 'Dismissed', count: counts.dismissed },
  ];

  return (
    <section className="alert-list-container" aria-label="Security Alerts Feed">
      {/* Status Filter Tabs */}
      <div className="status-tab-bar" role="tablist">
        {statusTabs.map((tab) => {
          const isActive = filters.status === tab.id;
          return (
            <button
              key={tab.id}
              role="tab"
              id={`tab-status-${tab.id}`}
              aria-selected={isActive}
              aria-controls="alert-card-feed"
              className={`status-tab-btn ${isActive ? 'active' : ''}`}
              onClick={() => onFilterChange({ status: tab.id })}
            >
              <span>{tab.label}</span>
              <span className={`tab-count ${tab.id}`}>{tab.count}</span>
            </button>
          );
        })}
      </div>

      {/* Filter and Search Bar */}
      <div className="filter-controls-card">
        {/* Search input */}
        <div className="search-bar-row">
          <div className="search-input-wrapper">
            <Search size={15} className="search-icon text-muted" />
            <input
              type="text"
              id="input-alert-search"
              placeholder="Search camera, floor, event type or alert ID..."
              value={filters.searchQuery}
              onChange={(e) => onFilterChange({ searchQuery: e.target.value })}
              aria-label="Search alerts"
            />
            {filters.searchQuery && (
              <button
                type="button"
                className="clear-search-btn"
                onClick={() => onFilterChange({ searchQuery: '' })}
                aria-label="Clear search input"
              >
                ×
              </button>
            )}
          </div>
        </div>

        {/* Filter Dropdowns Grid */}
        <div className="dropdowns-row">
          {/* Severity selector */}
          <div className="filter-select-group">
            <label htmlFor="select-severity" className="filter-label">
              Severity:
            </label>
            <select
              id="select-severity"
              value={filters.severity}
              onChange={(e) =>
                onFilterChange({ severity: e.target.value as AlertSeverity | 'all' })
              }
              aria-label="Filter by Severity"
            >
              <option value="all">All Severities</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </div>

          {/* Floor selector */}
          <div className="filter-select-group">
            <label htmlFor="select-floor" className="filter-label">
              Floor:
            </label>
            <select
              id="select-floor"
              value={filters.floor}
              onChange={(e) =>
                onFilterChange({ floor: e.target.value as FloorIdentifier | 'all' })
              }
              aria-label="Filter by PG Floor"
            >
              <option value="all">All Floors</option>
              <option value="Basement">Basement</option>
              <option value="Ground Floor">Ground Floor</option>
              <option value="Floor 1">Floor 1 (Boys Wing)</option>
              <option value="Floor 2">Floor 2 (Girls Wing)</option>
              <option value="Floor 3">Floor 3 (Study Lounge)</option>
              <option value="Rooftop">Rooftop Terrace</option>
            </select>
          </div>

          {/* Date filter inputs */}
          <div className="filter-date-group">
            <label htmlFor="input-date-start" className="filter-label">
              Date:
            </label>
            <input
              type="date"
              id="input-date-start"
              value={filters.startDate}
              onChange={(e) => onFilterChange({ startDate: e.target.value })}
              aria-label="Filter by Start Date"
              title="From Date"
            />
          </div>

          {/* Reset Filters button */}
          <button
            type="button"
            id="btn-reset-filters"
            className="reset-filters-btn"
            onClick={onResetFilters}
            title="Reset all active filters"
            aria-label="Reset all filters"
          >
            <RotateCcw size={13} />
            <span>Reset</span>
          </button>
        </div>
      </div>

      {/* Error state */}
      {isError && (
        <div className="alert-error-banner" role="alert" id="alert-feed-error">
          <AlertTriangle size={18} className="error-icon" />
          <div className="error-body">
            <strong>Failed to sync alert stream</strong>
            <p>{errorMessage || 'Network timeout or edge broker connection failure.'}</p>
          </div>
          {onRetry && (
            <button type="button" className="retry-btn" onClick={onRetry} id="btn-retry-alerts">
              Retry
            </button>
          )}
        </div>
      )}

      {/* Loading State: Skeleton Shimmers */}
      {isLoading && (
        <div className="skeleton-cards-list" id="skeleton-cards-list">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="card-skeleton shimmer" />
          ))}
        </div>
      )}

      {/* Empty State */}
      {!isLoading && !isError && filteredAlerts.length === 0 && (
        <div className="alert-feed-empty" id="alert-feed-empty">
          <Inbox size={36} className="text-muted" />
          <h4 className="empty-title">No Security Alerts Found</h4>
          <p className="empty-subtitle">
            No incidents matched your current filters. Adjust your criteria or clear filters.
          </p>
          <button
            type="button"
            className="empty-reset-btn"
            onClick={onResetFilters}
            id="btn-empty-clear-filters"
          >
            Clear All Filters
          </button>
        </div>
      )}

      {/* Active Alerts Cards Feed */}
      {!isLoading && !isError && filteredAlerts.length > 0 && (
        <div className="alert-cards-scroll-feed" id="alert-card-feed" role="feed">
          <div className="feed-counter-header">
            <span>
              Showing <strong>{filteredAlerts.length}</strong> of {alerts.length} incidents
            </span>
          </div>

          {filteredAlerts.map((alert) => (
            <AlertCard
              key={alert.id}
              alert={alert}
              isSelected={selectedAlertId === alert.id}
              onSelect={onSelectAlert}
            />
          ))}
        </div>
      )}

      <style jsx>{`
        .alert-list-container {
          display: flex;
          flex-direction: column;
          height: 100%;
          background: rgba(11, 15, 25, 0.6);
          border-right: 1px solid var(--border-subtle);
          overflow: hidden;
        }

        /* Status Tabs */
        .status-tab-bar {
          display: flex;
          overflow-x: auto;
          background: rgba(15, 23, 42, 0.7);
          border-bottom: 1px solid var(--border-subtle);
          padding: 4px 8px 0 8px;
          gap: 4px;
        }

        .status-tab-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px 12px;
          font-size: 0.8rem;
          font-weight: 600;
          color: var(--text-secondary);
          border-bottom: 2px solid transparent;
          border-radius: 6px 6px 0 0;
          white-space: nowrap;
          transition: all 0.15s ease;
        }

        .status-tab-btn:hover {
          color: var(--text-primary);
          background: rgba(255, 255, 255, 0.04);
        }

        .status-tab-btn.active {
          color: var(--accent-cyan);
          border-bottom-color: var(--accent-cyan);
          background: rgba(6, 182, 212, 0.08);
        }

        .tab-count {
          font-size: 0.68rem;
          font-family: var(--font-mono);
          padding: 1px 6px;
          border-radius: 999px;
          background: rgba(30, 41, 59, 0.9);
          color: var(--text-muted);
        }
        .status-tab-btn.active .tab-count {
          background: rgba(6, 182, 212, 0.25);
          color: #a5f3fc;
        }
        .tab-count.pending {
          color: #fcd34d;
        }
        .tab-count.confirmed {
          color: #6ee7b7;
        }

        /* Filter Controls */
        .filter-controls-card {
          padding: 12px 14px;
          background: rgba(15, 23, 42, 0.85);
          border-bottom: 1px solid var(--border-subtle);
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .search-bar-row {
          width: 100%;
        }

        .search-input-wrapper {
          position: relative;
          display: flex;
          align-items: center;
          width: 100%;
        }

        :global(.search-icon) {
          position: absolute;
          left: 10px;
          pointer-events: none;
        }

        .search-input-wrapper input {
          width: 100%;
          padding-left: 32px;
          padding-right: 26px;
          font-size: 0.82rem;
          height: 34px;
          background: rgba(11, 15, 25, 0.8);
        }

        .clear-search-btn {
          position: absolute;
          right: 8px;
          color: var(--text-muted);
          font-size: 1.1rem;
          line-height: 1;
        }

        .dropdowns-row {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
        }

        .filter-select-group,
        .filter-date-group {
          display: flex;
          align-items: center;
          gap: 5px;
          flex: 1;
          min-width: 110px;
        }

        .filter-label {
          font-size: 0.72rem;
          color: var(--text-muted);
        }

        .filter-select-group select,
        .filter-date-group input {
          width: 100%;
          height: 30px;
          padding: 4px 8px;
          font-size: 0.76rem;
          background: rgba(11, 15, 25, 0.8);
        }

        .reset-filters-btn {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 5px 9px;
          font-size: 0.73rem;
          border-radius: 4px;
          background: rgba(30, 41, 59, 0.7);
          color: var(--text-secondary);
          border: 1px solid var(--border-medium);
          transition: all 0.15s ease;
          height: 30px;
        }

        .reset-filters-btn:hover {
          color: var(--text-primary);
          border-color: rgba(148, 163, 184, 0.4);
        }

        /* Error state */
        .alert-error-banner {
          margin: 12px;
          background: rgba(239, 68, 68, 0.12);
          border: 1px solid rgba(239, 68, 68, 0.35);
          border-radius: 6px;
          padding: 12px;
          display: flex;
          align-items: center;
          gap: 10px;
          color: #fca5a5;
        }

        .error-body {
          flex: 1;
          font-size: 0.78rem;
        }

        .retry-btn {
          background: #ef4444;
          color: #ffffff;
          padding: 4px 10px;
          border-radius: 4px;
          font-size: 0.75rem;
          font-weight: 600;
        }

        /* Skeletons */
        .skeleton-cards-list {
          padding: 12px;
          display: flex;
          flex-direction: column;
          gap: 10px;
        }

        .card-skeleton {
          height: 100px;
          border-radius: 8px;
          background: rgba(30, 41, 59, 0.3);
        }

        .shimmer {
          animation: shimmerList 1.5s infinite linear;
          background: linear-gradient(
            90deg,
            rgba(30, 41, 59, 0.3) 0%,
            rgba(51, 65, 85, 0.5) 50%,
            rgba(30, 41, 59, 0.3) 100%
          );
          background-size: 200% 100%;
        }

        @keyframes shimmerList {
          0% { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }

        /* Empty state */
        .alert-feed-empty {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 32px 20px;
          text-align: center;
          gap: 10px;
        }

        .empty-title {
          font-size: 0.95rem;
          font-weight: 600;
          color: var(--text-primary);
        }

        .empty-subtitle {
          font-size: 0.8rem;
          color: var(--text-secondary);
          max-width: 280px;
          line-height: 1.4;
        }

        .empty-reset-btn {
          margin-top: 6px;
          padding: 6px 14px;
          background: rgba(59, 130, 246, 0.2);
          border: 1px solid rgba(59, 130, 246, 0.4);
          color: #93c5fd;
          border-radius: 6px;
          font-size: 0.8rem;
          font-weight: 600;
        }

        /* Active Feed */
        .alert-cards-scroll-feed {
          flex: 1;
          overflow-y: auto;
          padding: 12px;
          display: flex;
          flex-direction: column;
          gap: 10px;
        }

        .feed-counter-header {
          font-size: 0.72rem;
          color: var(--text-muted);
          padding: 0 4px;
        }
      `}</style>
    </section>
  );
};
