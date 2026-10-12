'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { FloorIdentifier } from '../types/alert';
import {
  Camera,
  Layers,
  Smartphone,
  Plus,
  X,
  Maximize2,
  ExternalLink,
  Copy,
  CheckCircle2,
  Tv,
  Globe,
  Radio,
  Trash2,
  Wifi,
  WifiOff,
  AlertTriangle,
  RotateCcw,
  ShieldAlert,
} from 'lucide-react';

export interface CameraItem {
  id: string;
  name: string;
  floor: FloorIdentifier;
  location: string;
  status: 'online' | 'degraded' | 'offline';
  fps: number;
  hasActiveAlert?: boolean;
  isPhoneCamera?: boolean;
  liveFrameBase64?: string;
  streamUrl?: string;
}

const defaultMockCameras: CameraItem[] = [
  {
    id: 'CAM-G-LOBBY-01',
    name: 'Ground Reception Turnstile',
    floor: 'Ground Floor',
    location: 'Main Security Turnstile & Lobby',
    status: 'online',
    fps: 30,
    hasActiveAlert: true,
  },
  {
    id: 'CAM-G-DINING-02',
    name: 'Ground Mess & Dining Hall',
    floor: 'Ground Floor',
    location: 'Resident Dining Facility',
    status: 'online',
    fps: 30,
  },
  {
    id: 'CAM-F1-CORR-04',
    name: 'Floor 1 Main Corridor East',
    floor: 'Floor 1',
    location: 'Boys Wing Corridor near Room 112',
    status: 'online',
    fps: 30,
    hasActiveAlert: true,
  },
  {
    id: 'CAM-F1-PHONE-01',
    name: 'Floor 1 Phone Cam - East',
    floor: 'Floor 1',
    location: 'Boys Wing Corridor East',
    status: 'online',
    fps: 30,
    isPhoneCamera: true,
    streamUrl: '/ws/live/CAM-F1-PHONE-01',
  },
  {
    id: 'CAM-F1-STAIR-01',
    name: 'Floor 1 Stairwell North',
    floor: 'Floor 1',
    location: 'Stairwell A Wing 1',
    status: 'online',
    fps: 28,
  },
  {
    id: 'CAM-F2-CORR-01',
    name: 'Floor 2 Girls Wing Corridor',
    floor: 'Floor 2',
    location: 'East Wing Passage',
    status: 'online',
    fps: 30,
  },
  {
    id: 'CAM-F2-STAIR-02',
    name: 'Floor 2 Emergency Fire Stair',
    floor: 'Floor 2',
    location: 'Emergency Fire Stairwell B',
    status: 'online',
    fps: 30,
    hasActiveAlert: true,
  },
  {
    id: 'CAM-F3-STUDY-01',
    name: 'Floor 3 Common Study Lounge',
    floor: 'Floor 3',
    location: 'Central Reading & Work Hall',
    status: 'online',
    fps: 30,
    hasActiveAlert: true,
  },
  {
    id: 'CAM-B1-PARK-03',
    name: 'Basement 1 Two-Wheeler Bay',
    floor: 'Basement',
    location: 'Resident Vehicle Parking Slot B',
    status: 'online',
    fps: 25,
  },
  {
    id: 'CAM-ROOF-PERIM-01',
    name: 'Rooftop Terrace North Perimeter',
    floor: 'Rooftop',
    location: 'Water Tank & Solar Panel Terrace',
    status: 'online',
    fps: 30,
    hasActiveAlert: true,
  },
];

