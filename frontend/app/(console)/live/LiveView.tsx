'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeftRight, CircleAlert, Pencil, Play, RefreshCw, Smartphone, Square, TriangleAlert } from 'lucide-react';
import { api } from '@/lib/api';
import { formatAgo, formatDateTime, SOURCE_LABELS } from '@/lib/format';
import { lineLength, type Point } from '@/lib/geometry';
import type { Camera, EntranceLine } from '@/lib/types';
import { useSystem } from '@/components/SystemProvider';
import { useCapture } from '@/components/CaptureProvider';
import { CameraStatusBadge } from '@/components/Status';
import { LiveFeed } from '@/components/LiveFeed';

const DETECTION_LABELS: Record<string, string> = {
  off: 'Off',
  unavailable: 'Unavailable',
  loading: 'Loading model…',
  active: 'Counting entries and exits',
  no_line: 'Detecting people (line not set)',
  error: 'Error',
};

export default function LiveView() {
  const { cameras, camerasError, selectedCameraId, selectCamera, timezone, refreshCameras } = useSystem();
  const capture = useCapture();
  const camera = cameras.find((c) => c.id === selectedCameraId) ?? null;
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [, setTick] = useState(0);

  // Keep "last frame … ago" fresh.
  useEffect(() => {
    const t = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => setActionError(null), [selectedCameraId]);

  if (camerasError && cameras.length === 0) {
    return (
      <div className="banner banner-err" role="alert">
        <CircleAlert size={16} /> {camerasError}
      </div>
    );
  }
  if (cameras.length === 0) {
    return (
      <>
        <PageHead />
        <div className="panel">
          <div className="empty">
            <strong>No cameras configured</strong>
            An administrator can add the entrance camera in <Link href="/settings#cameras">Settings → Cameras</Link>.
          </div>
        </div>
      </>
    );
  }
  if (!camera) return null;

  const isBrowser = camera.source_type === 'browser';
  const capturingThis = capture.cameraId === camera.id && capture.state !== 'idle';
  const status = camera.runtime.status;
  const running = status !== 'stopped' && status !== 'ended';

  const act = async (action: 'start' | 'stop' | 'reconnect') => {
    setBusy(true);
    setActionError(null);
    try {
      if (isBrowser) {
        if (action === 'stop') await capture.stop();
        else await capture.start(camera.id);
      } else {
        await api(`/cameras/${encodeURIComponent(camera.id)}/${action}`, { method: 'POST' });
      }
      await refreshCameras();
    } catch (err) {
      setActionError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const captureBusy = capturingThis && (capture.state === 'requesting' || capture.state === 'starting');
  const otherDeviceStreaming = isBrowser && running && !capturingThis;

  return (
    <>
      <PageHead>
        <div className="control-row">
          <label className="sr-only" htmlFor="camera-select">
            Camera
          </label>
          <select id="camera-select" className="select" value={camera.id} onChange={(e) => selectCamera(e.target.value)}>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <CameraStatusBadge status={status} />
        </div>
      </PageHead>

      {(actionError || (capturingThis && capture.error)) && (
        <div className="banner banner-err" role="alert">
          <CircleAlert size={16} />
          <span>{actionError || capture.error}</span>
        </div>
      )}
      {status === 'error' && camera.runtime.message && !actionError && (
        <div className="banner banner-err" role="alert">
          <CircleAlert size={16} />
          <span>{camera.runtime.message}</span>
          <div className="banner-actions">
            <button type="button" className="btn btn-sm" onClick={() => act('reconnect')} disabled={busy}>
              Reconnect
            </button>
          </div>
        </div>
      )}
      {otherDeviceStreaming && (
        <div className="banner banner-info" role="note">
          <Smartphone size={16} />
          <span>
            This browser camera is started on the server{status === 'live' ? ' and another device is sending video' : ', waiting for a device to send video'}.
            Press Start Camera to use this device&apos;s camera instead.
          </span>
        </div>
      )}

      <div className="live-layout">
        <section className="panel" aria-labelledby="feed-title">
          <div className="panel-head">
            <h2 id="feed-title">
              {camera.name} <span className="sub">· {camera.location || SOURCE_LABELS[camera.source_type]}</span>
            </h2>
            <div className="control-row">
              <button type="button" className="btn btn-primary" onClick={() => act('start')} disabled={busy || captureBusy || (running && (!isBrowser || capturingThis))}>
                <Play size={14} /> {captureBusy ? (capture.state === 'requesting' ? 'Waiting for permission…' : 'Starting…') : 'Start Camera'}
              </button>
              <button type="button" className="btn" onClick={() => act('stop')} disabled={busy || (!running && !capturingThis)}>
                <Square size={14} /> Stop Camera
              </button>
              <button type="button" className="btn" onClick={() => act('reconnect')} disabled={busy || captureBusy || (!running && !(capturingThis && capture.state === 'error'))}>
                <RefreshCw size={14} /> Reconnect
              </button>
            </div>
          </div>
          <div className="panel-body">
            <LineEditorAndFeed camera={camera} timezone={timezone} onSaved={refreshCameras} />
          </div>
        </section>

        <aside className="panel" aria-label="Camera details">
          <div className="panel-head">
            <h2>Camera details</h2>
          </div>
          <div className="panel-body" style={{ display: 'grid', gap: 16 }}>
            <dl className="kv">
              <dt>Status</dt>
              <dd>
                <CameraStatusBadge status={status} />
              </dd>
              <dt>Last frame</dt>
              <dd>
                {camera.runtime.last_frame_at ? (
                  <>
                    {formatDateTime(camera.runtime.last_frame_at, timezone)}
                    <span className="muted small"> ({formatAgo(camera.runtime.last_frame_at)})</span>
                  </>
                ) : (
                  'No frame received'
                )}
              </dd>
              <dt>Frame rate</dt>
              <dd>{status === 'live' ? `${camera.runtime.fps} fps` : '—'}</dd>
              <dt>Source</dt>
              <dd>{camera.source_description}</dd>
              <dt>Detection</dt>
              <dd>{DETECTION_LABELS[camera.runtime.detection_status] ?? camera.runtime.detection_status}</dd>
              <dt>Tracked now</dt>
              <dd>{status === 'live' ? camera.runtime.tracked_people : '—'}</dd>
              <dt>Events this session</dt>
              <dd>{camera.runtime.events_recorded}</dd>
            </dl>

            {camera.runtime.detection_message && camera.runtime.detection_status !== 'active' && (
              <div className={`banner ${camera.runtime.detection_status === 'error' ? 'banner-err' : 'banner-warn'}`} style={{ marginBottom: 0 }}>
                <TriangleAlert size={16} />
                <span>{camera.runtime.detection_message}</span>
              </div>
            )}

            {isBrowser && (
              <div>
                <p className="section-title">Use a phone as this camera</p>
                <p className="muted small" style={{ marginBottom: 8 }}>
                  Open this page on the phone mounted at the entrance, sign in, and press Start. Phones need HTTPS for camera access.
                </p>
                <Link className="btn btn-sm" href={`/streamer?camera=${encodeURIComponent(camera.id)}`}>
                  <Smartphone size={14} /> Phone streamer page
                </Link>
              </div>
            )}

            <div>
              <p className="section-title">Testing entry and exit</p>
              <ol className="steps">
                <li>Start the camera and wait for Live.</li>
                <li>Draw the entrance line across the doorway and check the arrow points inside.</li>
                <li>Walk across the line toward the arrow (entry), then back (exit).</li>
                <li>Check the events in Entry &amp; Exit Logs.</li>
              </ol>
            </div>
          </div>
        </aside>
      </div>
    </>
  );
}

function PageHead({ children }: { children?: React.ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>Live Camera</h1>
        <p>Video shown here is what the server receives. A camera is Live only while frames arrive.</p>
      </div>
      {children}
    </div>
  );
}

function LineEditorAndFeed({ camera, timezone, onSaved }: { camera: Camera; timezone: string; onSaved: () => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [points, setPoints] = useState<Point[]>([]);
  const [side, setSide] = useState<1 | -1>(camera.line?.entry_side ?? 1);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setEditing(false);
    setPoints([]);
    setError(null);
  }, [camera.id]);

  const draft: EntranceLine | null =
    points.length === 2 ? { x1: points[0].x, y1: points[0].y, x2: points[1].x, y2: points[1].y, entry_side: side } : null;

  const begin = () => {
    setEditing(true);
    setPoints([]);
    setSide(camera.line?.entry_side ?? 1);
    setError(null);
  };

  const pick = (p: Point) => setPoints((prev) => (prev.length >= 2 ? [p] : [...prev, p]));

  const save = async () => {
    if (!draft) return;
    if (lineLength(draft) < 0.05) {
      setError('The line is too short. Draw it across the full doorway.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api(`/cameras/${encodeURIComponent(camera.id)}/line`, { method: 'PUT', body: draft });
      await onSaved();
      setEditing(false);
      setPoints([]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const flipSaved = async () => {
    if (!camera.line) return;
    setSaving(true);
    try {
      await api(`/cameras/${encodeURIComponent(camera.id)}/line`, { method: 'PUT', body: { ...camera.line, entry_side: camera.line.entry_side === 1 ? -1 : 1 } });
      await onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <LiveFeed camera={camera} timezone={timezone} onPick={editing ? pick : undefined} draftLine={editing ? draft : undefined} draftPoints={editing ? points : undefined} />
      <div className="control-row" style={{ justifyContent: 'space-between' }}>
        {editing ? (
          <>
            <span className="small muted" role="status">
              {points.length < 2
                ? `Click ${points.length === 0 ? 'the first' : 'the second'} end of the entrance line on the video.`
                : 'The arrow must point into the PG. Flip it if needed, then save.'}
            </span>
            <div className="control-row">
              <button type="button" className="btn" onClick={() => setSide((s) => (s === 1 ? -1 : 1))} disabled={!draft}>
                <ArrowLeftRight size={14} /> Flip direction
              </button>
              <button type="button" className="btn" onClick={() => setEditing(false)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" onClick={save} disabled={!draft || saving}>
                Save line
              </button>
            </div>
          </>
        ) : (
          <>
            <span className="small muted">
              {camera.line ? 'Entrance line set. People crossing toward the arrow are recorded as entries.' : 'No entrance line yet: people are detected but not counted.'}
            </span>
            <div className="control-row">
              {camera.line && (
                <button type="button" className="btn" onClick={flipSaved} disabled={saving}>
                  <ArrowLeftRight size={14} /> Flip direction
                </button>
              )}
              <button type="button" className="btn" onClick={begin} disabled={camera.runtime.status !== 'live'} title={camera.runtime.status !== 'live' ? 'Start the camera to draw on the live image' : undefined}>
                <Pencil size={14} /> {camera.line ? 'Redraw line' : 'Draw entrance line'}
              </button>
            </div>
          </>
        )}
      </div>
      {error && (
        <div className="banner banner-err" role="alert" style={{ marginBottom: 0 }}>
          {error}
        </div>
      )}
    </div>
  );
}
