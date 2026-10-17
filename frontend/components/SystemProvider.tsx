'use client';

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { Camera, CameraRuntime, Location, SettingsResponse } from '@/lib/types';
import { wsUrl } from '@/lib/ws';
import { useSession } from './SessionProvider';

interface SystemValue {
  settings: SettingsResponse | null;
  timezone: string;
  cameras: Camera[];
  camerasError: string | null;
  selectedCameraId: string | null;
  selectCamera: (id: string) => void;
  locations: Location[];
  /** Location filter shared by Overview, Alerts, Evidence and Reports. null = all locations. */
  locationId: number | null;
  selectLocation: (id: number | null) => void;
  /** New (unacknowledged) alerts for the navigation badge; 0 for viewers. */
  newAlerts: number;
  /** Real-time channel to the backend is open. */
  connected: boolean;
  /** Increments whenever events, reviews or occupancy change on the server. */
  dataVersion: number;
  /** Increments whenever an alert is raised or reviewed. */
  alertVersion: number;
  refreshCameras: () => Promise<void>;
  refreshSettings: () => Promise<void>;
  refreshLocations: () => Promise<void>;
}

const SystemContext = createContext<SystemValue | null>(null);

export function useSystem(): SystemValue {
  const value = useContext(SystemContext);
  if (!value) throw new Error('useSystem must be used inside SystemProvider');
  return value;
}

const STORAGE_KEY = 'vv.selectedCamera';
const LOCATION_KEY = 'vv.location';

function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: selection lasts for this session */
  }
}

export function SystemProvider({ children }: { children: React.ReactNode }) {
  const { isOperator } = useSession();
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [camerasError, setCamerasError] = useState<string | null>(null);
  const [selectedCameraId, setSelected] = useState<string | null>(null);
  const [locations, setLocations] = useState<Location[]>([]);
  const [locationId, setLocationId] = useState<number | null>(null);
  const [newAlerts, setNewAlerts] = useState(0);
  const [connected, setConnected] = useState(false);
  const [dataVersion, setDataVersion] = useState(0);
  const [alertVersion, setAlertVersion] = useState(0);
  const retry = useRef(0);

  const refreshCameras = useCallback(async () => {
    try {
      const list = await api<Camera[]>('/cameras');
      setCameras(list);
      setCamerasError(null);
      setSelected((current) => {
        const stored = current ?? readStored(STORAGE_KEY);
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

  const refreshLocations = useCallback(async () => {
    try {
      const list = await api<Location[]>('/locations');
      setLocations(list);
      setLocationId((current) => {
        const stored = current ?? Number(readStored(LOCATION_KEY) || NaN);
        return Number.isFinite(stored) && list.some((l) => l.id === stored) ? stored : null;
      });
    } catch {
      /* the location switcher stays hidden */
    }
  }, []);

  const refreshAlertCount = useCallback(async () => {
    if (!isOperator) return;
    try {
      setNewAlerts((await api<{ new: number }>('/alerts/summary')).new);
    } catch {
      /* badge is informational */
    }
  }, [isOperator]);

  useEffect(() => {
    refreshCameras();
    refreshSettings();
    refreshLocations();
    refreshAlertCount();
    const timer = window.setInterval(refreshCameras, 5000);
    const alertTimer = window.setInterval(refreshAlertCount, 60000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(alertTimer);
    };
  }, [refreshCameras, refreshSettings, refreshLocations, refreshAlertCount]);

  // System channel: camera status changes, newly persisted events and alerts (organization-scoped on the server).
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
        } else if (data.type === 'alert' || data.type === 'alert_updated') {
          setAlertVersion((v) => v + 1);
          refreshAlertCount();
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
  }, [refreshAlertCount]);

  const selectCamera = useCallback((id: string) => {
    setSelected(id);
    store(STORAGE_KEY, id);
  }, []);

  const selectLocation = useCallback((id: number | null) => {
    setLocationId(id);
    store(LOCATION_KEY, id === null ? null : String(id));
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
        locations,
        locationId,
        selectLocation,
        newAlerts,
        connected,
        dataVersion,
        alertVersion,
        refreshCameras,
        refreshSettings,
        refreshLocations,
      }}
    >
      {children}
    </SystemContext.Provider>
  );
}
