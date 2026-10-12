'use client';

import React from 'react';
import { Sidebar } from '../../components/Sidebar';
import { CameraGrid } from '../../components/CameraGrid';
import { Video, ShieldCheck } from 'lucide-react';

export default function MonitoringPage() {
  return (
    <div className="app-container">
      <Sidebar />
      <main className="main-content">
        <header className="top-header">
          <div className="header-left">
            <div className="header-title-group">
              <h1>
                <Video size={20} className="text-highlight" />
                Live CCTV Monitoring Matrix
              </h1>
              <p className="header-subtitle">
                Multi-Floor PG Video Feeds & RTSP Edge Aggregation
              </p>
            </div>
          </div>
          <div className="header-right">
            <div className="system-status-pill online">
              <span className="pulse-dot online" />
              <span>9 OF 9 CAMERAS STREAMING</span>
            </div>
          </div>
        </header>

        <div className="mock-notice-strip">
          <span>
            <strong>SIMULATED LIVE MATRIX</strong>: Feeds displayed are synthetic RTSP edge stream placeholders for layout testing.
          </span>
        </div>

        <div className="monitoring-scroll-area">
          <CameraGrid />
        </div>
      </main>

      <style jsx>{`
        .monitoring-scroll-area {
          flex: 1;
          overflow-y: auto;
        }
      `}</style>
    </div>
  );
}
