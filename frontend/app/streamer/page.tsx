'use client';

import React, { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import {
  Smartphone,
  Video,
  VideoOff,
  SwitchCamera,
  Layers,
  MapPin,
  Wifi,
  WifiOff,
  ShieldAlert,
  ArrowLeft,
  Flame,
  CheckCircle2,
  Copy,
  Info,
} from 'lucide-react';

export default function PhoneStreamerPage() {
  const [cameraId, setCameraId] = useState('CAM-PHONE-01');
  const [cameraName, setCameraName] = useState('Phone Camera 1');
  const [floor, setFloor] = useState('Floor 1');
  const [location, setLocation] = useState('Corridor / Entrance');
  const [facingMode, setFacingMode] = useState<'environment' | 'user'>('environment');

  const [isStreaming, setIsStreaming] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [fps, setFps] = useState(0);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [copiedLink, setCopiedLink] = useState(false);
  const [alertTriggered, setAlertTriggered] = useState(false);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const frameIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const fpsCounterRef = useRef<number>(0);

  // Parse query parameters on load (e.g. ?id=CAM-F1-PHONE-01&floor=Floor%201&name=...&loc=...)
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const qId = params.get('id');
    const qName = params.get('name');
    const qFloor = params.get('floor');
    const qLoc = params.get('location') || params.get('loc');

    if (qId) setCameraId(qId);
    if (qName) setCameraName(qName);
    if (qFloor) setFloor(qFloor);
    if (qLoc) setLocation(qLoc);
  }, []);

  // Initialize camera preview
  const startCamera = async () => {
    try {
      setErrorMsg(null);
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: facingMode },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      });

      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play();
      }
    } catch (err: any) {
      setErrorMsg(
        err.message || 'Camera access denied or unavailable. Please grant camera permission.'
      );
    }
  };

  useEffect(() => {
    startCamera();
    return () => {
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }
      if (socketRef.current) {
        socketRef.current.close();
      }
      if (frameIntervalRef.current) {
        clearInterval(frameIntervalRef.current);
      }
    };
  }, [facingMode]);

  // Flip camera between front & back
  const toggleFacingMode = () => {
    setFacingMode((prev) => (prev === 'environment' ? 'user' : 'environment'));
  };

  // Start broadcasting live to backend
  const startBroadcasting = async () => {
    try {
      setErrorMsg(null);

      // 1. Register with backend REST API
      const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
      const backendUrl =
        typeof window !== 'undefined' && window.location.hostname !== 'localhost'
          ? `http://${window.location.hostname}:8000`
          : process.env.NEXT_PUBLIC_API_URL?.replace('/api/v1', '') || 'http://localhost:8000';

      try {
        await fetch(`${backendUrl}/api/v1/cameras/phone`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            id: cameraId,
            name: cameraName,
            floor,
            location,
            stream_type: 'browser_stream',
          }),
        });
      } catch (e) {
        console.warn('Backend REST registration warning (continuing with direct WS):', e);
      }

      // 2. Open WebSocket connection
      const wsHost =
        typeof window !== 'undefined'
          ? window.location.hostname
          : 'localhost';
      const wsPort = '8000';
      const wsUrl = `ws://${wsHost}:${wsPort}/ws/stream/${cameraId}`;

      const socket = new WebSocket(wsUrl);
      socketRef.current = socket;

      socket.onopen = () => {
        setIsConnected(true);
        setIsStreaming(true);

        // Frame capture loop: send 15 frames per second
        const canvas = canvasRef.current || document.createElement('canvas');
        canvasRef.current = canvas;
        const ctx = canvas.getContext('2d');

        frameIntervalRef.current = setInterval(() => {
          if (!videoRef.current || socket.readyState !== WebSocket.OPEN) return;

          canvas.width = 480;
          canvas.height = 360;
          ctx?.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);

          const frameBase64 = canvas.toDataURL('image/jpeg', 0.6);

          socket.send(
            JSON.stringify({
              image: frameBase64,
              camera_id: cameraId,
              floor,
              location,
            })
          );

          fpsCounterRef.current += 1;
        }, 66); // ~15 FPS
      };

      socket.onerror = (e) => {
        setErrorMsg('WebSocket connection to backend failed. Make sure backend is running on port 8000.');
        stopBroadcasting();
      };

      socket.onclose = () => {
        setIsConnected(false);
        setIsStreaming(false);
      };
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to start phone stream');
    }
  };

  const stopBroadcasting = () => {
    if (frameIntervalRef.current) {
      clearInterval(frameIntervalRef.current);
    }
    if (socketRef.current) {
      socketRef.current.close();
    }
    setIsStreaming(false);
    setIsConnected(false);
    setFps(0);
  };

  // FPS calculation timer
  useEffect(() => {
    const timer = setInterval(() => {
      setFps(fpsCounterRef.current);
      fpsCounterRef.current = 0;
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Trigger test altercation simulation from the phone
  const triggerTestAlert = () => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        JSON.stringify({
          trigger_alert: true,
          event_type: 'Physical Altercation',
          severity: 'critical',
        })
      );
      setAlertTriggered(true);
      setTimeout(() => setAlertTriggered(false), 3000);
    }
  };

  const copyMobileLink = () => {
    const url = window.location.href;
    navigator.clipboard.writeText(url);
    setCopiedLink(true);
    setTimeout(() => setCopiedLink(false), 2500);
  };

  return (
    <div className="streamer-page-wrapper">
      {/* Top Header */}
      <header className="streamer-header">
        <Link href="/monitoring" className="back-link">
          <ArrowLeft size={16} />
          <span>Exit to Dashboard</span>
        </Link>
        <div className="streamer-title-group">
          <Smartphone size={18} className="text-highlight" />
          <h1>Phone Camera CCTV Streamer</h1>
        </div>
        <div className={`status-pill ${isConnected ? 'live' : 'idle'}`}>
          <span className={`dot ${isConnected ? 'live' : 'idle'}`} />
          <span>{isConnected ? 'BROADCASTING LIVE' : 'PREVIEW READY'}</span>
        </div>
      </header>

      {/* Main Container */}
      <main className="streamer-content">
        {errorMsg && (
          <div className="error-banner" role="alert">
            <Info size={16} />
            <span>{errorMsg}</span>
          </div>
        )}

        <div className="streamer-grid">
          {/* Left: Live Viewfinder */}
          <div className="viewfinder-card">
            <div className="viewfinder-hud-top">
              <span className="rec-indicator">
                <span className={`rec-dot ${isStreaming ? 'active' : ''}`} />
                {isStreaming ? 'REC • STREAMING' : 'CAMERA STANDBY'}
              </span>
              <span className="hud-cam-id">{cameraId}</span>
              <span className="hud-fps">{fps} FPS</span>
            </div>

            <video
              ref={videoRef}
              playsInline
              muted
              className="viewfinder-video"
              aria-label="Smartphone camera viewfinder"
            />

            {/* AI Bounding Box Overlay Simulation */}
            {isStreaming && (
              <div className="ai-overlay-box">
                <span className="ai-box-label">LIVE CCTV FEED</span>
              </div>
            )}

            <div className="viewfinder-hud-bottom">
              <span className="hud-floor-tag">
                {floor} • {location}
              </span>
              <button
                type="button"
                className="flip-cam-btn"
                onClick={toggleFacingMode}
                title="Flip between front and rear phone camera"
                id="btn-flip-camera"
              >
                <SwitchCamera size={16} />
                <span>Flip Cam ({facingMode})</span>
              </button>
            </div>
          </div>

          {/* Right: Broadcast Configuration & Actions */}
          <div className="config-card">
            <h2 className="config-heading">Camera Placement & PG Details</h2>
            <p className="config-desc">
              Mount your phone securely in any PG corridor, lobby, or room. This feed streams straight into the VIAHIND Vision command center.
            </p>

            {/* Quick Presets for Multi-Floor Cameras */}
            {!isStreaming && (
              <div className="presets-box">
                <span className="presets-label">⚡ Quick Presets (Tap to configure):</span>
                <div className="preset-buttons-row">
                  <button
                    type="button"
                    className="preset-btn"
                    onClick={() => {
                      setCameraId('CAM-F1-PHONE-01');
                      setCameraName('Floor 1 Phone Cam - East');
                      setFloor('Floor 1');
                      setLocation('Corridor East near Room 102');
                    }}
                  >
                    F1 East
                  </button>
                  <button
                    type="button"
                    className="preset-btn"
                    onClick={() => {
                      setCameraId('CAM-F1-PHONE-02');
                      setCameraName('Floor 1 Phone Cam - West');
                      setFloor('Floor 1');
                      setLocation('Corridor West near Room 115');
                    }}
                  >
                    F1 West
                  </button>
                  <button
                    type="button"
                    className="preset-btn"
                    onClick={() => {
                      setCameraId('CAM-F1-PHONE-03');
                      setCameraName('Floor 1 Phone Cam - Stairs');
                      setFloor('Floor 1');
                      setLocation('North Staircase A');
                    }}
                  >
                    F1 Stairs
                  </button>
                  <button
                    type="button"
                    className="preset-btn"
                    onClick={() => {
                      setCameraId('CAM-F2-PHONE-01');
                      setCameraName('Floor 2 Phone Cam - Hall');
                      setFloor('Floor 2');
                      setLocation('Girls Wing Central Corridor');
                    }}
                  >
                    Floor 2
                  </button>
                  <button
                    type="button"
                    className="preset-btn"
                    onClick={() => {
                      setCameraId('CAM-G-PHONE-01');
                      setCameraName('Ground Phone Cam - Entry');
                      setFloor('Ground Floor');
                      setLocation('Main Reception & Entry');
                    }}
                  >
                    Ground
                  </button>
                </div>
              </div>
            )}

            <div className="inputs-group">
              <div className="input-field">
                <label htmlFor="input-phone-cam-id">Camera Identifier</label>
                <input
                  id="input-phone-cam-id"
                  type="text"
                  value={cameraId}
                  onChange={(e) => setCameraId(e.target.value)}
                  disabled={isStreaming}
                />
              </div>

              <div className="input-field">
                <label htmlFor="input-phone-cam-name">Display Name</label>
                <input
                  id="input-phone-cam-name"
                  type="text"
                  value={cameraName}
                  onChange={(e) => setCameraName(e.target.value)}
                  disabled={isStreaming}
                />
              </div>

              <div className="input-field">
                <label htmlFor="select-phone-floor">Assigned PG Floor</label>
                <select
                  id="select-phone-floor"
                  value={floor}
                  onChange={(e) => setFloor(e.target.value)}
                  disabled={isStreaming}
                >
                  <option value="Ground Floor">Ground Floor</option>
                  <option value="Floor 1">Floor 1 (Boys Wing)</option>
                  <option value="Floor 2">Floor 2 (Girls Wing)</option>
                  <option value="Floor 3">Floor 3 (Study Lounge)</option>
                  <option value="Basement">Basement Parking</option>
                  <option value="Rooftop">Rooftop Terrace</option>
                </select>
              </div>

              <div className="input-field">
                <label htmlFor="input-phone-location">Specific Location</label>
                <input
                  id="input-phone-location"
                  type="text"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  disabled={isStreaming}
                />
              </div>
            </div>

            {/* Broadcast action button */}
            <div className="broadcast-buttons-box">
              {!isStreaming ? (
                <button
                  type="button"
                  className="start-broadcast-btn"
                  onClick={startBroadcasting}
                  id="btn-start-broadcast"
                >
                  <Video size={18} />
                  <span>Start Live CCTV Broadcast</span>
                </button>
              ) : (
                <button
                  type="button"
                  className="stop-broadcast-btn"
                  onClick={stopBroadcasting}
                  id="btn-stop-broadcast"
                >
                  <VideoOff size={18} />
                  <span>Stop Broadcast</span>
                </button>
              )}

              {/* Test incident trigger button */}
              {isStreaming && (
                <button
                  type="button"
                  className="trigger-fight-btn"
                  onClick={triggerTestAlert}
                  id="btn-trigger-fight-alert"
                  title="Simulate a fight or motion detected on this phone camera feed"
                >
                  <Flame size={16} />
                  <span>
                    {alertTriggered ? 'Alert Dispatched to Console!' : 'Simulate Altercation Detection'}
                  </span>
                </button>
              )}
            </div>

            {/* Mobile Link Sharing Info */}
            <div className="mobile-share-card">
              <div className="share-header">
                <Smartphone size={14} className="text-highlight" />
                <span className="share-title">Open on your Mobile Phone:</span>
              </div>
              <p className="share-desc">
                Connect your phone to the same Wi-Fi network and open:
              </p>
              <div className="url-copy-box">
                <code className="url-code">
                  {typeof window !== 'undefined' ? window.location.href : 'http://localhost:3000/streamer'}
                </code>
                <button
                  type="button"
                  className="copy-url-btn"
                  onClick={copyMobileLink}
                  aria-label="Copy streamer link"
                >
                  {copiedLink ? <CheckCircle2 size={14} className="text-green" /> : <Copy size={14} />}
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>

      <style jsx>{`
        .streamer-page-wrapper {
          min-height: 100vh;
          background: #080b11;
          color: #f8fafc;
          display: flex;
          flex-direction: column;
        }

        .streamer-header {
          height: 60px;
          background: rgba(11, 15, 25, 0.9);
          border-bottom: 1px solid rgba(148, 163, 184, 0.15);
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0 20px;
        }

        .back-link {
          display: flex;
          align-items: center;
          gap: 6px;
          color: #94a3b8;
          font-size: 0.82rem;
          font-weight: 500;
          transition: color 0.15s ease;
        }
        .back-link:hover {
          color: #ffffff;
        }

        .streamer-title-group {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .streamer-title-group h1 {
          font-size: 1.05rem;
          font-weight: 700;
          color: #f8fafc;
        }

        .status-pill {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          font-size: 0.72rem;
          font-weight: 700;
          padding: 4px 10px;
          border-radius: 999px;
        }
        .status-pill.idle {
          background: rgba(148, 163, 184, 0.15);
          color: #cbd5e1;
        }
        .status-pill.live {
          background: rgba(16, 185, 129, 0.18);
          color: #34d399;
          border: 1px solid rgba(16, 185, 129, 0.35);
        }

        .dot {
          width: 7px;
          height: 7px;
          border-radius: 50%;
        }
        .dot.idle {
          background: #94a3b8;
        }
        .dot.live {
          background: #10b981;
          box-shadow: 0 0 8px #10b981;
          animation: pulseGreen 1.5s infinite;
        }

        @keyframes pulseGreen {
          0% { transform: scale(0.9); }
          50% { transform: scale(1.2); }
          100% { transform: scale(0.9); }
        }

        .streamer-content {
          flex: 1;
          max-width: 1200px;
          width: 100%;
          margin: 0 auto;
          padding: 24px 20px;
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .error-banner {
          background: rgba(239, 68, 68, 0.15);
          border: 1px solid rgba(239, 68, 68, 0.35);
          color: #fca5a5;
          padding: 10px 14px;
          border-radius: 6px;
          font-size: 0.8rem;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .streamer-grid {
          display: grid;
          grid-template-columns: 1fr 420px;
          gap: 20px;
        }

        @media (max-width: 900px) {
          .streamer-grid {
            grid-template-columns: 1fr;
          }
        }

        /* Viewfinder */
        .viewfinder-card {
          background: #000000;
          border: 1px solid rgba(148, 163, 184, 0.2);
          border-radius: 10px;
          position: relative;
          min-height: 440px;
          display: flex;
          flex-direction: column;
          overflow: hidden;
          box-shadow: 0 12px 30px rgba(0, 0, 0, 0.6);
        }

        .viewfinder-video {
          width: 100%;
          height: 100%;
          object-fit: cover;
          flex: 1;
          background: #050811;
        }

        .viewfinder-hud-top {
          position: absolute;
          top: 12px;
          left: 14px;
          right: 14px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          z-index: 10;
          font-family: var(--font-mono);
          font-size: 0.75rem;
          color: #f1f5f9;
          text-shadow: 0 1px 4px rgba(0, 0, 0, 0.9);
        }

        .rec-indicator {
          display: flex;
          align-items: center;
          gap: 6px;
          background: rgba(0, 0, 0, 0.7);
          padding: 3px 8px;
          border-radius: 4px;
        }

        .rec-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #94a3b8;
        }
        .rec-dot.active {
          background: #ef4444;
          animation: blinkRec 1s infinite;
        }

        @keyframes blinkRec {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.2; }
        }

        .hud-cam-id,
        .hud-fps {
          background: rgba(0, 0, 0, 0.7);
          padding: 3px 8px;
          border-radius: 4px;
        }

        .viewfinder-hud-bottom {
          position: absolute;
          bottom: 12px;
          left: 14px;
          right: 14px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          z-index: 10;
        }

        .hud-floor-tag {
          background: rgba(0, 0, 0, 0.7);
          padding: 3px 10px;
          border-radius: 4px;
          font-size: 0.75rem;
          color: #f8fafc;
        }

        .flip-cam-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: rgba(15, 23, 42, 0.85);
          border: 1px solid rgba(148, 163, 184, 0.3);
          color: #ffffff;
          padding: 5px 10px;
          border-radius: 6px;
          font-size: 0.74rem;
          cursor: pointer;
        }

        .ai-overlay-box {
          position: absolute;
          top: 30%;
          left: 25%;
          width: 50%;
          height: 40%;
          border: 2px dashed rgba(6, 182, 212, 0.8);
          pointer-events: none;
          display: flex;
          align-items: flex-start;
          justify-content: flex-start;
        }

        .ai-box-label {
          background: #06b6d4;
          color: #000000;
          font-size: 0.6rem;
          font-weight: 800;
          font-family: var(--font-mono);
          padding: 1px 4px;
        }

        /* Config Card */
        .config-card {
          background: rgba(15, 23, 42, 0.8);
          border: 1px solid rgba(148, 163, 184, 0.15);
          border-radius: 10px;
          padding: 20px;
          display: flex;
          flex-direction: column;
          gap: 14px;
        }

        .config-heading {
          font-size: 0.95rem;
          font-weight: 700;
          color: #f8fafc;
        }

        .config-desc {
          font-size: 0.8rem;
          color: #94a3b8;
          line-height: 1.45;
        }

        .presets-box {
          background: rgba(11, 15, 25, 0.7);
          border: 1px solid rgba(6, 182, 212, 0.25);
          padding: 8px 10px;
          border-radius: 6px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .presets-label {
          font-size: 0.72rem;
          font-weight: 700;
          color: #38bdf8;
        }

        .preset-buttons-row {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }

        .preset-btn {
          background: rgba(30, 41, 59, 0.8);
          border: 1px solid rgba(148, 163, 184, 0.2);
          color: #e2e8f0;
          font-size: 0.72rem;
          font-weight: 600;
          padding: 4px 8px;
          border-radius: 4px;
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .preset-btn:hover {
          background: rgba(6, 182, 212, 0.25);
          border-color: #06b6d4;
          color: #ffffff;
        }

        .inputs-group {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }

        .input-field {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .input-field label {
          font-size: 0.74rem;
          color: #94a3b8;
          font-weight: 600;
        }

        .input-field input,
        .input-field select {
          background: #0b0f19;
          border: 1px solid rgba(148, 163, 184, 0.2);
          color: #ffffff;
          padding: 8px 10px;
          border-radius: 6px;
          font-size: 0.82rem;
        }

        .broadcast-buttons-box {
          display: flex;
          flex-direction: column;
          gap: 8px;
          margin-top: 6px;
        }

        .start-broadcast-btn {
          width: 100%;
          background: linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%);
          color: #ffffff;
          border: none;
          padding: 12px;
          border-radius: 6px;
          font-weight: 700;
          font-size: 0.88rem;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          cursor: pointer;
          transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .start-broadcast-btn:hover {
          transform: translateY(-1px);
          box-shadow: 0 4px 14px rgba(6, 182, 212, 0.35);
        }

        .stop-broadcast-btn {
          width: 100%;
          background: rgba(239, 68, 68, 0.2);
          border: 1px solid #ef4444;
          color: #fca5a5;
          padding: 10px;
          border-radius: 6px;
          font-weight: 700;
          font-size: 0.84rem;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          cursor: pointer;
        }

        .trigger-fight-btn {
          width: 100%;
          background: rgba(245, 158, 11, 0.15);
          border: 1px solid rgba(245, 158, 11, 0.35);
          color: #fcd34d;
          padding: 8px;
          border-radius: 6px;
          font-size: 0.78rem;
          font-weight: 600;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          cursor: pointer;
        }

        .mobile-share-card {
          margin-top: 10px;
          background: rgba(11, 15, 25, 0.7);
          border: 1px dashed rgba(148, 163, 184, 0.2);
          border-radius: 8px;
          padding: 12px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .share-header {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .share-title {
          font-size: 0.76rem;
          font-weight: 600;
          color: #e2e8f0;
        }
        .share-desc {
          font-size: 0.72rem;
          color: #94a3b8;
        }

        .url-copy-box {
          display: flex;
          align-items: center;
          justify-content: space-between;
          background: #080b11;
          border: 1px solid rgba(148, 163, 184, 0.15);
          border-radius: 4px;
          padding: 4px 8px;
          margin-top: 4px;
        }
        .url-code {
          font-family: var(--font-mono);
          font-size: 0.72rem;
          color: #38bdf8;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .copy-url-btn {
          color: #94a3b8;
          padding: 4px;
          cursor: pointer;
        }
        .copy-url-btn:hover {
          color: #ffffff;
        }
      `}</style>
    </div>
  );
}
