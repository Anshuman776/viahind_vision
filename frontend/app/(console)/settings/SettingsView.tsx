'use client';

import { useCallback, useEffect, useState } from 'react';
import { CircleAlert, CircleCheck, Plus, TriangleAlert } from 'lucide-react';
import { api } from '@/lib/api';
import { formatDateTime, SOURCE_LABELS } from '@/lib/format';
import type { Camera, SiteSettings, SourceType, User } from '@/lib/types';
import { useSession } from '@/components/SessionProvider';
import { useSystem } from '@/components/SystemProvider';
import { CameraStatusBadge } from '@/components/Status';
import { Dialog } from '@/components/Dialog';
import { AlertRulesSection, AnomalyModelSection, EvidenceSection, LocationsSection, NotificationsSection, SchedulesSection, VideoAnomalySection } from './BusinessSettings';

const SECTIONS: [string, string, 'all' | 'admin'][] = [
  ['site', 'Business', 'all'],
  ['locations', 'Locations', 'all'],
  ['cameras', 'Cameras', 'all'],
  ['detection', 'Detection & tracking', 'all'],
  ['evidence', 'Event evidence', 'admin'],
  ['retention', 'Data retention', 'all'],
  ['alert-rules', 'Alert rules', 'admin'],
  ['notifications', 'Notifications', 'admin'],
  ['schedules', 'Scheduled reports', 'admin'],
  ['anomaly-model', 'Unusual patterns (ML)', 'admin'],
  ['video-anomaly', 'Video anomaly detection', 'admin'],
  ['operators', 'User accounts', 'admin'],
  ['integrations', 'System status', 'admin'],
];

const TIMEZONES = ['Asia/Kolkata', 'Asia/Dubai', 'Asia/Singapore', 'Europe/London', 'UTC', 'America/New_York'];

export default function SettingsView() {
  const { isAdmin } = useSession();
  const { settings, refreshSettings } = useSystem();

  if (!settings) return <p className="muted">Loading settings…</p>;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>{isAdmin ? 'Changes are validated by the server and recorded in the audit log.' : 'Read-only: only administrators can change settings.'}</p>
        </div>
      </div>
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Settings sections">
          {SECTIONS.filter(([, , who]) => who === 'all' || isAdmin).map(([id, label]) => (
            <a key={id} href={`#${id}`}>
              {label}
            </a>
          ))}
        </nav>
        <div className="settings-sections">
          <SiteSection site={settings.site} editable={isAdmin} onSaved={refreshSettings} />
          <LocationsSection editable={isAdmin} />
          <CamerasSection editable={isAdmin} fileSourcesAllowed={settings.system.file_sources_allowed ?? false} testVideoDir={settings.system.test_video_dir ?? 'test_videos'} />
          <DetectionSection site={settings.site} editable={isAdmin} onSaved={refreshSettings} />
          {isAdmin && <EvidenceSection site={settings.site} editable={isAdmin} usedMb={settings.system.storage?.evidence_used_mb} onSaved={refreshSettings} />}
          <RetentionSection site={settings.site} editable={isAdmin} onSaved={refreshSettings} />
          {isAdmin && (
            <>
              <AlertRulesSection />
              <NotificationsSection emailConfigured={settings.system.email_configured ?? false} />
              <SchedulesSection />
              <AnomalyModelSection />
              <VideoAnomalySection />
              <OperatorsSection />
              <IntegrationsSection />
            </>
          )}
        </div>
      </div>
    </>
  );
}

function useSettingsForm(site: SiteSettings, onSaved: () => Promise<void>) {
  const [form, setForm] = useState<SiteSettings>(site);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => setForm(site), [site]);
  const save = async (fields: (keyof SiteSettings)[]) => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const body = Object.fromEntries(fields.map((f) => [f, form[f]]));
      await api('/settings', { method: 'PUT', body });
      await onSaved();
      setSaved(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return { form, setForm, error, saved, busy, save };
}

function Section({ id, title, description, children }: { id: string; title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="panel" id={id} aria-labelledby={`${id}-title`} style={{ scrollMarginTop: 76 }}>
      <div className="panel-head">
        <h2 id={`${id}-title`}>
          {title} {description && <span className="sub">· {description}</span>}
        </h2>
      </div>
      <div className="panel-body">{children}</div>
    </section>
  );
}

