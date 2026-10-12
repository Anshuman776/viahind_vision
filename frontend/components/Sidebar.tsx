'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  ShieldAlert,
  Video,
  Smartphone,
  BarChart3,
  Layers,
  Settings,
  Bell,
  Cpu,
  Building2,
  Wifi,
  WifiOff,
} from 'lucide-react';

interface SidebarProps {
  pendingAlertCount?: number;
  isOffline?: boolean;
  onToggleOffline?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  pendingAlertCount = 3,
  isOffline = false,
  onToggleOffline,
}) => {
  const pathname = usePathname();

  const navItems = [
    {
      href: '/alerts',
      label: 'Security Alerts',
      icon: <Bell size={18} />,
      badge: pendingAlertCount > 0 ? pendingAlertCount : null,
    },
    {
      href: '/monitoring',
      label: 'Live CCTV Matrix',
      icon: <Video size={18} />,
      badge: null,
    },
    {
      href: '/streamer',
      label: 'Phone Cam Streamer',
      icon: <Smartphone size={18} />,
      badge: null,
    },
    {
      href: '/overview',
      label: 'Analytics & Models',
      icon: <BarChart3 size={18} />,
      badge: null,
    },
  ];

  return (
    <aside className="sidebar-container" aria-label="Main Navigation Sidebar">
      {/* Brand Header */}
      <div className="brand-header">
        <div className="brand-logo-icon">
          <ShieldAlert size={22} className="logo-shield" />
        </div>
        <div className="brand-text-block">
          <span className="brand-title">VIAHIND VISION</span>
          <span className="brand-subtitle">PG CCTV AI Guard</span>
        </div>
      </div>

      {/* Facility Switcher */}
      <div className="facility-selector-box">
        <div className="facility-icon">
          <Building2 size={14} />
        </div>
        <div className="facility-meta">
          <span className="facility-label">Active PG Facility:</span>
          <span className="facility-name">Block A (4 Floors + Roof)</span>
        </div>
      </div>

      {/* Nav List */}
      <nav className="nav-menu" aria-label="Dashboard Views">
        <div className="nav-group-label">OPERATIONS</div>
        {navItems.map((item) => {
          const isActive = pathname === item.href || (item.href === '/alerts' && pathname === '/');
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`nav-item-link ${isActive ? 'active' : ''}`}
              id={`nav-link-${item.label.toLowerCase().replace(/[\s&]+/g, '-')}`}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
              {item.badge !== null && item.badge > 0 && (
                <span className="nav-badge-pill" title={`${item.badge} pending alerts`}>
                  {item.badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Edge AI Agent Telemetry Footer */}
      <div className="sidebar-footer">
        <div className="edge-agent-card">
          <div className="agent-status-row">
            <Cpu size={14} className="text-highlight" />
            <span className="agent-title">Edge AI Agent</span>
            <span className="agent-badge">v2.4-edge</span>
          </div>
          <div className="agent-details">
            <span className="agent-metric">FPS: 30.0 / stream</span>
            <span className="agent-metric">Inference: 32ms</span>
          </div>
        </div>

        {/* Offline Simulation Toggle for UX testing */}
        {onToggleOffline && (
          <button
            type="button"
            className={`offline-toggle-btn ${isOffline ? 'offline' : 'online'}`}
            onClick={onToggleOffline}
            title="Toggle between Online & Simulated Offline Mode for testing state requirements"
            id="btn-toggle-offline-mode"
          >
            {isOffline ? <WifiOff size={13} /> : <Wifi size={13} />}
            <span>{isOffline ? 'Offline Mode Active' : 'Edge Stream Connected'}</span>
          </button>
        )}
      </div>

      <style jsx>{`
        .sidebar-container {
          width: 250px;
          height: 100vh;
          background: var(--bg-sidebar);
          border-right: 1px solid var(--border-subtle);
          display: flex;
          flex-direction: column;
          flex-shrink: 0;
          z-index: 30;
        }

        .brand-header {
          height: 64px;
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 0 18px;
          border-bottom: 1px solid var(--border-subtle);
          background: rgba(15, 23, 42, 0.4);
        }

        .brand-logo-icon {
          width: 36px;
          height: 36px;
          border-radius: 8px;
          background: linear-gradient(135deg, rgba(6, 182, 212, 0.25) 0%, rgba(59, 130, 246, 0.25) 100%);
          border: 1px solid rgba(6, 182, 212, 0.4);
          display: flex;
          align-items: center;
          justify-content: center;
        }

        :global(.logo-shield) {
          color: var(--accent-cyan);
        }

        .brand-text-block {
          display: flex;
          flex-direction: column;
        }

        .brand-title {
          font-weight: 800;
          font-size: 0.88rem;
          letter-spacing: 0.04em;
          color: var(--text-primary);
        }

        .brand-subtitle {
          font-size: 0.68rem;
          color: var(--text-secondary);
        }

        .facility-selector-box {
          margin: 14px 14px 6px 14px;
          padding: 8px 10px;
          border-radius: 6px;
          background: rgba(15, 23, 42, 0.6);
          border: 1px solid var(--border-subtle);
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .facility-icon {
          color: var(--accent-blue);
        }

        .facility-meta {
          display: flex;
          flex-direction: column;
        }

        .facility-label {
          font-size: 0.65rem;
          color: var(--text-muted);
        }

        .facility-name {
          font-size: 0.76rem;
          font-weight: 600;
          color: var(--text-primary);
        }

        .nav-menu {
          flex: 1;
          padding: 14px 10px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .nav-group-label {
          font-size: 0.65rem;
          font-weight: 700;
          color: var(--text-muted);
          letter-spacing: 0.05em;
          padding: 6px 10px;
        }

        .nav-item-link {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 9px 12px;
          border-radius: 6px;
          font-size: 0.84rem;
          font-weight: 500;
          color: var(--text-secondary);
          transition: all 0.15s ease;
          position: relative;
        }

        .nav-item-link:hover {
          color: var(--text-primary);
          background: rgba(255, 255, 255, 0.05);
        }

        .nav-item-link.active {
          color: #ffffff;
          background: rgba(6, 182, 212, 0.14);
          border-left: 3px solid var(--accent-cyan);
          font-weight: 600;
        }

        .nav-icon {
          display: flex;
          align-items: center;
          justify-content: center;
          color: inherit;
        }

        .nav-label {
          flex: 1;
        }

        .nav-badge-pill {
          background: var(--accent-red);
          color: #ffffff;
          font-size: 0.68rem;
          font-weight: 700;
          padding: 1px 6px;
          border-radius: 999px;
          box-shadow: 0 0 8px rgba(239, 68, 68, 0.5);
        }

        .sidebar-footer {
          padding: 14px;
          border-top: 1px solid var(--border-subtle);
          display: flex;
          flex-direction: column;
          gap: 10px;
        }

        .edge-agent-card {
          background: rgba(15, 23, 42, 0.8);
          border: 1px solid var(--border-subtle);
          border-radius: 6px;
          padding: 8px 10px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .agent-status-row {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .agent-title {
          font-size: 0.74rem;
          font-weight: 600;
          color: var(--text-primary);
          flex: 1;
        }

        .agent-badge {
          font-family: var(--font-mono);
          font-size: 0.62rem;
          background: rgba(6, 182, 212, 0.15);
          color: var(--accent-cyan);
          padding: 1px 4px;
          border-radius: 3px;
        }

        .agent-details {
          display: flex;
          justify-content: space-between;
          font-size: 0.68rem;
          color: var(--text-muted);
          font-family: var(--font-mono);
        }

        .offline-toggle-btn {
          width: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 6px 10px;
          border-radius: 6px;
          font-size: 0.72rem;
          font-weight: 600;
          transition: all 0.15s ease;
        }

        .offline-toggle-btn.online {
          background: rgba(16, 185, 129, 0.1);
          color: #34d399;
          border: 1px solid rgba(16, 185, 129, 0.25);
        }
        .offline-toggle-btn.online:hover {
          background: rgba(16, 185, 129, 0.18);
        }

        .offline-toggle-btn.offline {
          background: rgba(239, 68, 68, 0.15);
          color: #fca5a5;
          border: 1px solid rgba(239, 68, 68, 0.35);
        }
        .offline-toggle-btn.offline:hover {
          background: rgba(239, 68, 68, 0.25);
        }
      `}</style>
    </aside>
  );
};
