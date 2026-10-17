'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { BellRing, CheckCheck, Eye, Send, Shield, ShieldAlert, ShieldCheck, Siren, UserCog, Users } from 'lucide-react';
import { api } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import type { Guard, GuardCatalogue, GuardIncident, GuardRoom, GuardState, HeadGuardConfig, Recommendation } from '@/lib/types';
import { useSession } from '@/components/SessionProvider';
import { useSystem } from '@/components/SystemProvider';
import { SeverityBadge } from '@/components/AlertBadges';
import { Dialog } from '@/components/Dialog';
import { alertSnapshotUrl } from '@/components/AlertDrawer';

const REFRESH_MS = 10_000;

const STATE: Record<GuardState, [string, string]> = {
  on_duty: ['On duty', 'badge-ok'],
  reporting_in: ['Reporting in', 'badge-info'],
  off_duty: ['Off duty', 'badge-warn'],
  unreachable: ['Cannot see', 'badge-err'],
  disabled: ['Disabled', ''],
};

const PRIORITY: Record<Recommendation['priority'], string> = {
  urgent: 'badge-err',
  high: 'badge-warn',
  medium: 'badge-info',
  low: '',
};

export default function GuardRoomView() {
  const { isAdmin } = useSession();
  const { timezone, alertVersion } = useSystem();
  const [room, setRoom] = useState<GuardRoom | null>(null);
  const [catalogue, setCatalogue] = useState<GuardCatalogue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<Guard | null>(null);
  const [focus, setFocus] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRoom(await api<GuardRoom>('/guard-room'));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(t);
  }, [load, alertVersion]);

  useEffect(() => {
    api<GuardCatalogue>('/guards/catalogue').then(setCatalogue).catch(() => undefined);
    setFocus(new URLSearchParams(window.location.search).get('incident'));
  }, []);

  useEffect(() => {
    if (focus && room) document.getElementById(`incident-${focus}`)?.scrollIntoView({ block: 'center' });
  }, [focus, room]);

  const dutyLabel = useMemo(() => Object.fromEntries((catalogue?.duties ?? []).map((d) => [d.key, d.label])), [catalogue]);

  const act = async (incident: GuardIncident, action: 'acknowledge' | 'resolve') => {
    const note = action === 'resolve' ? window.prompt('What happened? (optional note for the log)') : null;
    if (action === 'resolve' && note === null) return;
    try {
      await api(`/guard-incidents/${incident.id}`, { method: 'POST', body: { action, note: note || null } });
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const briefing = async () => {
    try {
      const r = await api<{ queued: number }>('/head-guard/briefing', { method: 'POST' });
      setNotice(`Briefing queued to ${r.queued} channel(s).`);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  if (!room) return error ? <div className="banner banner-err">{error}</div> : <p className="muted">Calling the guards…</p>;

  const active = room.guards.filter((g) => g.state !== 'disabled');
  const onDuty = active.filter((g) => g.state === 'on_duty').length;
  const openIncidents = room.incidents.filter((i) => i.status !== 'resolved');
  const reportsToday = room.guards.reduce((n, g) => n + g.reports_today, 0);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Guard Room</h1>
          <p>{room.summary} Every camera is a guard at its post; the head guard groups their reports and tells the owner.</p>
        </div>
        {isAdmin && (
          <button type="button" className="btn" onClick={briefing}>
            <Send size={14} /> Send briefing now
          </button>
        )}
      </div>
      {error && <div className="banner banner-err" role="alert" style={{ marginBottom: 12 }}>{error}</div>}
      {notice && <div className="banner banner-info" role="status" style={{ marginBottom: 12 }}>{notice}</div>}

      <div className="metrics">
        <div className="metric">
          <div className="metric-label"><ShieldCheck size={14} /> Guards on duty</div>
          <div className="metric-value">{onDuty}<span className="metric-unit"> / {active.length}</span></div>
          <div className="metric-foot">up to {room.capacity.max_cameras_per_server} cameras per server</div>
        </div>
        <div className="metric">
          <div className="metric-label"><Siren size={14} /> Open incidents</div>
          <div className="metric-value">{openIncidents.length}</div>
          <div className="metric-foot">{openIncidents.filter((i) => i.status === 'open').length} not yet acknowledged</div>
        </div>
        <div className="metric">
          <div className="metric-label"><BellRing size={14} /> Reports today</div>
          <div className="metric-value">{reportsToday}</div>
          <div className="metric-foot">from all guards</div>
        </div>
        <div className="metric">
          <div className="metric-label"><Eye size={14} /> Detection</div>
          <div className="metric-text">
            {room.capacity.person_detector ? 'People detection on' : 'People detection off'}
            <br />
            {room.capacity.video_model_enabled ? 'Fight model on' : 'Fight model off'}
          </div>
        </div>
      </div>

      <div className="overview-grid">
        <section className="panel" aria-labelledby="inc-title">
          <div className="panel-head">
            <h2 id="inc-title">Incidents <span className="sub">· open and last 24 hours</span></h2>
          </div>
          {room.incidents.length === 0 ? (
            <div className="empty">All quiet. Nothing has been reported.</div>
          ) : (
            <ul className="incident-list">
              {room.incidents.map((inc) => (
                <IncidentCard key={inc.id} incident={inc} timezone={timezone} focused={focus === inc.id} onAct={act} />
              ))}
            </ul>
          )}
        </section>

        <div style={{ display: 'grid', gap: 16, alignContent: 'start' }}>
          <section className="panel" aria-labelledby="next-title">
            <div className="panel-head">
              <h2 id="next-title"><ShieldAlert size={15} /> Head guard · what to do next</h2>
            </div>
            {room.recommendations.length === 0 ? (
              <div className="empty">Nothing to do. Every post is covered.</div>
            ) : (
              <ul className="camera-list">
                {room.recommendations.map((r, i) => (
                  <li key={i}>
                    <span className={`badge ${PRIORITY[r.priority]}`}>{r.priority}</span>
                    <Link href={r.link} className="small" style={{ flex: 1 }}>{r.text}</Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {isAdmin && <HeadGuardSettings config={room.head_guard} onSaved={load} />}
        </div>
      </div>

      <section className="panel" aria-labelledby="guards-title">
        <div className="panel-head">
          <h2 id="guards-title"><Users size={15} /> Guards <span className="sub">· one per camera</span></h2>
        </div>
        {room.guards.length === 0 ? (
          <div className="empty">
            No guards yet. <Link href="/settings#cameras">Add cameras</Link> and each one becomes a guard.
          </div>
        ) : (
          <ul className="guard-grid">
            {room.guards.map((g) => (
              <li key={g.camera_id} className="guard-card">
                <div className="guard-card-head">
                  <Shield size={16} aria-hidden="true" />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="guard-name">{g.guard_name}</div>
                    <div className="small muted">{g.camera_name}{g.position ? ` · ${g.position}` : ''}</div>
                  </div>
                  <span className={`badge ${STATE[g.state][1]}`}><span className="dot" />{STATE[g.state][0]}</span>
                </div>
                <div className="small"><strong>Post:</strong> {g.post_label}</div>
                <div className="chip-row">
                  {g.duties.map((d) => (
                    <span key={d} className="badge">{dutyLabel[d] ?? d}</span>
                  ))}
                </div>
                <div className="small muted">
                  {g.state === 'on_duty' && `${g.tracked_people} people in view · `}
                  {g.reports_today} report(s) today
                  {g.last_report && <> · last: {g.last_report.title} ({formatDateTime(g.last_report.at, timezone)})</>}
                </div>
                {g.state === 'unreachable' && g.status_message && <div className="small" style={{ color: 'var(--err)' }}>{g.status_message}</div>}
                {isAdmin && (
                  <div>
                    <button type="button" className="btn btn-sm" onClick={() => setEditing(g)}>
                      <UserCog size={13} /> Assign post & duties
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {editing && catalogue && (
        <GuardDialog guard={editing} catalogue={catalogue} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />
      )}
    </>
  );
}

function IncidentCard({ incident, timezone, focused, onAct }: { incident: GuardIncident; timezone: string; focused: boolean; onAct: (i: GuardIncident, a: 'acknowledge' | 'resolve') => void }) {
  const [open, setOpen] = useState(focused || incident.status === 'open');
  return (
    <li id={`incident-${incident.id}`} className={`incident-card${focused ? ' focused' : ''}${incident.status === 'resolved' ? ' resolved' : ''}`}>
      <div className="incident-head">
        <SeverityBadge severity={incident.severity} />
        <button type="button" className="incident-title" onClick={() => setOpen(!open)} aria-expanded={open}>
          {incident.title}
        </button>
        <span className="badge">{incident.status}</span>
      </div>
      <div className="small muted">
        {incident.guards.map((g) => g.guard_name).join(', ') || 'Head guard'} · {incident.report_count} report(s) ·{' '}
        {formatDateTime(incident.last_seen_at, timezone)}
        {incident.location_name && ` · ${incident.location_name}`}
        {incident.escalated_at && ' · owner notified'}
      </div>
      {open && (
        <div className="incident-body">
          {incident.snapshot_alert_id && (
            <img className="incident-snap" src={alertSnapshotUrl(incident.snapshot_alert_id)} alt={`Evidence for ${incident.title}`} />
          )}
          <div style={{ minWidth: 0 }}>
            <p className="section-title">What the guards saw</p>
            <p className="small" style={{ whiteSpace: 'pre-line' }}>{incident.summary}</p>
            {incident.actions.length > 0 && (
              <>
                <p className="section-title" style={{ marginTop: 10 }}>What to do next</p>
                <ol className="steps">
                  {incident.actions.map((a, i) => <li key={i}>{a}</li>)}
                </ol>
              </>
            )}
            {incident.resolution_note && <p className="small muted" style={{ marginTop: 8 }}>Note: {incident.resolution_note}</p>}
            <div className="form-actions">
              {incident.status === 'open' && (
                <button type="button" className="btn btn-sm" onClick={() => onAct(incident, 'acknowledge')}>
                  <Eye size={13} /> I am checking
                </button>
              )}
              {incident.status !== 'resolved' && (
                <button type="button" className="btn btn-sm btn-primary" onClick={() => onAct(incident, 'resolve')}>
                  <CheckCheck size={13} /> Resolved
                </button>
              )}
              {incident.alert_ids[0] && <Link className="btn btn-sm btn-ghost" href={`/alerts?id=${incident.alert_ids[incident.alert_ids.length - 1]}`}>Open report</Link>}
            </div>
          </div>
        </div>
      )}
    </li>
  );
}

function GuardDialog({ guard, catalogue, onClose, onSaved }: { guard: Guard; catalogue: GuardCatalogue; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(guard.custom_name);
  const [post, setPost] = useState(guard.post);
  const [duties, setDuties] = useState<Set<string>>(new Set(guard.duties));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const choosePost = (key: string) => {
    setPost(key);
    setDuties(new Set(catalogue.posts.find((p) => p.key === key)?.duties ?? []));
  };
  const toggle = (key: string) => {
    const next = new Set(duties);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setDuties(next);
  };
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api(`/guards/${encodeURIComponent(guard.camera_id)}`, { method: 'PUT', body: { guard_name: name, post, duties: [...duties] } });
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      title={`Guard at ${guard.camera_name}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={save} disabled={busy || duties.size === 0}>Save</button>
        </>
      }
    >
      <div className="field">
        <label htmlFor="g-name">Guard name</label>
        <input id="g-name" className="input" maxLength={60} value={name} placeholder={`Guard at ${guard.camera_name}`} onChange={(e) => setName(e.target.value)} />
        <span className="field-hint">Shown in incident reports, e.g. &quot;Gate guard&quot; or &quot;2nd floor corridor&quot;.</span>
      </div>
      <div className="field">
        <label htmlFor="g-post">Post</label>
        <select id="g-post" className="select" value={post} onChange={(e) => choosePost(e.target.value)}>
          {catalogue.posts.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
        </select>
        <span className="field-hint">{catalogue.posts.find((p) => p.key === post)?.description}</span>
      </div>
      <fieldset className="field" style={{ border: 0, padding: 0 }}>
        <legend style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>Duties</legend>
        {catalogue.duties.map((d) => (
          <label key={d.key} className="small" style={{ display: 'block', marginBottom: 6 }}>
            <input type="checkbox" checked={duties.has(d.key)} onChange={() => toggle(d.key)} /> <strong>{d.label}</strong>
            <span className="muted"> · {d.description}</span>
          </label>
        ))}
      </fieldset>
      {error && <div className="banner banner-err" role="alert">{error}</div>}
    </Dialog>
  );
}

function HeadGuardSettings({ config, onSaved }: { config: HeadGuardConfig; onSaved: () => void }) {
  const [form, setForm] = useState(config);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => setForm(config), [config]);

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const { last_briefing: _ignored, ...body } = form;
      await api('/head-guard/config', { method: 'PUT', body });
      setMsg('Saved.');
      onSaved();
    } catch (err) {
      setMsg((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel" aria-labelledby="hg-title">
      <div className="panel-head">
        <h2 id="hg-title">Head guard settings</h2>
      </div>
      <div className="panel-body" style={{ display: 'grid', gap: 10 }}>
        <label className="small">
          <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> Head guard decides what reaches the owner
          <span className="muted"> (one message per incident instead of one per alert)</span>
        </label>
        <label className="small">
          <input type="checkbox" checked={form.corroboration_boost} onChange={(e) => setForm({ ...form, corroboration_boost: e.target.checked })} /> Raise severity when two guards report the same thing
        </label>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="hg-win">Group reports within (minutes)</label>
            <input id="hg-win" className="input" type="number" min={1} max={120} value={form.correlation_minutes} onChange={(e) => setForm({ ...form, correlation_minutes: Number(e.target.value) })} />
          </div>
          <div className="field">
            <label htmlFor="hg-auto">Auto-close quiet incidents after (minutes)</label>
            <input id="hg-auto" className="input" type="number" min={10} max={10080} value={form.auto_resolve_minutes} onChange={(e) => setForm({ ...form, auto_resolve_minutes: Number(e.target.value) })} />
          </div>
        </div>
        <label className="small">
          <input type="checkbox" checked={form.briefing_enabled} onChange={(e) => setForm({ ...form, briefing_enabled: e.target.checked })} /> Send a daily briefing to the owner at
          <select className="select select-sm" style={{ marginLeft: 6 }} value={form.briefing_hour} onChange={(e) => setForm({ ...form, briefing_hour: Number(e.target.value) })} aria-label="Briefing hour">
            {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>)}
          </select>
        </label>
        <div className="form-actions" style={{ marginTop: 0 }}>
          <button type="button" className="btn btn-primary btn-sm" onClick={save} disabled={busy}>Save</button>
          {msg && <span className="small muted">{msg}</span>}
        </div>
      </div>
    </section>
  );
}
