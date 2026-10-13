'use client';

/**
 * Browser camera capture (laptop/USB webcam or a phone) for cameras of type "browser".
 * Camera permission is requested only when an operator presses Start. Frames are sent as
 * JPEG over an authenticated WebSocket; the backend decides when the camera is "Live".
 */

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { wsUrl } from '@/lib/ws';

export type CaptureState = 'idle' | 'requesting' | 'starting' | 'streaming' | 'error';

interface CaptureValue {
  cameraId: string | null;
  state: CaptureState;
  error: string | null;
  /** Local camera stream (for an aiming preview on the capturing device). */
  stream: MediaStream | null;
  start: (cameraId: string, opts?: { facingMode?: 'user' | 'environment' }) => Promise<void>;
  stop: () => Promise<void>;
}

const CaptureContext = createContext<CaptureValue | null>(null);

export function useCapture(): CaptureValue {
  const value = useContext(CaptureContext);
  if (!value) throw new Error('useCapture must be used inside CaptureProvider');
  return value;
}

const FRAME_INTERVAL_MS = 125; // ~8 fps; the backend detector processes the latest frame only
const MAX_WIDTH = 960;
const MAX_BUFFERED = 1_500_000;

export function mediaErrorMessage(err: unknown): string {
  const name = (err as { name?: string })?.name;
  switch (name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return 'Camera permission was denied. Allow camera access for this site in your browser settings, then press Start Camera again.';
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'No camera was found on this device. Connect a webcam and try again.';
    case 'NotReadableError':
    case 'AbortError':
      return 'The camera could not be opened. It may be in use by another application.';
    default:
      return 'The camera could not be started.';
  }
}

const CLOSE_MESSAGES: Record<number, string> = {
  1008: 'The server refused the stream. Your session may have expired; sign in again.',
  1009: 'Frames are larger than the server accepts.',
  4009: 'Another device started streaming this camera.',
  4404: 'The server is not accepting frames for this camera (it was stopped or is not a browser camera).',
};

export function CaptureProvider({ children }: { children: React.ReactNode }) {
  const [cameraId, setCameraId] = useState<string | null>(null);
  const [state, setState] = useState<CaptureState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | undefined>(undefined);
  const stoppingRef = useRef(false);

  const releaseLocal = useCallback(() => {
    window.clearInterval(timerRef.current);
    timerRef.current = undefined;
    const socket = socketRef.current;
    socketRef.current = null;
    if (socket && socket.readyState <= WebSocket.OPEN) socket.close();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setStream(null);
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  const fail = useCallback(
    (message: string) => {
      releaseLocal();
      setError(message);
      setState('error');
    },
    [releaseLocal],
  );

  const stop = useCallback(async () => {
    stoppingRef.current = true;
    const id = cameraId;
    releaseLocal();
    setState('idle');
    setError(null);
    setCameraId(null);
    if (id) {
      try {
        await api(`/cameras/${encodeURIComponent(id)}/stop`, { method: 'POST' });
      } catch {
        /* the camera is reported disconnected by the backend if this fails */
      }
    }
  }, [cameraId, releaseLocal]);

  const start = useCallback(
    async (id: string, opts: { facingMode?: 'user' | 'environment' } = {}) => {
      releaseLocal();
      stoppingRef.current = false;
      setCameraId(id);
      setError(null);

      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        fail('Camera access needs a secure page (https:// or http://localhost). Open VIAHIND Vision over HTTPS on this device.');
        return;
      }
      setState('requesting');
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1280 }, height: { ideal: 720 }, ...(opts.facingMode ? { facingMode: { ideal: opts.facingMode } } : {}) },
          audio: false,
        });
      } catch (err) {
        fail(mediaErrorMessage(err));
        return;
      }
      streamRef.current = stream;
      setStream(stream);
      const video = videoRef.current!;
      video.srcObject = stream;
      try {
        await video.play();
      } catch {
        /* autoplay of a muted stream is allowed; frames still render */
      }

      setState('starting');
      try {
        await api(`/cameras/${encodeURIComponent(id)}/start`, { method: 'POST' });
      } catch (err) {
        fail((err as Error).message);
        return;
      }

      const socket = new WebSocket(wsUrl(`/ws/stream/${encodeURIComponent(id)}`));
      socketRef.current = socket;
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');

      socket.onopen = () => {
        setState('streaming');
        timerRef.current = window.setInterval(() => {
          if (socket.readyState !== WebSocket.OPEN || !ctx || video.videoWidth === 0) return;
          if (socket.bufferedAmount > MAX_BUFFERED) return; // slow network: skip, never queue
          const scale = Math.min(1, MAX_WIDTH / video.videoWidth);
          canvas.width = Math.round(video.videoWidth * scale);
          canvas.height = Math.round(video.videoHeight * scale);
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          canvas.toBlob((blob) => {
            if (blob && socket.readyState === WebSocket.OPEN) socket.send(blob);
          }, 'image/jpeg', 0.75);
        }, FRAME_INTERVAL_MS);
      };
      socket.onclose = (e) => {
        if (stoppingRef.current || socketRef.current !== socket) return;
        fail(CLOSE_MESSAGES[e.code] || 'The connection to the server was lost. Press Reconnect to resume.');
      };
      // Tracks end if the webcam is unplugged or the OS revokes access.
      stream.getVideoTracks().forEach((track) => {
        track.onended = () => {
          if (!stoppingRef.current) fail('The camera stopped providing video (unplugged or access revoked).');
        };
      });
    },
    [fail, releaseLocal],
  );

  useEffect(() => releaseLocal, [releaseLocal]);

  return (
    <CaptureContext.Provider value={{ cameraId, state, error, stream, start, stop }}>
      {children}
      {/* Off-screen source for frame capture; the visible view shows what the backend receives. */}
      <video
        ref={videoRef}
        muted
        playsInline
        aria-hidden="true"
        style={{ position: 'fixed', width: 2, height: 2, opacity: 0, pointerEvents: 'none', left: -10, top: -10 }}
      />
    </CaptureContext.Provider>
  );
}
