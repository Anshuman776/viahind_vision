'use client';

import { useEffect, useRef, useState } from 'react';
import { CameraOff, CircleAlert, RefreshCw, VideoOff } from 'lucide-react';
import { lineGeometry, clamp01, type Point } from '@/lib/geometry';
import type { Camera, EntranceLine, LiveFrame } from '@/lib/types';
import { formatTime } from '@/lib/format';
import { wsUrl } from '@/lib/ws';

interface Props {
  camera: Camera;
  timezone: string;
  /** When set, clicks on the video pick points for the entrance line. */
  onPick?: (p: Point) => void;
  /** Line to draw instead of the saved one (while editing). */
  draftLine?: EntranceLine | null;
  draftPoints?: Point[];
  /** Zone polygon being drawn. */
  draftPolygon?: Point[];
  showOverlay?: boolean;
}

export const ZONE_COLORS = { restricted: '#e5484d', monitored: '#3e9bd6' } as const;

const LINE_COLOR = '#f5b700';

export function LiveFeed({ camera, timezone, onPick, draftLine, draftPoints, draftPolygon, showOverlay = true }: Props) {
  const [frame, setFrame] = useState<LiveFrame | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const status = camera.runtime.status;

  useEffect(() => {
    setFrame(null);
    let socket: WebSocket | null = null;
    let timer: number | undefined;
    let closed = false;
    const connect = () => {
      socket = new WebSocket(wsUrl(`/ws/live/${encodeURIComponent(camera.id)}`));
      socket.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data);
          if (data.type === 'frame') setFrame(data as LiveFrame);
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = () => {
        if (!closed) timer = window.setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      socket?.close();
    };
  }, [camera.id]);

  const width = frame?.width ?? 1280;
  const height = frame?.height ?? 720;
  const showVideo = frame !== null && status === 'live';
  const line = draftLine !== undefined ? draftLine : camera.line;

  const handleClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!onPick || !svgRef.current) return;
    const ctm = svgRef.current.getScreenCTM();
    if (!ctm) return;
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse());
    onPick({ x: clamp01(pt.x / width), y: clamp01(pt.y / height) });
  };

  return (
    <div>
      <div
        className={`video-stage${onPick ? ' editing' : ''}`}
        style={frame ? { aspectRatio: `${width} / ${height}` } : undefined}
        aria-label={`Live view of ${camera.name}`}
      >
        {showVideo ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={frame.image} alt={`Live frame from ${camera.name}`} />
        ) : (
          <Placeholder camera={camera} hasFrame={frame !== null} />
        )}

        {(showVideo || onPick) && (
          <svg
            ref={svgRef}
            className="overlay"
            viewBox={`0 0 ${width} ${height}`}
            preserveAspectRatio="xMidYMid meet"
            onClick={handleClick}
            role={onPick ? 'application' : undefined}
            aria-label={onPick ? 'Click two points to draw the entrance line' : undefined}
          >
            {showOverlay && showVideo &&
              frame.tracks.map((t, i) => {
                const [x1, y1, x2, y2] = t.box;
                const tracked = t.track_id !== null;
                const color = !tracked ? '#9aa0a6' : t.side === 'inside' ? '#5fb37c' : t.side === 'outside' ? '#6aa6e8' : '#d7dade';
                const text = t.label ?? (tracked ? `Track ${t.track_id}` : 'Person');
                return (
                  <g key={`${t.track_id ?? 'u'}-${i}`}>
                    <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill="none" stroke={color} strokeWidth={Math.max(2, width / 400)} />
                    <rect x={x1} y={Math.max(0, y1 - height * 0.04)} width={Math.max(60, text.length * width * 0.0085)} height={height * 0.04} fill={color} />
                    <text x={x1 + 4} y={Math.max(height * 0.03, y1 - height * 0.01)} fontSize={height * 0.028} fill="#111">
                      {text}
                    </text>
                  </g>
                );
              })}
            {showOverlay &&
              (frame?.zones ?? camera.zones.filter((z) => z.enabled).map((z) => ({ ...z, count: 0 }))).map((z) => (
                <g key={z.id} pointerEvents="none">
                  <polygon
                    points={z.polygon.map(([x, y]) => `${x * width},${y * height}`).join(' ')}
                    fill={ZONE_COLORS[z.kind]}
                    fillOpacity={0.12}
                    stroke={ZONE_COLORS[z.kind]}
                    strokeWidth={Math.max(2, width / 500)}
                    strokeDasharray={z.kind === 'monitored' ? `${width / 120} ${width / 200}` : undefined}
                  />
                  <text
                    x={z.polygon[0][0] * width + 6}
                    y={z.polygon[0][1] * height + height * 0.035}
                    fontSize={height * 0.028}
                    fill="#fff"
                    stroke="#111"
                    strokeWidth={height / 400}
                    paintOrder="stroke"
                  >
                    {z.name}
                    {showVideo && z.count > 0 ? ` · ${z.count}` : ''}
                  </text>
                </g>
              ))}
            {draftPolygon && draftPolygon.length > 0 && (
              <g pointerEvents="none">
                <polyline
                  points={draftPolygon.map((p) => `${p.x * width},${p.y * height}`).join(' ') + (draftPolygon.length > 2 ? ` ${draftPolygon[0].x * width},${draftPolygon[0].y * height}` : '')}
                  fill={draftPolygon.length > 2 ? 'rgba(245,183,0,0.15)' : 'none'}
                  stroke={LINE_COLOR}
                  strokeWidth={Math.max(2, width / 400)}
                />
                {draftPolygon.map((p, i) => (
                  <circle key={i} cx={p.x * width} cy={p.y * height} r={Math.max(4, width / 200)} fill={LINE_COLOR} stroke="#111" strokeWidth={2} />
                ))}
              </g>
            )}
            {line && <LineOverlay line={line} width={width} height={height} />}
            {draftPoints?.map((p, i) => (
              <circle key={i} cx={p.x * width} cy={p.y * height} r={Math.max(5, width / 160)} fill={LINE_COLOR} stroke="#111" strokeWidth={2} />
            ))}
          </svg>
        )}

        {showVideo && (
          <div className="video-hud">
            <span className="hud-chip">
              <span className="dot" style={{ color: '#5fd38d' }} aria-hidden="true" />
              Live · {formatTime(frame.ts, timezone)}
            </span>
            {frame.tracks.length > 0 && (
              <span className="hud-chip">
                {frame.tracks.length} {frame.tracks.length === 1 ? 'person' : 'people'} in view
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function LineOverlay({ line, width, height }: { line: EntranceLine; width: number; height: number }) {
  const g = lineGeometry(line, width, height);
  const sw = Math.max(3, width / 300);
  const fs = Math.min(width, height) * 0.04;
  return (
    <g pointerEvents="none">
      <defs>
        <marker id="vv-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill={LINE_COLOR} />
        </marker>
      </defs>
      <line x1={g.a.x} y1={g.a.y} x2={g.b.x} y2={g.b.y} stroke="#111" strokeWidth={sw + 3} strokeLinecap="round" opacity={0.5} />
      <line x1={g.a.x} y1={g.a.y} x2={g.b.x} y2={g.b.y} stroke={LINE_COLOR} strokeWidth={sw} strokeLinecap="round" />
      <line x1={g.mid.x} y1={g.mid.y} x2={g.inside.x} y2={g.inside.y} stroke={LINE_COLOR} strokeWidth={sw} markerEnd="url(#vv-arrow)" />
      <text x={g.inside.x + g.normal.x * fs} y={g.inside.y + g.normal.y * fs + fs / 3} fontSize={fs} fill={LINE_COLOR} stroke="#111" strokeWidth={fs / 10} paintOrder="stroke" textAnchor="middle" fontWeight={700}>
        INSIDE
      </text>
      <text x={g.outside.x} y={g.outside.y + fs / 3} fontSize={fs * 0.8} fill="#fff" stroke="#111" strokeWidth={fs / 12} paintOrder="stroke" textAnchor="middle">
        outside
      </text>
    </g>
  );
}

function Placeholder({ camera, hasFrame }: { camera: Camera; hasFrame: boolean }) {
  const { status, message } = camera.runtime;
  let icon = <VideoOff size={28} aria-hidden="true" />;
  let title = 'Camera stopped';
  let text = 'Press Start Camera to begin monitoring.';
  if (status === 'connecting') {
    icon = <RefreshCw size={28} className="spin" aria-hidden="true" />;
    title = 'Connecting…';
    text = message || 'Waiting for the first frame.';
  } else if (status === 'live' && !hasFrame) {
    icon = <RefreshCw size={28} className="spin" aria-hidden="true" />;
    title = 'Receiving video';
    text = 'The first frame is on its way.';
  } else if (status === 'disconnected') {
    icon = <CameraOff size={28} aria-hidden="true" />;
    title = 'Disconnected';
    text = message || 'No frames are arriving. Reconnecting automatically.';
  } else if (status === 'error') {
    icon = <CircleAlert size={28} aria-hidden="true" />;
    title = 'Camera error';
    text = message || 'The camera could not be opened.';
  } else if (status === 'ended') {
    title = 'Test clip finished';
    text = message;
  }
  return (
    <div className="video-placeholder" role="status">
      {icon}
      <strong>{title}</strong>
      {text}
    </div>
  );
}
