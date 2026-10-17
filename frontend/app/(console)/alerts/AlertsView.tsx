'use client';

import { useCallback, useEffect, useState } from 'react';
import { Camera as CameraIcon, ChevronLeft, ChevronRight, CircleAlert, Image as ImageIcon } from 'lucide-react';
import { api, queryString } from '@/lib/api';
import { CATEGORY_LABELS, formatDateTime } from '@/lib/format';
import type { AlertPage } from '@/lib/types';
import { useSystem } from '@/components/SystemProvider';
import { AlertStatusBadge, SeverityBadge } from '@/components/AlertBadges';
import { AlertDrawer } from '@/components/AlertDrawer';

const PAGE_SIZE = 25;

export default function AlertsView() {
  const { timezone, alertVersion, locationId, cameras } = useSystem();
  const [status, setStatus] = useState('open');
  const [severity, setSeverity] = useState('');
  const [category, setCategory] = useState('');
  const [cameraId, setCameraId] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState<AlertPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Deep link from notification emails: /alerts?id=<alert id>
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get('id');
    if (id) setOpenId(id);
  }, []);

  const load = useCallback(async () => {
    try {
      const q = queryString({ status, severity, category, camera_id: cameraId, location_id: locationId, page, page_size: PAGE_SIZE });
      setData(await api<AlertPage>(`/alerts${q}`));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [status, severity, category, cameraId, locationId, page]);

  useEffect(() => {
    load();
  }, [load, alertVersion]);

  useEffect(() => setSelected(new Set()), [data]);

  const filter = (setter: (v: string) => void) => (e: React.ChangeEvent<HTMLSelectElement>) => {
    setter(e.target.value);
    setPage(1);
  };

  const bulk = async (action: 'acknowledge' | 'resolve' | 'dismiss') => {
    try {
      await api(`/alerts/bulk${queryString({ action })}`, { method: 'POST', body: [...selected] });
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Alerts</h1>
          <p>Each alert explains what was measured. Review it, then resolve it or dismiss it as a false positive.</p>
        </div>
      </div>

      {error && (
        <div className="banner banner-err" role="alert">
          <CircleAlert size={16} /> {error}
        </div>
      )}

      <section className="panel">
        <div className="filters">
          <div className="field">
            <label htmlFor="a-status">Status</label>
            <select id="a-status" className="select" value={status} onChange={filter(setStatus)}>
              <option value="open">Open (new + acknowledged)</option>
              <option value="new">New</option>
              <option value="acknowledged">Acknowledged</option>
              <option value="resolved">Resolved</option>
              <option value="dismissed">Dismissed</option>
              <option value="">All</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="a-sev">Severity</label>
            <select id="a-sev" className="select" value={severity} onChange={filter(setSeverity)}>
              <option value="">All</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
              <option value="info">Info</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="a-cat">Type</label>
            <select id="a-cat" className="select" value={category} onChange={filter(setCategory)}>
              <option value="">All</option>
              {(data?.categories ?? Object.keys(CATEGORY_LABELS)).map((c) => (
                <option key={c} value={c}>
                  {CATEGORY_LABELS[c] ?? c}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="a-cam">Camera</label>
            <select id="a-cam" className="select" value={cameraId} onChange={filter(setCameraId)}>
              <option value="">All</option>
              {cameras
                .filter((c) => locationId === null || c.location_id === locationId)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
            </select>
          </div>
          {selected.size > 0 && (
            <div className="control-row" style={{ marginLeft: 'auto' }}>
              <span className="small muted">{selected.size} selected</span>
              <button type="button" className="btn btn-sm" onClick={() => bulk('acknowledge')}>
                Acknowledge
              </button>
              <button type="button" className="btn btn-sm" onClick={() => bulk('resolve')}>
                Resolve
              </button>
              <button type="button" className="btn btn-sm" onClick={() => bulk('dismiss')}>
                Dismiss
              </button>
            </div>
          )}
        </div>

        {!data ? (
          <p className="empty">Loading…</p>
        ) : data.items.length === 0 ? (
          <div className="empty">
            <strong>{status === 'open' ? 'No open alerts' : 'No alerts match these filters'}</strong>
            {status === 'open' ? 'Configured rules are running; new alerts appear here in real time.' : 'Try another status or type.'}
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: 32 }}>
                    <span className="sr-only">Select</span>
                  </th>
                  <th>Severity</th>
                  <th>Alert</th>
                  <th>Where</th>
                  <th>Last seen</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((a) => (
                  <tr key={a.id} className="clickable" onClick={() => setOpenId(a.id)}>
                    <td onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" aria-label={`Select ${a.title}`} checked={selected.has(a.id)} onChange={() => toggle(a.id)} />
                    </td>
                    <td>
                      <SeverityBadge severity={a.severity} />
                    </td>
                    <td style={{ maxWidth: 480 }}>
                      <div style={{ fontWeight: 600 }}>
                        {a.title}
                        {a.occurrences > 1 && <span className="muted small"> ×{a.occurrences}</span>}
                        {a.has_snapshot && <ImageIcon size={13} aria-label="Has evidence snapshot" style={{ marginLeft: 6, verticalAlign: -2, color: 'var(--text-3)' }} />}
                      </div>
                      <div className="small muted clamp-2">{a.reason}</div>
                    </td>
                    <td className="small">
                      {a.camera_name ? (
                        <span>
                          <CameraIcon size={12} aria-hidden="true" style={{ verticalAlign: -1 }} /> {a.camera_name}
                        </span>
                      ) : (
                        a.location_name ?? '—'
                      )}
                      {a.zone_name && <div className="muted">Zone: {a.zone_name}</div>}
                    </td>
                    <td className="small nowrap">{formatDateTime(a.last_seen_at, timezone)}</td>
                    <td>
                      <AlertStatusBadge status={a.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > PAGE_SIZE && (
          <div className="pagination">
            <span>
              {data.total} alert{data.total === 1 ? '' : 's'}
            </span>
            <div className="control-row">
              <button type="button" className="btn btn-sm" onClick={() => setPage((p) => p - 1)} disabled={page <= 1} aria-label="Previous page">
                <ChevronLeft size={14} />
              </button>
              <span>
                Page {page} of {pages}
              </span>
              <button type="button" className="btn btn-sm" onClick={() => setPage((p) => p + 1)} disabled={page >= pages} aria-label="Next page">
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </section>

      {openId && <AlertDrawer alertId={openId} timezone={timezone} onClose={() => setOpenId(null)} onChanged={load} />}
    </>
  );
}
