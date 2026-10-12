'use client';

import React from 'react';
import { Sidebar } from '../../components/Sidebar';
import {
  BarChart3,
  Cpu,
  Shield,
  Activity,
  Layers,
  CheckCircle,
  AlertTriangle,
  Flame,
} from 'lucide-react';

export default function OverviewPage() {
  return (
    <div className="app-container">
      <Sidebar />
      <main className="main-content">
        <header className="top-header">
          <div className="header-left">
            <div className="header-title-group">
              <h1>
                <BarChart3 size={20} className="text-highlight" />
                CCTV Analytics & Fight Classifier Telemetry
              </h1>
              <p className="header-subtitle">
                System Health, Edge AI Performance & Facility Alert Distribution
              </p>
            </div>
          </div>
          <div className="header-right">
            <div className="system-status-pill online">
              <span className="pulse-dot online" />
              <span>MODEL INFERENCE ACTIVE (v2.4.1)</span>
            </div>
          </div>
        </header>

        <div className="mock-notice-strip">
          <span>
            <strong>TELEMETRY OVERVIEW</strong>: Aggregated synthetic model metrics across PG Block A facility floors.
          </span>
        </div>

        <div className="overview-content">
          {/* Metrics summary cards */}
          <div className="stats-cards-grid">
            <div className="stat-card">
              <div className="stat-card-top">
                <span className="stat-label">Total Cameras</span>
                <Shield size={16} className="text-highlight" />
              </div>
              <div className="stat-value">9 / 9</div>
              <span className="stat-sub">100% Floor Coverage</span>
            </div>

            <div className="stat-card">
              <div className="stat-card-top">
                <span className="stat-label">Classifier Avg Latency</span>
                <Cpu size={16} className="text-highlight" />
              </div>
              <div className="stat-value">31.4 ms</div>
              <span className="stat-sub">MobileNetV3 on NVIDIA Jetson Edge</span>
            </div>

            <div className="stat-card">
              <div className="stat-card-top">
                <span className="stat-label">Model Accuracy Benchmark</span>
                <Activity size={16} className="text-highlight" />
              </div>
              <div className="stat-value">96.8%</div>
              <span className="stat-sub">F1-Score on Fight Detection Dataset</span>
            </div>

            <div className="stat-card">
              <div className="stat-card-top">
                <span className="stat-label">Critical Alerts (24h)</span>
                <Flame size={16} className="card-crit-icon" />
              </div>
              <div className="stat-value text-red">2 Active</div>
              <span className="stat-sub">Requires supervisor review</span>
            </div>
          </div>

          {/* Breakdown by floor */}
          <div className="floor-breakdown-section">
            <h2 className="section-heading">Facility Floor Alert Distribution (Block A)</h2>
            <div className="floor-bars-list">
              <div className="floor-bar-item">
                <div className="floor-meta">
                  <span className="floor-title">Floor 1 (Boys Wing)</span>
                  <span className="floor-count">3 Incidents (1 Altercation, 2 Movement)</span>
                </div>
                <div className="bar-track">
                  <div className="bar-fill crit" style={{ width: '45%' }} />
                </div>
              </div>

              <div className="floor-bar-item">
                <div className="floor-meta">
                  <span className="floor-title">Floor 2 (Girls Wing)</span>
                  <span className="floor-count">1 Incident (Loitering)</span>
                </div>
                <div className="bar-track">
                  <div className="bar-fill high" style={{ width: '20%' }} />
                </div>
              </div>

              <div className="floor-bar-item">
                <div className="floor-meta">
                  <span className="floor-title">Rooftop Terrace</span>
                  <span className="floor-count">1 Incident (Perimeter Breach)</span>
                </div>
                <div className="bar-track">
                  <div className="bar-fill crit" style={{ width: '25%' }} />
                </div>
              </div>

              <div className="floor-bar-item">
                <div className="floor-meta">
                  <span className="floor-title">Ground Floor Reception</span>
                  <span className="floor-count">1 Incident (Tailgating)</span>
                </div>
                <div className="bar-track">
                  <div className="bar-fill med" style={{ width: '15%' }} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>

      <style jsx>{`
        .overview-content {
          flex: 1;
          overflow-y: auto;
          padding: 24px;
          display: flex;
          flex-direction: column;
          gap: 24px;
        }

        .stats-cards-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap: 16px;
        }

        .stat-card {
          background: var(--bg-surface);
          border: 1px solid var(--border-subtle);
          border-radius: 8px;
          padding: 18px 20px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .stat-card-top {
          display: flex;
          align-items: center;
          justify-content: space-between;
        }

        .stat-label {
          font-size: 0.78rem;
          color: var(--text-secondary);
        }

        .stat-value {
          font-size: 1.6rem;
          font-weight: 800;
          font-family: var(--font-mono);
          color: var(--text-primary);
        }

        .stat-value.text-red {
          color: #f87171;
        }

        :global(.card-crit-icon) {
          color: #ef4444;
        }

        .stat-sub {
          font-size: 0.72rem;
          color: var(--text-muted);
        }

        .floor-breakdown-section {
          background: var(--bg-surface);
          border: 1px solid var(--border-subtle);
          border-radius: 8px;
          padding: 20px;
        }

        .section-heading {
          font-size: 1rem;
          font-weight: 700;
          color: var(--text-primary);
          margin-bottom: 18px;
        }

        .floor-bars-list {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .floor-bar-item {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .floor-meta {
          display: flex;
          align-items: center;
          justify-content: space-between;
          font-size: 0.8rem;
        }

        .floor-title {
          font-weight: 600;
          color: var(--text-primary);
        }

        .floor-count {
          color: var(--text-secondary);
          font-family: var(--font-mono);
          font-size: 0.75rem;
        }

        .bar-track {
          height: 8px;
          background: rgba(30, 41, 59, 0.7);
          border-radius: 999px;
          overflow: hidden;
        }

        .bar-fill {
          height: 100%;
          border-radius: 999px;
        }
        .bar-fill.crit {
          background: #ef4444;
        }
        .bar-fill.high {
          background: #f59e0b;
        }
        .bar-fill.med {
          background: #3b82f6;
        }
      `}</style>
    </div>
  );
}
