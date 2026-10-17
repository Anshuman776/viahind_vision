/**
 * WebSocket base URL. The backend authenticates WebSockets with the same session cookie and
 * checks the Origin header.
 *
 * - Production (behind the HTTPS reverse proxy, e.g. https://pg.example.com): same origin. The proxy
 *   routes /ws/* to the backend, so no extra port has to be open.
 * - Development (Next.js dev server on :3000): the backend on :8000 of the same hostname.
 * - NEXT_PUBLIC_WS_URL (build time) overrides both, e.g. wss://api.example.com.
 */
export function wsBase(): string {
  const configured = process.env.NEXT_PUBLIC_WS_URL;
  if (configured) return configured.replace(/\/ws\/alerts\/?$/, '').replace(/\/$/, '');
  if (typeof window === 'undefined') return 'ws://localhost:8000';
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  if (window.location.port === '3000') return `${proto}://${window.location.hostname}:8000`;
  return `${proto}://${window.location.host}`;
}

export function wsUrl(path: string): string {
  return `${wsBase()}${path}`;
}
