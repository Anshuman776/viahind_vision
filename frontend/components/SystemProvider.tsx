'use client';

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { Camera, CameraRuntime, SettingsResponse } from '@/lib/types';
import { wsUrl } from '@/lib/ws';

interface SystemValue {
  settings: SettingsResponse | null;
  timezone: string;
  cameras: Camera[];
  camerasError: string | null;
  selectedCameraId: string | null;
  selectCamera: (id: string) => void;
  /** Real-time channel to the backend is open. */
  connected: boolean;
  /** Increments whenever events, reviews or occupancy change on the server. */
  dataVersion: number;
  refreshCameras: () => Promise<void>;
  refreshSettings: () => Promise<void>;
}

const SystemContext = createContext<SystemValue | null>(null);

export function useSystem(): SystemValue {
  const value = useContext(SystemContext);
  if (!value) throw new Error('useSystem must be used inside SystemProvider');
  return value;
}

const STORAGE_KEY = 'vv.selectedCamera';

function readStoredCamera(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function SystemProvider({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [camerasError, setCamerasError] = useState<string | null>(null);
  const [selectedCameraId, setSelected] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [dataVersion, setDataVersion] = useState(0);
  const retry = useRef(0);

  const refreshCameras = useCallback(async () => {
    try {
      const list = await api<Camera[]>('/cameras');
      setCameras(list);
      setCamerasError(null);
      setSelected((current) => {
        const stored = current ?? readStoredCamera();
        if (stored && list.some((c) => c.id === stored)) return stored;
        return list[0]?.id ?? null;
      });
    } catch (err) {
      setCamerasError((err as Error).message);
    }
  }, []);

  const refreshSettings = useCallback(async () => {
    try {
      setSettings(await api<SettingsResponse>('/settings'));
    } catch {
      /* shown by pages that need it */
    }
  }, []);

  useEffect(() => {
    refreshCameras();
    refreshSettings();
    const timer = window.setInterval(refreshCameras, 5000);
    return () => window.clearInterval(timer);
  }, [refreshCameras, refreshSettings]);

  // System channel: camera status changes and newly persisted events.
  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: number | undefined;
    let closed = false;

    const connect = () => {
      socket = new WebSocket(wsUrl('/ws/alerts'));
      socket.onopen = () => {
        retry.current = 0;
        setConnected(true);
      };
      socket.onmessage = (msg) => {
        let data: { type?: string; camera_id?: string; status?: CameraRuntime };
        try {
          data = JSON.parse(msg.data);
        } catch {
          return;
        }
        if (data.type === 'camera_status' && data.camera_id && data.status) {
          const runtime = data.status;
          setCameras((list) => list.map((c) => (c.id === data.camera_id ? { ...c, runtime } : c)));
        } else if (data.type === 'event_recorded' || data.type === 'event_updated' || data.type === 'occupancy' || data.type === 'anomaly') {
          setDataVersion((v) => v + 1);
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (closed) return;
        const delay = Math.min(15000, 1000 * 2 ** retry.current++);
        timer = window.setTimeout(connect, delay);
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      socket?.close();
    };
  }, []);

  const selectCamera = useCallback((id: string) => {
    setSelected(id);
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* storage unavailable: selection lasts for this session */
    }
  }, []);

  return (
    <SystemContext.Provider
      value={{
        settings,
        timezone: settings?.site.timezone || 'Asia/Kolkata',
        cameras,
        camerasError,
        selectedCameraId,
        selectCamera,
        connected,
        dataVersion,
        refreshCameras,
        refreshSettings,
      }}
    >
      {children}
    </SystemContext.Provider>
  );
}