function SaveRow({ busy, saved, error, onSave, editable }: { busy: boolean; saved: boolean; error: string | null; onSave: () => void; editable: boolean }) {
  if (!editable) return null;
  return (
    <div className="form-actions">
      <button type="button" className="btn btn-primary" onClick={onSave} disabled={busy}>
        Save
      </button>
      {saved && !error && (
        <span className="small" style={{ color: 'var(--ok)' }} role="status">
          Saved
        </span>
      )}
      {error && (
        <span className="small" style={{ color: 'var(--err)' }} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

function NumberField({
  id,
  label,
  hint,
  value,
  onChange,
  step = 1,
  min,
  max,
  disabled,
}: {
  id: string;
  label: string;
  hint?: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
  min?: number;
  max?: number;
  disabled: boolean;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} className="input" type="number" step={step} min={min} max={max} value={value} disabled={disabled} onChange={(e) => onChange(Number(e.target.value))} />
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  );
}

function SiteSection({ site, editable, onSaved }: { site: SiteSettings; editable: boolean; onSaved: () => Promise<void> }) {
  const f = useSettingsForm(site, onSaved);
  const zones = TIMEZONES.includes(f.form.timezone) ? TIMEZONES : [f.form.timezone, ...TIMEZONES];
  return (
    <Section id="site" title="Business">
      <div className="form-grid">
        <div className="field">
          <label htmlFor="site-name">Business name</label>
          <input id="site-name" className="input" value={f.form.site_name} disabled={!editable} maxLength={120} onChange={(e) => f.setForm({ ...f.form, site_name: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="site-tz">Site timezone</label>
          <select id="site-tz" className="select" value={f.form.timezone} disabled={!editable} onChange={(e) => f.setForm({ ...f.form, timezone: e.target.value })}>
            {zones.map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
          <span className="field-hint">All times, days and hourly figures use this timezone.</span>
        </div>
      </div>
      <SaveRow editable={editable} busy={f.busy} saved={f.saved} error={f.error} onSave={() => f.save(['site_name', 'timezone'])} />
    </Section>
  );
}

function DetectionSection({ site, editable, onSaved }: { site: SiteSettings; editable: boolean; onSaved: () => Promise<void> }) {
  const f = useSettingsForm(site, onSaved);
  const set = (k: keyof SiteSettings) => (v: number) => f.setForm({ ...f.form, [k]: v });
  return (
    <Section id="detection" title="Detection & tracking" description="applies to all cameras immediately">
      <div className="form-grid">
        <NumberField id="d-conf" label="Minimum detection confidence" hint="0.10 – 0.95. Higher ignores more uncertain detections." value={f.form.min_confidence} step={0.05} min={0.1} max={0.95} onChange={set('min_confidence')} disabled={!editable} />
        <NumberField id="d-cool" label="Cooldown (seconds)" hint="A direction reversal within this time is marked Uncertain." value={f.form.cooldown_seconds} step={0.5} min={0} max={60} onChange={set('cooldown_seconds')} disabled={!editable} />
        <NumberField id="d-timeout" label="Track timeout (seconds)" hint="A person not seen for this long is forgotten." value={f.form.track_timeout_seconds} step={0.5} min={0.5} max={60} onChange={set('track_timeout_seconds')} disabled={!editable} />
        <NumberField id="d-hits" label="Minimum track length (frames)" hint="Tracks shorter than this never create events." value={f.form.min_track_hits} min={1} max={60} onChange={set('min_track_hits')} disabled={!editable} />
        <NumberField id="d-side" label="Frames needed on the new side" hint="Confirms a crossing before it is recorded." value={f.form.min_side_frames} min={1} max={30} onChange={set('min_side_frames')} disabled={!editable} />
        <NumberField id="d-band" label="Line tolerance band" hint="Fraction of the frame around the line where no decision is made (0 – 0.2)." value={f.form.line_band} step={0.01} min={0} max={0.2} onChange={set('line_band')} disabled={!editable} />
        <div className="field">
          <label htmlFor="d-anchor">Position used for crossing</label>
          <select id="d-anchor" className="select" value={f.form.anchor_point} disabled={!editable} onChange={(e) => f.setForm({ ...f.form, anchor_point: e.target.value as 'bottom' | 'center' })}>
            <option value="bottom">Feet (angled cameras)</option>
            <option value="center">Body centre (overhead cameras)</option>
          </select>
        </div>
      </div>
      <SaveRow
        editable={editable}
        busy={f.busy}
        saved={f.saved}
        error={f.error}
        onSave={() => f.save(['min_confidence', 'cooldown_seconds', 'track_timeout_seconds', 'min_track_hits', 'min_side_frames', 'line_band', 'anchor_point'])}
      />
    </Section>
  );
}

function RetentionSection({ site, editable, onSaved }: { site: SiteSettings; editable: boolean; onSaved: () => Promise<void> }) {
  const f = useSettingsForm(site, onSaved);
  const [runResult, setRunResult] = useState<string | null>(null);
  const runNow = async () => {
    try {
      const r = await api<{ purged_snapshots: number; deleted_events: number }>('/settings/retention/run', { method: 'POST' });
      setRunResult(`Removed ${r.purged_snapshots} snapshot(s) and ${r.deleted_events} event record(s).`);
    } catch (err) {
      setRunResult((err as Error).message);
    }
  };
  return (
    <Section id="retention" title="Data retention" description="runs hourly">
      <div className="form-grid">
        <NumberField id="r-snap" label="Keep snapshots for (days)" value={f.form.snapshot_retention_days} min={1} max={3650} onChange={(v) => f.setForm({ ...f.form, snapshot_retention_days: v })} disabled={!editable} />
        <NumberField id="r-events" label="Keep event records for (days)" hint="0 keeps records until deleted manually." value={f.form.event_retention_days} min={0} max={3650} onChange={(v) => f.setForm({ ...f.form, event_retention_days: v })} disabled={!editable} />
      </div>
      <SaveRow editable={editable} busy={f.busy} saved={f.saved} error={f.error} onSave={() => f.save(['snapshot_retention_days', 'event_retention_days'])} />
      {editable && (
        <div className="form-actions">
          <button type="button" className="btn btn-sm" onClick={runNow}>
            Apply retention now
          </button>
          {runResult && <span className="small muted">{runResult}</span>}
        </div>
      )}
    </Section>
  );
}

interface CameraForm {
  id: string;
  name: string;
  location: string;
  source_type: SourceType;
  source: string;
  enabled: boolean;
  detection_enabled: boolean;
  counting_enabled: boolean;
  location_id: string;
}

const EMPTY_CAMERA: CameraForm = { id: '', name: '', location: '', source_type: 'browser', source: '', enabled: true, detection_enabled: true, counting_enabled: true, location_id: '' };

interface TestResult {
  ok: boolean;
  message: string;
  steps: { step: string; ok: boolean; message: string }[];
}

function CamerasSection({ editable, fileSourcesAllowed, testVideoDir }: { editable: boolean; fileSourcesAllowed: boolean; testVideoDir: string }) {
  const { cameras, refreshCameras, locations, refreshLocations } = useSystem();
  const [test, setTest] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [editing, setEditing] = useState<Camera | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<CameraForm>(EMPTY_CAMERA);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const openNew = () => {
    setEditing(null);
    setForm({ ...EMPTY_CAMERA, location_id: locations[0] ? String(locations[0].id) : '' });
    setError(null);
    setTest(null);
    setOpen(true);
  };
  const openEdit = (c: Camera) => {
    setEditing(c);
    setForm({ id: c.id, name: c.name, location: c.location, source_type: c.source_type, source: '', enabled: c.enabled, detection_enabled: c.detection_enabled, counting_enabled: c.counting_enabled, location_id: String(c.location_id) });
    setError(null);
    setTest(null);
    setOpen(true);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (editing) {
        const body: Record<string, unknown> = {
          name: form.name, location: form.location, enabled: form.enabled, detection_enabled: form.detection_enabled,
          counting_enabled: form.counting_enabled, location_id: form.location_id ? Number(form.location_id) : undefined,
        };
        if (form.source_type !== editing.source_type) body.source_type = form.source_type;
        if (form.source.trim()) body.source = form.source.trim();
        await api(`/cameras/${encodeURIComponent(editing.id)}`, { method: 'PATCH', body });
      } else {
        await api('/cameras', { method: 'POST', body: { ...form, source: form.source.trim() || null, location_id: form.location_id ? Number(form.location_id) : null } });
      }
      await refreshCameras();
      await refreshLocations();
      setOpen(false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      if (form.source.trim() && form.source_type !== 'browser') {
        setTest(await api<TestResult>('/cameras/test-source', { method: 'POST', body: { source_type: form.source_type, source: form.source.trim() } }));
      } else if (editing) {
        setTest(await api<TestResult>(`/cameras/${encodeURIComponent(editing.id)}/test`, { method: 'POST' }));
      }
    } catch (err) {
      setTest({ ok: false, message: (err as Error).message, steps: [] });
    } finally {
      setTesting(false);
    }
  };

  const remove = async () => {
    if (!editing || !window.confirm(`Delete camera "${editing.name}"? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await api(`/cameras/${encodeURIComponent(editing.id)}`, { method: 'DELETE' });
      await refreshCameras();
      setOpen(false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const sourceHint: Record<SourceType, string> = {
    browser: 'Frames come from a signed-in browser (laptop webcam or phone) when an operator presses Start Camera.',
    device: 'Index of a USB camera attached to the server running the backend (usually 0).',
    network: 'rtsp://user:password@192.168.1.20:554/stream1, an HTTP MJPEG URL, or env:CAMERA_GATE_URL to keep credentials in the server environment.',
    file: `File name of a clip in the server's ${testVideoDir}/ folder. For testing only.`,
  };

  return (
    <Section id="cameras" title="Cameras">
      {cameras.length === 0 ? (
        <div className="empty" style={{ padding: 16 }}>
          <strong>No cameras yet</strong>
          {editable ? 'Add the entrance camera to start monitoring.' : 'Ask an administrator to add the entrance camera.'}
        </div>
      ) : (
        <div className="table-wrap" style={{ margin: '-16px -16px 0' }}>
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                {locations.length > 1 && <th>Location</th>}
                <th>Source</th>
                <th>Entrance line</th>
                <th>Status</th>
                {editable && (
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {cameras.map((c) => (
                <tr key={c.id}>
                  <td>
                    <strong>{c.name}</strong>
                    <div className="small muted mono">{c.id}</div>
                  </td>
                  <td>{SOURCE_LABELS[c.source_type]}</td>
                  {locations.length > 1 && <td>{locations.find((l) => l.id === c.location_id)?.name ?? '—'}</td>}
                  <td className="small" style={{ maxWidth: 260 }}>
                    {c.source_description ?? '—'}
                    {c.last_error && c.runtime.status !== 'live' && <div className="muted">Last error: {c.last_error}</div>}
                  </td>
                  <td>{!c.counting_enabled ? <span className="badge">Counting off</span> : c.line ? 'Configured' : <span className="badge badge-warn">Not set</span>}</td>
                  <td>{c.enabled ? <CameraStatusBadge status={c.runtime.status} /> : <span className="badge">Disabled</span>}</td>
                  {editable && (
                    <td style={{ textAlign: 'right' }}>
                      <button type="button" className="btn btn-sm" onClick={() => openEdit(c)}>
                        Edit
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editable && (
        <div className="form-actions">
          <button type="button" className="btn" onClick={openNew}>
            <Plus size={14} /> Add camera
          </button>
        </div>
      )}

      <Dialog
        open={open}
        title={editing ? `Edit ${editing.name}` : 'Add camera'}
        onClose={() => setOpen(false)}
        footer={
          <>
            {editing && (
              <button type="button" className="btn btn-danger" onClick={remove} disabled={busy} style={{ marginRight: 'auto' }}>
                Delete
              </button>
            )}
            <button type="button" className="btn" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button type="button" className="btn btn-primary" onClick={save} disabled={busy || !form.name || (!editing && !form.id)}>
              Save
            </button>
          </>
        }
      >
        {!editing && (
          <div className="field">
            <label htmlFor="c-id">Camera ID</label>
            <input id="c-id" className="input mono" value={form.id} placeholder="CAM-ENTRANCE-01" maxLength={48} onChange={(e) => setForm({ ...form, id: e.target.value.toUpperCase() })} />
          </div>
        )}
        <div className="field">
          <label htmlFor="c-name">Name</label>
          <input id="c-name" className="input" value={form.name} maxLength={120} placeholder="Main entrance" onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="c-site">Location</label>
          <select id="c-site" className="select" value={form.location_id} onChange={(e) => setForm({ ...form, location_id: e.target.value })}>
            {locations.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="c-loc">Position</label>
          <input id="c-loc" className="input" value={form.location} maxLength={160} placeholder="Front door, facing street" onChange={(e) => setForm({ ...form, location: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="c-type">Camera type</label>
          <select id="c-type" className="select" value={form.source_type} onChange={(e) => setForm({ ...form, source_type: e.target.value as SourceType })}>
            <option value="browser">Browser camera (webcam or phone)</option>
            <option value="network">IP / CCTV camera (RTSP or HTTP)</option>
            <option value="device">USB camera on the server</option>
            {fileSourcesAllowed && <option value="file">Test clip (development)</option>}
          </select>
        </div>
        {form.source_type !== 'browser' && (
          <div className="field">
            <label htmlFor="c-src">Source</label>
            <input
              id="c-src"
              className="input mono"
              type={form.source_type === 'network' ? 'password' : 'text'}
              autoComplete="off"
              value={form.source}
              placeholder={editing && editing.source_type === form.source_type ? 'Leave blank to keep the current source' : ''}
              onChange={(e) => setForm({ ...form, source: e.target.value })}
            />
            <span className="field-hint">{sourceHint[form.source_type]}</span>
            {editing && <span className="field-hint">Current: {editing.source_description}. Stored encrypted and never shown in full.</span>}
            <div className="control-row" style={{ marginTop: 4 }}>
              <button type="button" className="btn btn-sm" onClick={runTest} disabled={testing || (!form.source.trim() && !editing)}>
                {testing ? 'Testing…' : 'Test connection'}
              </button>
            </div>
            {test && (
              <div className={`banner ${test.ok ? 'banner-info' : 'banner-err'}`} role="status" style={{ marginBottom: 0 }}>
                <div>
                  <strong>{test.message}</strong>
                  {test.steps.length > 1 && (
                    <ul className="small" style={{ paddingLeft: 16, marginTop: 4 }}>
                      {test.steps.map((st) => (
                        <li key={st.step}>
                          {st.ok ? '✓' : '✗'} {st.message}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
        {form.source_type === 'browser' && <p className="field-hint">{sourceHint.browser}</p>}
        <label className="control-row">
          <input type="checkbox" checked={form.detection_enabled} onChange={(e) => setForm({ ...form, detection_enabled: e.target.checked })} /> Detect people (needed for counting and zones)
        </label>
        <label className="control-row">
          <input type="checkbox" checked={form.counting_enabled} onChange={(e) => setForm({ ...form, counting_enabled: e.target.checked })} /> Count entries and exits at this camera&apos;s line
        </label>
        <p className="field-hint">Use one counting camera per doorway; overlapping cameras on the same door double-count. Turn counting off for zone-only cameras.</p>
        {editing && (
          <label className="control-row">
            <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> Camera enabled
          </label>
        )}
        {error && (
          <div className="banner banner-err" role="alert" style={{ marginBottom: 0 }}>
            {error}
          </div>
        )}
      </Dialog>
    </Section>
  );
}

function OperatorsSection() {
  const { user: me } = useSession();
  const { timezone } = useSystem();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ username: '', password: '', role: 'operator', email: '' });
  const [resetFor, setResetFor] = useState<User | null>(null);
  const [newPassword, setNewPassword] = useState('');

  const load = useCallback(async () => {
    try {
      setUsers(await api<User[]>('/users'));
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const call = async (fn: () => Promise<unknown>, after?: () => void) => {
    setError(null);
    try {
      await fn();
      after?.();
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <Section id="operators" title="User accounts">
      {error && (
        <div className="banner banner-err" role="alert">
          {error}
        </div>
      )}
      <div className="table-wrap" style={{ margin: '0 -16px' }}>
        <table className="table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Role</th>
              <th>Status</th>
              <th>Last sign-in</th>
              <th>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>
                  <strong>{u.username}</strong> {u.id === me.id && <span className="muted small">(you)</span>}
                </td>
                <td>
                  <select
                    className="select"
                    value={u.role}
                    aria-label={`Role for ${u.username}`}
                    onChange={(e) => call(() => api(`/users/${u.id}`, { method: 'PATCH', body: { role: e.target.value } }))}
                  >
                    <option value="viewer">Viewer</option>
                    <option value="operator">Operator</option>
                    <option value="admin">Administrator</option>
                  </select>
                </td>
                <td>{u.is_active ? <span className="badge badge-ok">Active</span> : <span className="badge">Deactivated</span>}</td>
                <td className="small">{u.last_login_at ? formatDateTime(u.last_login_at, timezone) : 'Never'}</td>
                <td style={{ textAlign: 'right' }} className="nowrap">
                  <button type="button" className="btn btn-sm" onClick={() => { setResetFor(u); setNewPassword(''); }}>
                    Reset password
                  </button>{' '}
                  {u.id !== me.id && (
                    <button type="button" className="btn btn-sm" onClick={() => call(() => api(`/users/${u.id}`, { method: 'PATCH', body: { is_active: !u.is_active } }))}>
                      {u.is_active ? 'Deactivate' : 'Reactivate'}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="form-actions">
        <button type="button" className="btn" onClick={() => { setForm({ username: '', password: '', role: 'operator', email: '' }); setOpen(true); }}>
          <Plus size={14} /> Add operator
        </button>
      </div>

      <Dialog
        open={open}
        title="Add operator"
        onClose={() => setOpen(false)}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button type="button" className="btn btn-primary" disabled={!form.username || form.password.length < 10} onClick={() => call(() => api('/users', { method: 'POST', body: { ...form, email: form.email.trim() || null } }), () => setOpen(false))}>
              Create account
            </button>
          </>
        }
      >
        <div className="field">
          <label htmlFor="u-name">Username</label>
          <input id="u-name" className="input" autoComplete="off" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="u-pass">Initial password</label>
          <input id="u-pass" className="input" type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <span className="field-hint">At least 10 characters with upper- and lower-case letters and a digit.</span>
        </div>
        <div className="field">
          <label htmlFor="u-role">Role</label>
          <select id="u-role" className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            <option value="viewer">Viewer: dashboards and reports only (no video or images)</option>
            <option value="operator">Operator: monitor cameras, review events and alerts, reconcile occupancy</option>
            <option value="admin">Administrator: also settings, cameras and accounts</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="u-email">Email (optional)</label>
          <input id="u-email" className="input" type="email" autoComplete="off" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </div>
        {error && <div className="banner banner-err" style={{ marginBottom: 0 }}>{error}</div>}
      </Dialog>

      <Dialog
        open={resetFor !== null}
        title={`Reset password for ${resetFor?.username ?? ''}`}
        onClose={() => setResetFor(null)}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setResetFor(null)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={newPassword.length < 10}
              onClick={() => resetFor && call(() => api(`/users/${resetFor.id}`, { method: 'PATCH', body: { password: newPassword } }), () => setResetFor(null))}
            >
              Set password
            </button>
          </>
        }
      >
        <div className="field">
          <label htmlFor="u-newpass">New password</label>
          <input id="u-newpass" className="input" type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
        </div>
      </Dialog>
    </Section>
  );
}

function IntegrationsSection() {
  const { settings } = useSystem();
  if (!settings) return null;
  const { person_detector: pd, anomaly, storage } = settings.system;
  if (!anomaly || !storage) return null;
  const anomalyOk = anomaly.status === 'ready';
  return (
    <Section id="integrations" title="Integrations">
      <div style={{ display: 'grid', gap: 14 }}>
        <IntegrationRow
          ok={pd.available}
          title="Person detection (YOLO + ByteTrack)"
          status={pd.available ? 'Available' : 'Not configured'}
          text={pd.available ? 'Used by every camera with detection enabled.' : `${pd.message} Set PERSON_MODEL_PATH in backend/.env to a local YOLO checkpoint.`}
        />
        <IntegrationRow
          ok={anomalyOk}
          warn={anomaly.status === 'motion' || anomaly.status === 'disabled' || anomaly.status === 'placeholder'}
          title="Video anomaly detection"
          status={{ disabled: 'Disabled', placeholder: 'No model', ready: 'Classifier active', motion: 'Motion detector active', error: 'Error', not_initialized: 'Not started' }[anomaly.status] ?? anomaly.status}
          text={anomaly.status === 'disabled' ? 'Turn on with ANOMALY_DETECTION_ENABLED=True.' : 'See Video anomaly detection above for details.'}
        />
        <IntegrationRow
          ok={!storage.low}
          title="Snapshot storage"
          status={storage.free_mb !== null ? `${(storage.free_mb / 1024).toFixed(1)} GB free` : 'Unknown'}
          text={storage.low ? `Below the ${storage.min_free_mb} MB minimum: new snapshots are skipped until space is freed.` : 'Event snapshots only; no continuous video is stored.'}
        />
      </div>
    </Section>
  );
}

function IntegrationRow({ ok, warn, title, status, text }: { ok: boolean; warn?: boolean; title: string; status: string; text: string }) {
  const Icon = ok ? CircleCheck : warn ? TriangleAlert : CircleAlert;
  const tone = ok ? 'badge-ok' : warn ? 'badge-warn' : 'badge-err';
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600 }}>{title}</div>
        <div className="small muted">{text}</div>
      </div>
      <span className={`badge ${tone}`}>
        <Icon size={13} aria-hidden="true" /> {status}
      </span>
    </div>
  );
}
