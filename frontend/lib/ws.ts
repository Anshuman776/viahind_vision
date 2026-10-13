/**
 * WebSocket base URL. The backend authenticates WebSockets with the same session cookie
 * (cookies are shared across ports on the same hostname) and checks the Origin header.
 *
 * Override with NEXT_PUBLIC_WS_URL (e.g. wss://surveillance.example.com or the legacy
 * ws://localhost:8000/ws/alerts form) when the backend is behind a reverse proxy.
 */
export function wsBase(): string {
  const configured = process.env.NEXT_PUBLIC_WS_URL;
  if (configured) return configured.replace(/\/ws\/alerts\/?$/, '').replace(/\/$/, '');
  if (typeof window === 'undefined') return 'ws://localhost:8000';
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.hostname}:8000`;
}

export function wsUrl(path: string): string {
  return `${wsBase()}${path}`;
}
