/**
 * Same-origin API client. Requests go through the Next.js rewrite to the backend, carry the
 * httpOnly session cookie, and state-changing requests add the CSRF header the backend requires.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

type Listener = () => void;
const unauthorizedListeners = new Set<Listener>();

export function onUnauthorized(listener: Listener): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

function describe(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : '';
        const msg = (d.msg || 'Invalid value').replace(/^Value error, /, '');
        return field && field !== 'body' ? `${String(field).replace(/_/g, ' ')}: ${msg}` : msg;
      })
      .join(' ');
  }
  if (status >= 500) return 'The server could not complete the request. Check that the backend is running.';
  return `Request failed (${status}).`;
}

export async function api<T = unknown>(
  path: string,
  options: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const method = options.method || 'GET';
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') headers['X-VV-CSRF'] = '1';

  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, {
      method,
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      credentials: 'same-origin',
      cache: 'no-store',
      signal: options.signal,
    });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError(0, 'Cannot reach the VIAHIND Vision server. Check the network connection and that the backend is running.');
  }

  if (res.status === 401 && path !== '/auth/login') {
    unauthorizedListeners.forEach((l) => l());
  }
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error body (e.g. proxy error) */
    }
    if (res.status === 500 && detail === null) {
      throw new ApiError(502, 'The backend is not responding. Start it with "uvicorn main:app" in backend/.');
    }
    throw new ApiError(res.status, describe(detail, res.status));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function queryString(params: Record<string, string | number | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== '') q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : '';
}

export const snapshotUrl = (eventId: string) => `/api/v1/events/${encodeURIComponent(eventId)}/snapshot`;
