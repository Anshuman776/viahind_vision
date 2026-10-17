import { describe, expect, it, vi, afterEach } from 'vitest';
import { formatAgo, formatDuration, formatTime, siteToday } from '@/lib/format';
import { lineGeometry } from '@/lib/geometry';
import { filterParams, type LogFilters } from '@/lib/filters';
import { api, ApiError, onUnauthorized, queryString } from '@/lib/api';

describe('format', () => {
  it('formats times in the site timezone, not the browser timezone', () => {
    const utc = '2026-10-12T03:12:15+00:00';
    expect(formatTime(utc, 'Asia/Kolkata')).toBe('08:42:15 AM');
    expect(formatTime(utc, 'UTC')).toBe('03:12:15 AM');
  });

  it('computes the site calendar day', () => {
    // 20:00 UTC is already the next day in India.
    expect(siteToday('Asia/Kolkata', new Date('2026-10-12T20:00:00Z'))).toBe('2026-10-13');
    expect(siteToday('UTC', new Date('2026-10-12T20:00:00Z'))).toBe('2026-10-12');
  });

  it('formats durations and missing durations', () => {
    expect(formatDuration(null)).toBe('—');
    expect(formatDuration(45)).toBe('45 s');
    expect(formatDuration(9381)).toBe('2 h 36 min');
  });

  it('formats relative times', () => {
    expect(formatAgo(null)).toBe('never');
    expect(formatAgo(1000, 1030)).toBe('30 s ago');
  });
});

describe('entrance line geometry (mirrors backend line_crossing.py)', () => {
  it('points inside to the left-hand normal for entry_side=1', () => {
    // Left-to-right horizontal line: the left-hand normal in image coordinates points down.
    const g = lineGeometry({ x1: 0.1, y1: 0.5, x2: 0.9, y2: 0.5, entry_side: 1 }, 640, 480);
    expect(g.inside.y).toBeGreaterThan(g.mid.y);
    expect(g.outside.y).toBeLessThan(g.mid.y);
  });

  it('flips with entry_side=-1', () => {
    const g = lineGeometry({ x1: 0.1, y1: 0.5, x2: 0.9, y2: 0.5, entry_side: -1 }, 640, 480);
    expect(g.inside.y).toBeLessThan(g.mid.y);
  });
});

describe('log filters', () => {
  const base: LogFilters = { range: 'today', from: '', to: '', eventType: '', cameraId: '', q: '', review: '' };

  it('maps "today" to the site date', () => {
    expect(filterParams(base, '2026-10-13')).toEqual({ date_from: '2026-10-13', date_to: '2026-10-13' });
  });

  it('includes only filters that are set', () => {
    const params = filterParams({ ...base, range: 'all', eventType: 'exit', q: '  Person 04 ', review: 'needs_review' }, '2026-10-13');
    expect(params).toEqual({ event_type: 'exit', q: 'Person 04', review_status: 'needs_review' });
    expect(queryString({ a: 1, b: '', c: null })).toBe('?a=1');
  });
});

describe('api client', () => {
  afterEach(() => vi.restoreAllMocks());

  it('sends the CSRF header on state-changing requests only', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response('{}', { status: 200 }));
    await api('/events');
    await api('/occupancy/reconcile', { method: 'POST', body: { count: 1, reason: 'x' } });
    const getInit = fetchMock.mock.calls[0][1]!;
    const postInit = fetchMock.mock.calls[1][1]!;
    expect((getInit.headers as Record<string, string>)['X-VV-CSRF']).toBeUndefined();
    expect((postInit.headers as Record<string, string>)['X-VV-CSRF']).toBe('1');
    expect(postInit.credentials).toBe('same-origin');
  });

  it('turns validation errors into readable messages', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: [{ loc: ['body', 'timezone'], msg: 'Value error, Unknown timezone.' }] }), { status: 422 }),
    );
    await expect(api('/settings', { method: 'PUT', body: {} })).rejects.toThrow('timezone: Unknown timezone.');
  });

  it('notifies listeners when the session has expired', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ detail: 'Not signed in.' }), { status: 401 }));
    const listener = vi.fn();
    const off = onUnauthorized(listener);
    await expect(api('/overview')).rejects.toBeInstanceOf(ApiError);
    expect(listener).toHaveBeenCalledOnce();
    off();
  });

  it('reports an unreachable server clearly', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(api('/overview')).rejects.toThrow(/Cannot reach the VIAHIND Vision server/);
  });
});

describe('wsUrl', () => {
  const original = window.location;
  const at = (url: string) => {
    Object.defineProperty(window, 'location', { value: new URL(url), configurable: true });
  };
  afterEach(() => {
    Object.defineProperty(window, 'location', { value: original, configurable: true });
  });

  it('uses the same origin behind the HTTPS proxy (no port 8000 on the internet)', async () => {
    const { wsUrl } = await import('@/lib/ws');
    at('https://pg.example.com/live');
    expect(wsUrl('/ws/alerts')).toBe('wss://pg.example.com/ws/alerts');
  });

  it('uses the backend port next to the dev server', async () => {
    const { wsUrl } = await import('@/lib/ws');
    at('http://192.168.1.20:3000/live');
    expect(wsUrl('/ws/live/CAM-1')).toBe('ws://192.168.1.20:8000/ws/live/CAM-1');
  });
});