export const CameraGrid: React.FC = () => {
  const [cameras, setCameras] = useState<CameraItem[]>(defaultMockCameras);
  const [selectedFloor, setSelectedFloor] = useState<FloorIdentifier | 'all'>('all');
  const [showAddModal, setShowAddModal] = useState(false);
  const [liveFrames, setLiveFrames] = useState<Record<string, string>>({});

  // Add Phone Camera form states
  const [phoneCamId, setPhoneCamId] = useState('CAM-PHONE-01');
  const [phoneCamName, setPhoneCamName] = useState('My Phone Camera');
  const [phoneFloor, setPhoneFloor] = useState<FloorIdentifier>('Floor 1');
  const [phoneLocation, setPhoneLocation] = useState('Corridor East');
  const [ipAppUrl, setIpAppUrl] = useState('');
  const [connectionMethod, setConnectionMethod] = useState<'web_streamer' | 'ip_webcam_app'>('web_streamer');
  const [copiedLink, setCopiedLink] = useState(false);

  // Dynamic host detection & manual override states
  const [detectedHostIp, setDetectedHostIp] = useState<string>('');
  const [detectedInterfaceName, setDetectedInterfaceName] = useState<string>('');
  const [availableInterfaces, setAvailableInterfaces] = useState<
    Array<{ name: string; address: string; isWifi: boolean }>
  >([]);
  const [manualHostOverride, setManualHostOverride] = useState<string>('');
  const [showFirewallInfo, setShowFirewallInfo] = useState<boolean>(false);

  // Auto-detect reachable network interfaces from server
  useEffect(() => {
    const fetchNetworkInfo = async () => {
      try {
        const res = await fetch('/api/network-info');
        if (res.ok) {
          const data = await res.json();
          if (data && data.primaryIp) {
            setDetectedHostIp(data.primaryIp);
            if (Array.isArray(data.interfaces)) {
              setAvailableInterfaces(data.interfaces);
              const match = data.interfaces.find((i: any) => i.address === data.primaryIp);
              if (match) setDetectedInterfaceName(match.name);
            }
          }
        }
      } catch (err) {
        if (
          typeof window !== 'undefined' &&
          window.location.hostname !== 'localhost' &&
          window.location.hostname !== '127.0.0.1'
        ) {
          setDetectedHostIp(window.location.hostname);
        }
      }
    };

    fetchNetworkInfo();
  }, []);

  // Helper to get backend URL dynamically
  const getBackendUrl = () => {
    if (typeof window !== 'undefined' && window.location.hostname !== 'localhost') {
      return `http://${window.location.hostname}:8000`;
    }
    return process.env.NEXT_PUBLIC_API_URL?.replace('/api/v1', '') || 'http://localhost:8000';
  };

  // Poll backend for registered phone cameras
  const fetchCameras = async () => {
    try {
      const backendUrl = getBackendUrl();
      const res = await fetch(`${backendUrl}/api/v1/cameras`);
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data) && data.length > 0) {
          const mapped: CameraItem[] = data.map((d: any) => {
            if (d.live_frame_base64) {
              setLiveFrames((prev) => ({ ...prev, [d.id]: d.live_frame_base64 }));
            }
            return {
              id: d.id,
              name: d.name,
              floor: d.floor,
              location: d.location,
              status: d.status,
              fps: d.fps,
              hasActiveAlert: d.has_active_alert,
              isPhoneCamera: d.is_phone_camera,
              streamUrl: d.stream_url,
            };
          });
          setCameras(mapped);
        }
      }
    } catch (e) {
      // Offline fallback
    }
  };

  useEffect(() => {
    fetchCameras();
    const interval = setInterval(fetchCameras, 5000);
    return () => clearInterval(interval);
  }, []);

  // Listen to live WebSocket frame relay for any registered phone cameras
  useEffect(() => {
    const phoneCams = cameras.filter((c) => c.isPhoneCamera);
    if (phoneCams.length === 0) return;

    const sockets: WebSocket[] = [];
    const wsHost = typeof window !== 'undefined' ? window.location.hostname : 'localhost';

    phoneCams.forEach((cam) => {
      try {
        const ws = new WebSocket(`ws://${wsHost}:8000/ws/live/${cam.id}`);
        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.image) {
              setLiveFrames((prev) => ({ ...prev, [cam.id]: data.image }));
            }
          } catch (err) {}
        };
        sockets.push(ws);
      } catch (err) {}
    });

    return () => {
      sockets.forEach((s) => s.close());
    };
  }, [cameras]);

  // Handle Registering Phone Camera
  const handleConnectPhoneCamera = async () => {
    const newPhoneCam: CameraItem = {
      id: phoneCamId,
      name: phoneCamName,
      floor: phoneFloor,
      location: phoneLocation,
      status: 'online',
      fps: 30,
      isPhoneCamera: true,
      hasActiveAlert: false,
      streamUrl: connectionMethod === 'ip_webcam_app' ? ipAppUrl : `/ws/live/${phoneCamId}`,
    };

    // Try notifying backend
    try {
      const backendUrl = getBackendUrl();
      await fetch(`${backendUrl}/api/v1/cameras/phone`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: phoneCamId,
          name: phoneCamName,
          floor: phoneFloor,
          location: phoneLocation,
          stream_type: connectionMethod === 'ip_webcam_app' ? 'ip_webcam_mjpeg' : 'browser_stream',
          ip_stream_url: ipAppUrl || undefined,
        }),
      });
    } catch (e) {}

    setCameras((prev) => [newPhoneCam, ...prev.filter((c) => c.id !== phoneCamId)]);
    setShowAddModal(false);
  };

  const handleDeletePhoneCamera = async (camId: string) => {
    try {
      const backendUrl = getBackendUrl();
      await fetch(`${backendUrl}/api/v1/cameras/phone/${camId}`, { method: 'DELETE' });
    } catch (e) {}
    setCameras((prev) => prev.filter((c) => c.id !== camId));
  };

  // Dynamically resolve reachable host: manual override > non-loopback window.location.host > detected LAN IP > fallback
  const getStreamerHost = () => {
    const currentPort = typeof window !== 'undefined' && window.location.port ? window.location.port : '3000';

    // 1. Manual override takes highest precedence if provided
    if (manualHostOverride.trim()) {
      const override = manualHostOverride.trim();
      if (override.includes(':')) {
        return override;
      }
      return currentPort && currentPort !== '80' && currentPort !== '443' ? `${override}:${currentPort}` : override;
    }

    // 2. If client is browsing on non-localhost/loopback address, use current window.location.host
    if (typeof window !== 'undefined') {
      const currentHost = window.location.hostname;
      if (currentHost && currentHost !== 'localhost' && currentHost !== '127.0.0.1') {
        return window.location.host;
      }
    }

    // 3. Use detected host IP (e.g. 10.167.189.1) with current frontend port
    const effectiveIp = detectedHostIp || (typeof window !== 'undefined' ? window.location.hostname : '127.0.0.1');
    return currentPort && currentPort !== '80' && currentPort !== '443' ? `${effectiveIp}:${currentPort}` : effectiveIp;
  };

  const getStreamerProtocol = () => {
    return typeof window !== 'undefined' && window.location.protocol ? window.location.protocol : 'http:';
  };

  const streamerHost = getStreamerHost();
  const streamerFullUrl = `${getStreamerProtocol()}//${streamerHost}/streamer`;

  // Deep-link with camera ID & floor parameters pre-populated!
  const streamerTargetUrl = `${streamerFullUrl}?id=${encodeURIComponent(phoneCamId)}&floor=${encodeURIComponent(phoneFloor)}&name=${encodeURIComponent(phoneCamName)}&loc=${encodeURIComponent(phoneLocation)}`;

  const copyStreamerUrl = () => {
    navigator.clipboard.writeText(streamerTargetUrl);
    setCopiedLink(true);
    setTimeout(() => setCopiedLink(false), 2000);
  };

  // Preset quick applier
  const applyPreset = (id: string, name: string, floor: FloorIdentifier, loc: string) => {
    setPhoneCamId(id);
    setPhoneCamName(name);
    setPhoneFloor(floor);
    setPhoneLocation(loc);
  };

  const filteredCameras = cameras.filter((cam) => {
    if (selectedFloor !== 'all' && cam.floor !== selectedFloor) return false;
    return true;
  });

  const floors: Array<FloorIdentifier | 'all'> = [
    'all',
    'Basement',
    'Ground Floor',
    'Floor 1',
    'Floor 2',
    'Floor 3',
    'Rooftop',
  ];

  return (
    <div className="camera-grid-component">
      {/* Top Filter and Add Phone Cam Bar */}
      <div className="floor-filter-bar">
        <div className="filter-left">
          <span className="floor-filter-label">
            <Layers size={14} /> Filter by PG Floor:
          </span>
          <div className="floor-pills">
            {floors.map((floor) => (
              <button
                key={floor}
                type="button"
                className={`floor-pill-btn ${selectedFloor === floor ? 'active' : ''}`}
                onClick={() => setSelectedFloor(floor)}
              >
                {floor === 'all' ? `All Floors (${cameras.length} Cams)` : floor}
              </button>
            ))}
          </div>
        </div>

        {/* Action Button: Connect Phone Camera */}
        <button
          type="button"
          className="add-phone-cam-btn"
          onClick={() => setShowAddModal(true)}
          id="btn-add-phone-camera"
        >
          <Smartphone size={15} />
          <span>+ Connect Phone Camera</span>
        </button>
      </div>

      {/* Grid of Cameras */}
      <div className="cameras-matrix">
        {filteredCameras.map((cam) => (
          <div
            key={cam.id}
            className={`camera-tile-card ${cam.isPhoneCamera ? 'phone-camera-card' : ''}`}
          >
            <div className="cam-header-row">
              <div className="cam-title-group">
                {cam.isPhoneCamera ? (
                  <Smartphone size={15} className="text-cyan" />
                ) : (
                  <Camera size={14} className="text-highlight" />
                )}
                <span className="cam-id-text">{cam.id}</span>
              </div>
              <div className="cam-status-badges">
                {cam.isPhoneCamera && <span className="phone-badge">SMARTPHONE</span>}
                {cam.hasActiveAlert && <span className="active-alert-chip">ALERT</span>}
                <span className="online-chip">
                  <span className="green-dot" /> LIVE
                </span>
                {cam.isPhoneCamera && (
                  <button
                    type="button"
                    className="delete-phone-cam-btn"
                    onClick={() => handleDeletePhoneCamera(cam.id)}
                    title="Disconnect this phone camera"
                    aria-label={`Disconnect ${cam.name}`}
                  >
                    <Trash2 size={12} />
                  </button>
                )}
              </div>
            </div>

            {/* Live Video / Canvas Viewport */}
            <div className="cam-video-viewport">
              {/* If this is a phone camera and we have live frame, render real live image! */}
              {cam.isPhoneCamera && liveFrames[cam.id] ? (
                <img
                  src={liveFrames[cam.id]}
                  alt={`Live view from ${cam.name}`}
                  className="live-phone-feed-img"
                />
              ) : cam.isPhoneCamera && cam.streamUrl?.startsWith('http') ? (
                <img
                  src={cam.streamUrl}
                  alt={`IP Webcam stream for ${cam.name}`}
                  className="live-phone-feed-img"
                />
              ) : (
                <div className="placeholder-viewport">
                  <div className="surveillance-crosshair" />
                  <div className="canvas-placeholder-text">
                    {cam.isPhoneCamera
                      ? `Waiting for phone stream: /streamer`
                      : cam.name}
                  </div>
                </div>
              )}

              <div className="cam-viewport-overlay">
                <span className="rec-live-text">
                  {cam.isPhoneCamera ? 'PHONE CAM' : 'RTSP STREAM'} • 1080P @ {cam.fps}FPS
                </span>
                <span className="cam-floor-tag">{cam.floor}</span>
              </div>
            </div>

            <div className="cam-footer-info">
              <span className="cam-loc-desc">{cam.location}</span>
              {cam.isPhoneCamera ? (
                <Link
                  href="/streamer"
                  className="open-streamer-shortcut"
                  title="Open streamer control on this phone"
                >
                  <ExternalLink size={13} />
                  <span>Stream Controller</span>
                </Link>
              ) : (
                <button type="button" className="expand-cam-btn" title="Inspect full stream">
                  <Maximize2 size={13} />
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* MODAL: Connect Phone Camera as CCTV */}
      {showAddModal && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal-card">
            <div className="modal-header">
              <div className="modal-title-row">
                <Smartphone size={20} className="text-highlight" />
                <h3>Connect Smartphone as CCTV Camera</h3>
              </div>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowAddModal(false)}
                aria-label="Close modal"
              >
                <X size={18} />
              </button>
            </div>

            <div className="modal-body">
              <p className="modal-desc">
                No physical IP cameras yet? Use your smartphone camera as an active CCTV feed in your PG facility.
              </p>

              {/* Method Tabs */}
              <div className="method-tabs">
                <button
                  type="button"
                  className={`method-tab ${connectionMethod === 'web_streamer' ? 'active' : ''}`}
                  onClick={() => setConnectionMethod('web_streamer')}
                >
                  <Globe size={15} />
                  <span>Option 1: Phone Browser (Zero Install)</span>
                </button>
                <button
                  type="button"
                  className={`method-tab ${connectionMethod === 'ip_webcam_app' ? 'active' : ''}`}
                  onClick={() => setConnectionMethod('ip_webcam_app')}
                >
                  <Radio size={15} />
                  <span>Option 2: IP Webcam Mobile App</span>
                </button>
              </div>

              {connectionMethod === 'web_streamer' ? (
                <div className="method-content">
                  {/* Quick Multi-Floor Presets */}
                  <div className="modal-presets-bar">
                    <span className="presets-title">⚡ Quick Floor & Location Presets:</span>
                    <div className="preset-chips">
                      <button
                        type="button"
                        className={`preset-chip ${phoneCamId === 'CAM-F1-PHONE-01' ? 'active' : ''}`}
                        onClick={() => applyPreset('CAM-F1-PHONE-01', 'Floor 1 Phone Cam - East', 'Floor 1', 'Boys Wing Corridor East')}
                      >
                        Floor 1 East
                      </button>
                      <button
                        type="button"
                        className={`preset-chip ${phoneCamId === 'CAM-F1-PHONE-02' ? 'active' : ''}`}
                        onClick={() => applyPreset('CAM-F1-PHONE-02', 'Floor 1 Phone Cam - West', 'Floor 1', 'Boys Wing Corridor West')}
                      >
                        Floor 1 West
                      </button>
                      <button
                        type="button"
                        className={`preset-chip ${phoneCamId === 'CAM-F1-PHONE-03' ? 'active' : ''}`}
                        onClick={() => applyPreset('CAM-F1-PHONE-03', 'Floor 1 Phone Cam - Stairs', 'Floor 1', 'North Staircase A')}
                      >
                        Floor 1 Stairs
                      </button>
                      <button
                        type="button"
                        className={`preset-chip ${phoneCamId === 'CAM-F2-PHONE-01' ? 'active' : ''}`}
                        onClick={() => applyPreset('CAM-F2-PHONE-01', 'Floor 2 Phone Cam - Hall', 'Floor 2', 'Girls Wing Central Corridor')}
                      >
                        Floor 2
                      </button>
                      <button
                        type="button"
                        className={`preset-chip ${phoneCamId === 'CAM-G-PHONE-01' ? 'active' : ''}`}
                        onClick={() => applyPreset('CAM-G-PHONE-01', 'Ground Phone Cam - Entry', 'Ground Floor', 'Main Reception Turnstile')}
                      >
                        Ground
                      </button>
                    </div>
                  </div>

                  {/* Host Detection & Manual Override */}
                  <div className="host-config-section">
                    <div className="host-info-row">
                      <div className="host-detected-badge">
                        <Wifi size={14} className="text-cyan" />
                        <span className="host-label">Detected Host:</span>
                        <code className="host-ip-val">
                          {detectedHostIp || (typeof window !== 'undefined' ? window.location.hostname : 'Detecting...')}
                        </code>
                        {detectedInterfaceName && (
                          <span className="interface-tag">({detectedInterfaceName})</span>
                        )}
                      </div>
                      {manualHostOverride && (
                        <button
                          type="button"
                          className="reset-override-btn"
                          onClick={() => setManualHostOverride('')}
                          title="Reset to automatically detected host address"
                          id="btn-reset-host-override"
                        >
                          <RotateCcw size={12} />
                          <span>Reset to Auto</span>
                        </button>
                      )}
                    </div>

                    {availableInterfaces.length > 1 && (
                      <div className="available-interfaces-row">
                        <span className="avail-label">Available Adapters:</span>
                        {availableInterfaces.map((iface) => (
                          <button
                            key={`${iface.name}-${iface.address}`}
                            type="button"
                            className={`iface-chip ${
                              (manualHostOverride || detectedHostIp) === iface.address ? 'active' : ''
                            }`}
                            onClick={() => setManualHostOverride(iface.address)}
                          >
                            {iface.name} ({iface.address})
                          </button>
                        ))}
                      </div>
                    )}

                    <div className="manual-override-box">
                      <label htmlFor="input-host-override">
                        Manual Host Override <span className="label-hint">(Use if automatic IP detection is incorrect, or using VPN / hotspot)</span>:
                      </label>
                      <div className="override-input-row">
                        <input
                          id="input-host-override"
                          type="text"
                          placeholder="e.g. 10.167.189.1 or my-pc.local:3000"
                          value={manualHostOverride}
                          onChange={(e) => setManualHostOverride(e.target.value)}
                        />
                        {manualHostOverride && (
                          <button
                            type="button"
                            className="clear-override-btn"
                            onClick={() => setManualHostOverride('')}
                            aria-label="Clear manual override"
                          >
                            <X size={14} />
                          </button>
                        )}
                      </div>
                      {manualHostOverride && (
                        <span className="override-active-notice">
                          Target host overridden to: <code>{getStreamerHost()}</code>
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Network Connectivity Warning */}
                  <div className="connectivity-warning-card" role="alert">
                    <div className="warning-title-row">
                      <AlertTriangle size={15} className="text-amber" />
                      <h4>Network Connectivity Notice: Same Wi-Fi Required</h4>
                    </div>
                    <p className="warning-desc">
                      Your phone and laptop must be connected to the <strong>same Wi-Fi network</strong> (or connect your phone to this laptop&apos;s <strong>Mobile Hotspot</strong>).
                    </p>
                    <ul className="connectivity-guidelines">
                      <li>
                        <strong>Mobile Data (4G/5G) will not work:</strong> Cellular networks cannot route to private LAN addresses like <code>{getStreamerHost()}</code>.
                      </li>
                      <li>
                        <strong>Wi-Fi Isolation / Guest Networks:</strong> Some guest Wi-Fi networks block peer-to-peer traffic between devices. If connection fails, switch to Windows Mobile Hotspot.
                      </li>
                      <li>
                        <strong>Windows Firewall:</strong> Inbound connections on ports <code>{typeof window !== 'undefined' && window.location.port ? window.location.port : '3000'}</code> (frontend) and <code>8000</code> (backend stream broker) must be allowed.
                      </li>
                    </ul>

                    <button
                      type="button"
                      className="toggle-firewall-btn"
                      onClick={() => setShowFirewallInfo(!showFirewallInfo)}
                      aria-expanded={showFirewallInfo}
                      id="btn-toggle-firewall-info"
                    >
                      <ShieldAlert size={13} />
                      <span>{showFirewallInfo ? 'Hide Windows Firewall Setup' : 'View Windows Firewall & Port Setup'}</span>
                    </button>

                    {showFirewallInfo && (
                      <div className="firewall-instructions-box">
                        <p className="firewall-help-text">
                          If your phone cannot load the page, allow inbound traffic in PowerShell (Run as Administrator):
                        </p>
                        <pre className="firewall-code-block">
                          <code>
{`# Allow Frontend (Port 3000)
New-NetFirewallRule -DisplayName "VIAHIND Vision Frontend" -Direction Inbound -LocalPort 3000 -Protocol TCP -Action Allow

# Allow Backend Stream Broker (Port 8000)
New-NetFirewallRule -DisplayName "VIAHIND Vision Backend" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow`}
                          </code>
                        </pre>
                      </div>
                    )}
                  </div>

                  {/* QR Code Scanner Card */}
                  <div className="qr-scan-card">
                    <div className="qr-image-container">
                      <img
                        src={`https://api.qrserver.com/v1/create-qr-code/?size=150x150&margin=4&data=${encodeURIComponent(streamerTargetUrl)}`}
                        alt="Scan QR code with phone"
                        className="qr-img"
                        width={130}
                        height={130}
                      />
                    </div>
                    <div className="qr-instructions">
                      <span className="qr-badge">📱 SCAN TO CONNECT PHONE</span>
                      <p className="qr-subtext">
                        Scan with your phone&apos;s camera. It opens the streamer pre-configured for <strong>{phoneFloor}</strong> (<code>{phoneCamId}</code>).
                      </p>
                      <span className="qr-network-tip">
                        Host Address: <code>{getStreamerHost()}</code>
                      </span>
                    </div>
                  </div>

                  <div className="streamer-url-box">
                    <label>Or open this link on your phone browser:</label>
                    <div className="copy-row">
                      <code className="streamer-target-url-text">{streamerTargetUrl}</code>
                      <button
                        type="button"
                        className="copy-btn"
                        onClick={copyStreamerUrl}
                        id="btn-copy-streamer-url"
                        aria-label="Copy streamer link"
                      >
                        {copiedLink ? <CheckCircle2 size={15} className="text-green" /> : <Copy size={15} />}
                        <span>{copiedLink ? 'Copied Link!' : 'Copy Link'}</span>
                      </button>
                    </div>
                  </div>

                  <div className="quick-test-action">
                    <span>Test on this computer now:</span>
                    <Link
                      href={streamerTargetUrl}
                      target="_blank"
                      className="test-streamer-link"
                      id="link-launch-streamer"
                    >
                      <ExternalLink size={14} />
                      <span>Launch Streamer for {phoneCamId}</span>
                    </Link>
                  </div>
                </div>
              ) : (
                <div className="method-content">
                  <div className="instructions-box">
                    <strong>How to connect an IP Webcam app:</strong>
                    <ol>
                      <li>Install any free <strong>IP Webcam</strong> app on Android or iOS.</li>
                      <li>Tap "Start Server" in the app on your phone.</li>
                      <li>Paste the local stream URL below (e.g. <code>http://192.168.1.15:8080/video</code>).</li>
                    </ol>
                  </div>

                  <div className="form-field">
                    <label>Phone IP Stream URL</label>
                    <input
                      type="text"
                      placeholder="e.g. http://192.168.1.50:8080/video"
                      value={ipAppUrl}
                      onChange={(e) => setIpAppUrl(e.target.value)}
                    />
                  </div>
                </div>
              )}

              {/* Assignment Details */}
              <div className="assignment-section">
                <h4>Camera Placement in PG</h4>
                <div className="assignment-grid">
                  <div className="form-field">
                    <label>Camera ID</label>
                    <input
                      type="text"
                      value={phoneCamId}
                      onChange={(e) => setPhoneCamId(e.target.value)}
                    />
                  </div>
                  <div className="form-field">
                    <label>Camera Name</label>
                    <input
                      type="text"
                      value={phoneCamName}
                      onChange={(e) => setPhoneCamName(e.target.value)}
                    />
                  </div>
                  <div className="form-field">
                    <label>Assigned Floor</label>
                    <select
                      value={phoneFloor}
                      onChange={(e) => setPhoneFloor(e.target.value as FloorIdentifier)}
                    >
                      <option value="Ground Floor">Ground Floor</option>
                      <option value="Floor 1">Floor 1 (Boys Wing)</option>
                      <option value="Floor 2">Floor 2 (Girls Wing)</option>
                      <option value="Floor 3">Floor 3 (Study Lounge)</option>
                      <option value="Basement">Basement Parking</option>
                      <option value="Rooftop">Rooftop Terrace</option>
                    </select>
                  </div>
                  <div className="form-field">
                    <label>Specific Location</label>
                    <input
                      type="text"
                      value={phoneLocation}
                      onChange={(e) => setPhoneLocation(e.target.value)}
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="modal-footer">
              <button
                type="button"
                className="cancel-btn"
                onClick={() => setShowAddModal(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="submit-connect-btn"
                onClick={handleConnectPhoneCamera}
                id="btn-confirm-add-phone-camera"
              >
                Add Phone Camera Feed
              </button>
            </div>
          </div>
        </div>
      )}

      <style jsx>{`
        .camera-grid-component {
          display: flex;
          flex-direction: column;
          gap: 16px;
          padding: 20px;
        }

        .floor-filter-bar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          flex-wrap: wrap;
          background: rgba(15, 23, 42, 0.6);
          padding: 10px 14px;
          border-radius: 8px;
          border: 1px solid var(--border-subtle);
        }

        .filter-left {
          display: flex;
          align-items: center;
          gap: 12px;
          flex-wrap: wrap;
        }

        .floor-filter-label {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.8rem;
          color: var(--text-secondary);
          font-weight: 600;
        }

        .floor-pills {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
        }

        .floor-pill-btn {
          font-size: 0.75rem;
          font-weight: 500;
          padding: 4px 10px;
          border-radius: 6px;
          background: rgba(30, 41, 59, 0.7);
          color: var(--text-secondary);
          border: 1px solid var(--border-medium);
          transition: all 0.15s ease;
        }

        .floor-pill-btn:hover {
          color: var(--text-primary);
          border-color: rgba(148, 163, 184, 0.4);
        }

        .floor-pill-btn.active {
          background: rgba(6, 182, 212, 0.2);
          color: #a5f3fc;
          border-color: var(--accent-cyan);
          font-weight: 600;
        }

        .add-phone-cam-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: linear-gradient(135deg, rgba(6, 182, 212, 0.25) 0%, rgba(59, 130, 246, 0.25) 100%);
          border: 1px solid rgba(6, 182, 212, 0.5);
          color: #38bdf8;
          padding: 6px 14px;
          border-radius: 6px;
          font-size: 0.78rem;
          font-weight: 700;
          cursor: pointer;
          transition: all 0.15s ease;
        }
        .add-phone-cam-btn:hover {
          background: linear-gradient(135deg, rgba(6, 182, 212, 0.35) 0%, rgba(59, 130, 246, 0.35) 100%);
          color: #ffffff;
          box-shadow: 0 0 12px rgba(6, 182, 212, 0.3);
        }

        .cameras-matrix {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
          gap: 16px;
        }

        .camera-tile-card {
          background: var(--bg-surface);
          border: 1px solid var(--border-subtle);
          border-radius: 8px;
          overflow: hidden;
          display: flex;
          flex-direction: column;
          transition: transform 0.15s ease, border-color 0.15s ease;
        }

        .camera-tile-card.phone-camera-card {
          border-color: rgba(6, 182, 212, 0.4);
          box-shadow: 0 0 16px rgba(6, 182, 212, 0.1);
        }

        .camera-tile-card:hover {
          border-color: rgba(148, 163, 184, 0.35);
          transform: translateY(-2px);
        }

        .cam-header-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 12px;
          background: rgba(11, 15, 25, 0.8);
          border-bottom: 1px solid var(--border-subtle);
        }

        .cam-title-group {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .cam-id-text {
          font-family: var(--font-mono);
          font-size: 0.78rem;
          font-weight: 600;
          color: var(--text-primary);
        }

        .cam-status-badges {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .phone-badge {
          background: rgba(6, 182, 212, 0.2);
          color: #38bdf8;
          border: 1px solid rgba(6, 182, 212, 0.4);
          font-size: 0.62rem;
          font-weight: 700;
          padding: 1px 5px;
          border-radius: 4px;
        }

        .active-alert-chip {
          background: rgba(239, 68, 68, 0.2);
          color: #fca5a5;
          border: 1px solid rgba(239, 68, 68, 0.4);
          font-size: 0.65rem;
          font-weight: 700;
          padding: 1px 5px;
          border-radius: 4px;
        }

        .online-chip {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-size: 0.65rem;
          font-weight: 700;
          color: #34d399;
          background: rgba(16, 185, 129, 0.15);
          padding: 1px 6px;
          border-radius: 4px;
        }

        .delete-phone-cam-btn {
          color: #94a3b8;
          display: flex;
          align-items: center;
          padding: 2px;
          cursor: pointer;
        }
        .delete-phone-cam-btn:hover {
          color: #ef4444;
        }

        .green-dot {
          width: 5px;
          height: 5px;
          background: #10b981;
          border-radius: 50%;
        }

        .cam-video-viewport {
          height: 180px;
          background: radial-gradient(circle at center, #111a2e 0%, #060912 100%);
          position: relative;
          display: flex;
          align-items: center;
          justify-content: center;
          overflow: hidden;
        }

        .live-phone-feed-img {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }

        .placeholder-viewport {
          width: 100%;
          height: 100%;
          display: flex;
          align-items: center;
          justify-content: center;
          position: relative;
        }

        .cam-viewport-overlay {
          position: absolute;
          top: 8px;
          left: 10px;
          right: 10px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          font-family: var(--font-mono);
          font-size: 0.66rem;
          color: rgba(255, 255, 255, 0.75);
          z-index: 5;
        }

        .cam-floor-tag {
          background: rgba(0, 0, 0, 0.6);
          padding: 1px 6px;
          border-radius: 3px;
        }

        .canvas-placeholder-text {
          font-size: 0.8rem;
          color: rgba(255, 255, 255, 0.5);
          text-align: center;
          padding: 0 16px;
        }

        .cam-footer-info {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 12px;
          background: rgba(11, 15, 25, 0.6);
          border-top: 1px solid var(--border-subtle);
        }

        .cam-loc-desc {
          font-size: 0.75rem;
          color: var(--text-secondary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .open-streamer-shortcut {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-size: 0.72rem;
          color: #38bdf8;
          font-weight: 600;
        }
        .open-streamer-shortcut:hover {
          text-decoration: underline;
        }

        .expand-cam-btn {
          color: var(--text-secondary);
          display: flex;
          align-items: center;
          justify-content: center;
        }

        /* Modal */
        .modal-backdrop {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.75);
          backdrop-filter: blur(6px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 100;
          padding: 20px;
        }

        .modal-card {
          background: #0f172a;
          border: 1px solid rgba(148, 163, 184, 0.2);
          border-radius: 12px;
          max-width: 560px;
          width: 100%;
          display: flex;
          flex-direction: column;
          overflow: hidden;
          box-shadow: 0 20px 40px rgba(0, 0, 0, 0.7);
        }

        .modal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 20px;
          border-bottom: 1px solid rgba(148, 163, 184, 0.15);
          background: #0b0f19;
        }

        .modal-title-row {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .modal-title-row h3 {
          font-size: 1rem;
          font-weight: 700;
          color: #f8fafc;
        }

        .modal-close-btn {
          color: #94a3b8;
          cursor: pointer;
        }
        .modal-close-btn:hover {
          color: #ffffff;
        }

        .modal-body {
          padding: 20px;
          display: flex;
          flex-direction: column;
          gap: 14px;
          max-height: 75vh;
          overflow-y: auto;
        }

        .modal-desc {
          font-size: 0.82rem;
          color: #94a3b8;
          line-height: 1.45;
        }

        .method-tabs {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 8px;
          background: #0b0f19;
          padding: 4px;
          border-radius: 6px;
        }

        .method-tab {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 8px;
          font-size: 0.76rem;
          font-weight: 600;
          color: #94a3b8;
          border-radius: 4px;
          cursor: pointer;
          transition: all 0.15s ease;
        }
        .method-tab.active {
          background: rgba(6, 182, 212, 0.2);
          color: #a5f3fc;
          border: 1px solid rgba(6, 182, 212, 0.4);
        }

        .modal-presets-bar {
          background: rgba(11, 15, 25, 0.7);
          border: 1px solid rgba(6, 182, 212, 0.2);
          border-radius: 6px;
          padding: 8px 10px;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .presets-title {
          font-size: 0.72rem;
          font-weight: 700;
          color: #38bdf8;
        }

        .preset-chips {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }

        .preset-chip {
          background: rgba(30, 41, 59, 0.8);
          border: 1px solid rgba(148, 163, 184, 0.2);
          color: #e2e8f0;
          font-size: 0.7rem;
          font-weight: 600;
          padding: 4px 8px;
          border-radius: 4px;
          cursor: pointer;
          transition: all 0.15s ease;
        }
        .preset-chip:hover,
        .preset-chip.active {
          background: rgba(6, 182, 212, 0.25);
          border-color: #06b6d4;
          color: #ffffff;
        }

        .host-config-section {
          background: rgba(11, 15, 25, 0.8);
          border: 1px solid rgba(6, 182, 212, 0.25);
          border-radius: 8px;
          padding: 12px;
          display: flex;
          flex-direction: column;
          gap: 10px;
        }

        .host-info-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          flex-wrap: wrap;
        }

        .host-detected-badge {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.78rem;
          color: #e2e8f0;
        }

        .host-label {
          color: #94a3b8;
          font-weight: 500;
        }

        .host-ip-val {
          color: #38bdf8;
          background: rgba(6, 182, 212, 0.15);
          padding: 2px 6px;
          border-radius: 4px;
          font-weight: 700;
          font-size: 0.8rem;
          letter-spacing: 0.02em;
        }

        .interface-tag {
          font-size: 0.7rem;
          color: #a5f3fc;
          background: rgba(15, 23, 42, 0.6);
          padding: 1px 5px;
          border-radius: 3px;
        }

        .reset-override-btn {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-size: 0.7rem;
          font-weight: 600;
          color: #f59e0b;
          background: rgba(245, 158, 11, 0.15);
          border: 1px solid rgba(245, 158, 11, 0.3);
          border-radius: 4px;
          padding: 3px 8px;
          cursor: pointer;
          transition: all 0.15s ease;
        }
        .reset-override-btn:hover {
          background: rgba(245, 158, 11, 0.25);
          color: #fbbf24;
        }

        .available-interfaces-row {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
          font-size: 0.72rem;
        }
        .avail-label {
          color: #64748b;
          font-weight: 600;
        }
        .iface-chip {
          background: rgba(30, 41, 59, 0.7);
          border: 1px solid rgba(148, 163, 184, 0.2);
          color: #cbd5e1;
          font-size: 0.68rem;
          padding: 2px 7px;
          border-radius: 4px;
          cursor: pointer;
        }
        .iface-chip:hover,
        .iface-chip.active {
          border-color: #06b6d4;
          color: #38bdf8;
          background: rgba(6, 182, 212, 0.15);
        }

        .manual-override-box {
          display: flex;
          flex-direction: column;
          gap: 5px;
        }
        .manual-override-box label {
          font-size: 0.73rem;
          font-weight: 600;
          color: #94a3b8;
        }
        .label-hint {
          font-weight: 400;
          color: #64748b;
          font-size: 0.68rem;
        }

        .override-input-row {
          display: flex;
          align-items: center;
          gap: 6px;
          position: relative;
        }
        .override-input-row input {
          flex: 1;
          background: #060912;
          border: 1px solid rgba(148, 163, 184, 0.25);
          color: #f1f5f9;
          font-family: var(--font-mono);
          font-size: 0.78rem;
          padding: 6px 30px 6px 10px;
          border-radius: 6px;
        }
        .override-input-row input:focus {
          border-color: #06b6d4;
          outline: none;
          box-shadow: 0 0 0 2px rgba(6, 182, 212, 0.2);
        }
        .clear-override-btn {
          position: absolute;
          right: 8px;
          color: #94a3b8;
          cursor: pointer;
          background: none;
          border: none;
          display: flex;
          align-items: center;
          padding: 2px;
        }
        .clear-override-btn:hover {
          color: #ffffff;
        }

        .override-active-notice {
          font-size: 0.7rem;
          color: #38bdf8;
          margin-top: 2px;
        }
        .override-active-notice code {
          color: #a5f3fc;
          font-weight: 600;
        }

        .connectivity-warning-card {
          background: rgba(245, 158, 11, 0.08);
          border: 1px solid rgba(245, 158, 11, 0.3);
          border-radius: 8px;
          padding: 12px;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .warning-title-row {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .warning-title-row h4 {
          font-size: 0.78rem;
          font-weight: 700;
          color: #fbbf24;
          margin: 0;
        }
        .warning-desc {
          font-size: 0.74rem;
          color: #fde68a;
          line-height: 1.4;
          margin: 0;
        }
        .connectivity-guidelines {
          margin: 0;
          padding-left: 18px;
          display: flex;
          flex-direction: column;
          gap: 4px;
          font-size: 0.71rem;
          color: #cbd5e1;
        }
        .connectivity-guidelines strong {
          color: #f1f5f9;
        }
        .connectivity-guidelines code {
          color: #38bdf8;
          background: rgba(15, 23, 42, 0.7);
          padding: 1px 4px;
          border-radius: 3px;
        }

        .toggle-firewall-btn {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          font-size: 0.7rem;
          font-weight: 600;
          color: #38bdf8;
          background: rgba(56, 189, 248, 0.1);
          border: 1px solid rgba(56, 189, 248, 0.25);
          border-radius: 4px;
          padding: 4px 8px;
          cursor: pointer;
          align-self: flex-start;
          transition: all 0.15s ease;
        }
        .toggle-firewall-btn:hover {
          background: rgba(56, 189, 248, 0.2);
          color: #ffffff;
        }

        .firewall-instructions-box {
          background: #060912;
          border: 1px solid rgba(148, 163, 184, 0.2);
          border-radius: 6px;
          padding: 8px 10px;
          margin-top: 4px;
        }
        .firewall-help-text {
          font-size: 0.7rem;
          color: #94a3b8;
          margin: 0 0 6px 0;
        }
        .firewall-code-block {
          background: #030712;
          padding: 8px;
          border-radius: 4px;
          margin: 0;
          overflow-x: auto;
          font-size: 0.68rem;
          color: #38bdf8;
          line-height: 1.4;
        }
        .firewall-code-block code {
          font-family: var(--font-mono);
          white-space: pre-wrap;
        }

        .qr-scan-card {
          display: flex;
          align-items: center;
          gap: 14px;
          background: #0b0f19;
          border: 1px solid rgba(148, 163, 184, 0.2);
          border-radius: 8px;
          padding: 12px;
        }

        .qr-image-container {
          background: #ffffff;
          padding: 6px;
          border-radius: 6px;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }

        .qr-img {
          display: block;
          border-radius: 2px;
        }

        .qr-instructions {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .qr-badge {
          display: inline-block;
          font-size: 0.65rem;
          font-weight: 800;
          color: #06b6d4;
          letter-spacing: 0.05em;
        }

        .qr-subtext {
          font-size: 0.76rem;
          color: #cbd5e1;
          line-height: 1.4;
          margin: 0;
        }

        .qr-network-tip {
          font-size: 0.7rem;
          color: #94a3b8;
          margin-top: 4px;
        }
        .qr-network-tip code {
          color: #38bdf8;
          background: rgba(15, 23, 42, 0.6);
          padding: 1px 4px;
          border-radius: 3px;
        }

        .instructions-box {
          background: rgba(11, 15, 25, 0.7);
          border: 1px solid rgba(148, 163, 184, 0.15);
          border-radius: 6px;
          padding: 12px;
          font-size: 0.78rem;
          color: #cbd5e1;
        }
        .instructions-box ol {
          padding-left: 20px;
          margin-top: 6px;
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .streamer-url-box {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .streamer-url-box label {
          font-size: 0.74rem;
          color: #94a3b8;
          font-weight: 600;
        }

        .copy-row {
          display: flex;
          align-items: center;
          gap: 8px;
          background: #0b0f19;
          border: 1px solid rgba(148, 163, 184, 0.2);
          padding: 6px 10px;
          border-radius: 6px;
        }
        .copy-row code {
          flex: 1;
          font-family: var(--font-mono);
          font-size: 0.75rem;
          color: #38bdf8;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .copy-btn {
          display: flex;
          align-items: center;
          gap: 4px;
          color: #94a3b8;
          font-size: 0.75rem;
          cursor: pointer;
        }
        .copy-btn:hover {
          color: #ffffff;
        }

        .quick-test-action {
          display: flex;
          align-items: center;
          justify-content: space-between;
          font-size: 0.78rem;
          color: #94a3b8;
          padding: 8px 12px;
          background: rgba(30, 41, 59, 0.4);
          border-radius: 6px;
        }

        .test-streamer-link {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          color: #38bdf8;
          font-weight: 600;
        }
        .test-streamer-link:hover {
          text-decoration: underline;
        }

        .assignment-section {
          display: flex;
          flex-direction: column;
          gap: 10px;
          border-top: 1px solid rgba(148, 163, 184, 0.12);
          padding-top: 12px;
        }
        .assignment-section h4 {
          font-size: 0.85rem;
          font-weight: 600;
          color: #f1f5f9;
        }

        .assignment-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 10px;
        }

        .form-field {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .form-field label {
          font-size: 0.72rem;
          color: #94a3b8;
          font-weight: 600;
        }
        .form-field input,
        .form-field select {
          background: #0b0f19;
          border: 1px solid rgba(148, 163, 184, 0.2);
          color: #ffffff;
          padding: 8px 10px;
          border-radius: 6px;
          font-size: 0.8rem;
        }

        .modal-footer {
          padding: 14px 20px;
          border-top: 1px solid rgba(148, 163, 184, 0.15);
          background: #0b0f19;
          display: flex;
          align-items: center;
          justify-content: flex-end;
          gap: 10px;
        }

        .cancel-btn {
          color: #94a3b8;
          padding: 8px 14px;
          font-size: 0.8rem;
          cursor: pointer;
        }

        .submit-connect-btn {
          background: #06b6d4;
          color: #000000;
          font-weight: 700;
          font-size: 0.82rem;
          padding: 8px 16px;
          border-radius: 6px;
          cursor: pointer;
        }
        .submit-connect-btn:hover {
          background: #22d3ee;
        }
      `}</style>
    </div>
  );
};
