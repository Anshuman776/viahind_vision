'use client';

/**
 * Phone camera streamer: turns a signed-in phone (or any browser) into the video source for a
 * "Browser camera" configured in Settings. Frames go to the backend over an authenticated
 * WebSocket; detection and event recording happen on the server.
 */

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, CircleAlert, Play, ShieldCheck, Square, SwitchCamera } from 'lucide-react';
import { api } from '@/lib/api';
import type { Camera } from '@/lib/types';
import { CaptureProvider, useCapture } from '@/components/CaptureProvider';
import { SessionProvider } from '@/components/SessionProvider';
import { CameraStatusBadge } from '@/components/Status';

export default function StreamerPage() {
  return (
    <SessionProvider>
      <CaptureProvider>
        <Streamer />
      </CaptureProvider>
    </SessionProvider>
  );
}

function Streamer() {
  const capture = useCapture();
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState('');
  const [facing, setFacing] = useState<'environment' | 'user'>('environment');
  const [error, setError] = useState<string | null>(null);
  const previewRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const load = () =>
      api<Camera[]>('/cameras')
        .then((list) => {
          const browserCams = list.filter((c) => c.source_type === 'browser' && c.enabled);
          setCameras(browserCams);
          setCameraId((current) => {
            if (current) return current;
            const requested = new URLSearchParams(window.location.search).get('camera');
            return browserCams.find((c) => c.id === requested)?.id ?? browserCams[0]?.id ?? '';
          });
        })
        .catch((err) => setError(err.message));
    load();
    const t = window.setInterval(load, 4000);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => {
    if (previewRef.current) previewRef.current.srcObject = capture.stream;
  }, [capture.stream]);

  const camera = cameras.find((c) => c.id === cameraId);
  const active = capture.state !== 'idle' && capture.state !== 'error';

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: 16, display: 'grid', gap: 14 }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div className="brand-mark" aria-hidden="true">
          <ShieldCheck size={18} />
        </div>
        <div style={{ flex: 1 }}>
          <div className="brand-name">VIAHIND Vision</div>
          <div className="brand-sub">Phone camera streamer</div>
        </div>
        <Link href="/live" className="btn btn-sm">
          <ArrowLeft size={14} /> Dashboard
        </Link>
      </header>

      {(error || capture.error) && (
        <div className="banner banner-err" role="alert" style={{ marginBottom: 0 }}>
          <CircleAlert size={16} /> <span>{capture.error || error}</span>
        </div>
      )}

      <div className="video-stage" style={{ aspectRatio: '3 / 4', maxHeight: '60vh' }}>
        {capture.stream ? (
          <video ref={previewRef} autoPlay muted playsInline style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain' }} />
        ) : (
          <div className="video-placeholder">
            <strong>Camera off</strong>
            Mount the phone so the doorway is fully visible, then press Start. Camera permission is requested only then.
          </div>
        )}
        {capture.state === 'streaming' && (
          <div className="video-hud">
            <span className="hud-chip">Sending to server</span>
          </div>
        )}
      </div>

      <section className="panel">
        <div className="panel-body" style={{ display: 'grid', gap: 12 }}>
          {cameras.length === 0 ? (
            <p className="muted">
              No browser cameras are configured. An administrator can add one in Settings → Cameras (type &ldquo;Browser camera&rdquo;).
            </p>
          ) : (
            <div className="field">
              <label htmlFor="stream-camera">Stream as camera</label>
              <select id="stream-camera" className="select" value={cameraId} disabled={active} onChange={(e) => setCameraId(e.target.value)}>
                {cameras.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          {camera && (
            <div className="control-row" style={{ justifyContent: 'space-between' }}>
              <span className="small muted">Server status</span>
              <CameraStatusBadge status={camera.runtime.status} />
            </div>
          )}
          <div className="control-row">
            {active ? (
              <button type="button" className="btn" onClick={() => capture.stop()}>
                <Square size={14} /> Stop
              </button>
            ) : (
              <button type="button" className="btn btn-primary" disabled={!cameraId} onClick={() => capture.start(cameraId, { facingMode: facing })}>
                <Play size={14} /> Start
              </button>
            )}
            <button
              type="button"
              className="btn"
              disabled={active}
              onClick={() => setFacing((f) => (f === 'environment' ? 'user' : 'environment'))}
              title="Choose the front or rear camera before starting"
            >
              <SwitchCamera size={14} /> {facing === 'environment' ? 'Rear camera' : 'Front camera'}
            </button>
          </div>
          <p className="small muted">
            Keep this page open and the screen on while streaming. Phones require HTTPS for camera access. Residents and visitors must be
            informed that the entrance is monitored.
          </p>
        </div>
      </section>
    </div>
  );
}
