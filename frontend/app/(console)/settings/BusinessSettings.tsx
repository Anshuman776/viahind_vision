'use client';

import { useCallback, useEffect, useState } from 'react';
import { BrainCircuit, Mail, Plus, Send, Trash2 } from 'lucide-react';
import { api } from '@/lib/api';
import { CATEGORY_LABELS, formatDateTime, SEVERITY_LABELS } from '@/lib/format';
import type { AlertRule, BusinessHours, Channel, DayKey, Delivery, Location, MailServer, ModelStatus, ReportSchedule, Severity, SiteSettings } from '@/lib/types';
import { useSystem } from '@/components/SystemProvider';
import { Dialog } from '@/components/Dialog';
import { SeverityBadge } from '@/components/AlertBadges';

const DAYS: [DayKey, string][] = [
  ['mon', 'Mon'],
  ['tue', 'Tue'],
  ['wed', 'Wed'],
  ['thu', 'Thu'],
  ['fri', 'Fri'],
  ['sat', 'Sat'],
  ['sun', 'Sun'],
];
const SEVERITIES: Severity[] = ['info', 'low', 'medium', 'high', 'critical'];

export function Section({ id, title, description, children }: { id: string; title: string; description?: string; children: React.ReactNode }) {
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

function ErrorBanner({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="banner banner-err" role="alert" style={{ marginBottom: 12 }}>
      {error}
    </div>
  );
}

function useAsync() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (fn: () => Promise<unknown>, after?: () => void) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      after?.();
      return true;
    } catch (err) {
      setError((err as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, setError, run };
}

// -- Locations and business hours ---------------------------------------------------------------

interface LocationForm {
  name: string;
  address: string;
  capacity: string;
  hoursEnabled: boolean;
  hours: Record<DayKey, { open: boolean; from: string; to: string }>;
  is_active: boolean;
}

function toForm(l: Location | null): LocationForm {
  const hours = {} as LocationForm['hours'];
  for (const [d] of DAYS) {
    const r = l?.business_hours?.[d]?.[0];
    hours[d] = { open: !!r, from: r?.[0] ?? '09:00', to: r?.[1] ?? '21:00' };
  }
  return {
    name: l?.name ?? '',
    address: l?.address ?? '',
    capacity: l?.capacity ? String(l.capacity) : '',
    hoursEnabled: !!l?.business_hours,
    hours,
    is_active: l?.is_active ?? true,
  };
}

export function hoursFromForm(form: LocationForm): BusinessHours {
  const out: BusinessHours = {};
  for (const [d] of DAYS) if (form.hours[d].open) out[d] = [[form.hours[d].from, form.hours[d].to]];
  return out;
}

export function LocationsSection({ editable }: { editable: boolean }) {
  const { locations, refreshLocations } = useSystem();
  const [editing, setEditing] = useState<Location | null>(null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<LocationForm>(toForm(null));
  const { busy, error, setError, run } = useAsync();

  const start = (l: Location | null) => {
    setEditing(l);
    setForm(toForm(l));
    setError(null);
    setOpen(true);
  };

  const save = () => {
    const capacity = form.capacity.trim() ? Number(form.capacity) : null;
    const body: Record<string, unknown> = { name: form.name, address: form.address, is_active: form.is_active };
    if (editing) {
      if (capacity === null) body.clear_capacity = true;
      else body.capacity = capacity;
      if (form.hoursEnabled) body.business_hours = hoursFromForm(form);
      else body.clear_business_hours = true;
    } else {
      body.capacity = capacity;
      body.business_hours = form.hoursEnabled ? hoursFromForm(form) : null;
    }
    run(
      () => (editing ? api(`/locations/${editing.id}`, { method: 'PATCH', body }) : api('/locations', { method: 'POST', body })),
      () => {
        refreshLocations();
        setOpen(false);
      },
    );
  };

  const setDay = (d: DayKey, patch: Partial<LocationForm['hours'][DayKey]>) => setForm({ ...form, hours: { ...form.hours, [d]: { ...form.hours[d], ...patch } } });

  return (
    <Section id="locations" title="Locations" description="premises, capacity and business hours">
      <p className="small muted" style={{ marginBottom: 12 }}>
        Each camera belongs to a location. Occupancy, reports and alerts are kept per location. Business hours drive the
        after-hours alert; capacity drives the occupancy alert.
      </p>
      <div className="table-wrap" style={{ margin: '0 -16px' }}>
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th className="num">Cameras</th>
              <th className="num">Capacity</th>
              <th>Business hours</th>
              <th>Status</th>
              {editable && <th><span className="sr-only">Actions</span></th>}
            </tr>
          </thead>
          <tbody>
            {locations.map((l) => (
              <tr key={l.id}>
                <td>
                  <strong>{l.name}</strong>
                  {l.address && <div className="small muted">{l.address}</div>}
                </td>
                <td className="num">{l.camera_count}</td>
                <td className="num">{l.capacity ?? '—'}</td>
                <td className="small">
                  {l.business_hours
                    ? DAYS.filter(([d]) => l.business_hours?.[d]?.length).map(([d, label]) => `${label} ${l.business_hours![d]![0][0]}–${l.business_hours![d]![0][1]}`).join(', ') || 'Closed all week'
                    : 'Not configured'}
                </td>
                <td>{l.is_active ? <span className="badge badge-ok">Active</span> : <span className="badge">Inactive</span>}</td>
                {editable && (
                  <td style={{ textAlign: 'right' }}>
                    <button type="button" className="btn btn-sm" onClick={() => start(l)}>
                      Edit
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editable && (
        <div className="form-actions">
          <button type="button" className="btn" onClick={() => start(null)}>
            <Plus size={14} /> Add location
          </button>
        </div>
      )}
      <Dialog
        open={open}
        title={editing ? `Edit ${editing.name}` : 'Add location'}
        onClose={() => setOpen(false)}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button type="button" className="btn btn-primary" onClick={save} disabled={busy || !form.name.trim()}>
              Save
            </button>
          </>
        }
      >
        <div className="field">
          <label htmlFor="l-name">Name</label>
          <input id="l-name" className="input" maxLength={120} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="l-addr">Address</label>
          <input id="l-addr" className="input" maxLength={255} value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="l-cap">Capacity (people)</label>
          <input id="l-cap" className="input" type="number" min={1} max={100000} value={form.capacity} placeholder="Not set" onChange={(e) => setForm({ ...form, capacity: e.target.value })} />
        </div>
        <label className="small">
          <input type="checkbox" checked={form.hoursEnabled} onChange={(e) => setForm({ ...form, hoursEnabled: e.target.checked })} /> Set business hours
        </label>
        {form.hoursEnabled && (
          <div className="hours-grid">
            {DAYS.map(([d, label]) => (
              <div key={d} style={{ display: 'contents' }}>
                <label htmlFor={`h-${d}`}>
                  <input id={`h-${d}`} type="checkbox" checked={form.hours[d].open} onChange={(e) => setDay(d, { open: e.target.checked })} /> {label}
                </label>
                <input className="input" type="time" aria-label={`${label} opens`} value={form.hours[d].from} disabled={!form.hours[d].open} onChange={(e) => setDay(d, { from: e.target.value })} />
                <input className="input" type="time" aria-label={`${label} closes`} value={form.hours[d].to} disabled={!form.hours[d].open} onChange={(e) => setDay(d, { to: e.target.value })} />
                <span className="small muted">{form.hours[d].open ? '' : 'Closed'}</span>
              </div>
            ))}
          </div>
        )}
        {editing && (
          <label className="small">
            <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Active
          </label>
        )}
        <ErrorBanner error={error} />
      </Dialog>
    </Section>
  );
}

// -- Evidence settings ------------------------------------------------------------------------------

export function EvidenceSection({ site, editable, usedMb, onSaved }: { site: SiteSettings; editable: boolean; usedMb?: number; onSaved: () => Promise<void> }) {
  const [form, setForm] = useState({
    snapshot_jpeg_quality: site.snapshot_jpeg_quality,
    snapshot_max_width: site.snapshot_max_width,
    snapshot_storage_limit_mb: site.snapshot_storage_limit_mb,
    alert_retention_days: site.alert_retention_days,
  });
  const [saved, setSaved] = useState(false);
  const { busy, error, run } = useAsync();
  const field = (key: keyof typeof form, label: string, hint: string, min: number, max: number) => (
    <div className="field">
      <label htmlFor={`ev-${key}`}>{label}</label>
      <input id={`ev-${key}`} className="input" type="number" min={min} max={max} value={form[key]} disabled={!editable} onChange={(e) => setForm({ ...form, [key]: Number(e.target.value) })} />
      <span className="field-hint">{hint}</span>
    </div>
  );
  return (
    <Section id="evidence" title="Event evidence" description="snapshots saved at events only">
      <div className="form-grid">
        {field('snapshot_jpeg_quality', 'Image quality', '40–95. Lower saves space.', 40, 95)}
        {field('snapshot_max_width', 'Maximum image width (px)', 'Snapshots are crops of the person, resized to at most this width.', 160, 1920)}
        {field('snapshot_storage_limit_mb', 'Storage limit (MB)', `0 = no limit. ${usedMb !== undefined ? `Currently ${usedMb} MB used.` : ''} New images are skipped (not oldest deleted) when reached.`, 0, 1048576)}
        {field('alert_retention_days', 'Keep closed alerts for (days)', '0 keeps them. Open alerts are never deleted.', 0, 3650)}
      </div>
      {editable && (
        <div className="form-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={() => run(() => api('/settings', { method: 'PUT', body: form }), () => { setSaved(true); onSaved(); })}
          >
            Save
          </button>
          {saved && !error && <span className="small" style={{ color: 'var(--ok)' }} role="status">Saved</span>}
          {error && <span className="small" style={{ color: 'var(--err)' }} role="alert">{error}</span>}
        </div>
      )}
    </Section>
  );
}

// -- Alert rules ------------------------------------------------------------------------------------

export function AlertRulesSection() {
  const [rules, setRules] = useState<AlertRule[] | null>(null);
  const { error, run } = useAsync();
  const load = useCallback(() => run(async () => setRules(await api<AlertRule[]>('/alert-rules'))), [run]);
  useEffect(() => {
    load();
  }, [load]);

  const update = (rule: AlertRule, body: Record<string, unknown>) =>
    run(async () => {
      const updated = await api<AlertRule>(`/alert-rules/${rule.rule_type}`, { method: 'PUT', body });
      setRules((list) => list?.map((r) => (r.rule_type === rule.rule_type ? updated : r)) ?? null);
    });

  return (
    <Section id="alert-rules" title="Alert rules" description="explainable, reviewable conditions">
      <p className="small muted" style={{ marginBottom: 8 }}>
        Rules describe measurable situations. None of them identify people or decide intent; every alert is reviewed by a person.
        Zone rules use the zones drawn on each camera (Live Cameras page).
      </p>
      <ErrorBanner error={error} />
      {!rules ? (
        <p className="muted">Loading…</p>
      ) : (
        rules.map((r) => <RuleRow key={r.rule_type} rule={r} onUpdate={(body) => update(r, body)} />)
      )}
    </Section>
  );
}

function RuleRow({ rule, onUpdate }: { rule: AlertRule; onUpdate: (body: Record<string, unknown>) => void }) {
  const [params, setParams] = useState(rule.params);
  useEffect(() => setParams(rule.params), [rule.params]);
  const dirty = JSON.stringify(params) !== JSON.stringify(rule.params);
  return (
    <div className="rule-row">
      <div>
        <div style={{ fontWeight: 600 }}>
          {rule.title} <span className="badge" style={{ marginLeft: 6 }}>{CATEGORY_LABELS[rule.category] ?? rule.category}</span>
        </div>
        <div className="small muted">{rule.description}</div>
        {Object.keys(rule.param_specs).length > 0 && (
          <div className="rule-params">
            {Object.entries(rule.param_specs).map(([name, spec]) =>
              spec.type === 'bool' ? (
                <label key={name} className="small" style={{ alignSelf: 'end' }}>
                  <input type="checkbox" checked={Boolean(params[name])} onChange={(e) => setParams({ ...params, [name]: e.target.checked })} /> {spec.label}
                </label>
              ) : (
                <div className="field" key={name}>
                  <label htmlFor={`${rule.rule_type}-${name}`}>{spec.label || name}</label>
                  <input
                    id={`${rule.rule_type}-${name}`}
                    className="input"
                    type="number"
                    step={spec.type === 'float' ? 0.5 : 1}
                    min={spec.min ?? undefined}
                    max={spec.max ?? undefined}
                    value={Number(params[name])}
                    onChange={(e) => setParams({ ...params, [name]: Number(e.target.value) })}
                  />
                </div>
              ),
            )}
            {dirty && (
              <button type="button" className="btn btn-sm btn-primary" style={{ alignSelf: 'end' }} onClick={() => onUpdate({ params })}>
                Save parameters
              </button>
            )}
          </div>
        )}
      </div>
      <div style={{ display: 'grid', gap: 6, justifyItems: 'end', alignContent: 'start' }}>
        <label className="small">
          <input type="checkbox" checked={rule.enabled} onChange={(e) => onUpdate({ enabled: e.target.checked })} /> Enabled
        </label>
        <select className="select select-sm" aria-label={`Severity for ${rule.title}`} value={rule.severity} onChange={(e) => onUpdate({ severity: e.target.value })}>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {SEVERITY_LABELS[s]}
            </option>
          ))}
        </select>
        <label className="small muted" htmlFor={`${rule.rule_type}-cool`}>
          Re-notify after (min)
        </label>
        <input
          id={`${rule.rule_type}-cool`}
          className="input select-sm"
          type="number"
          min={0}
          max={1440}
          style={{ width: 90 }}
          defaultValue={Math.round(rule.cooldown_seconds / 60)}
          onBlur={(e) => Number(e.target.value) * 60 !== rule.cooldown_seconds && onUpdate({ cooldown_seconds: Number(e.target.value) * 60 })}
        />
      </div>
    </div>
  );
}

// -- Notification channels ------------------------------------------------------------------------

export function NotificationsSection({ emailConfigured }: { emailConfigured: boolean }) {
  const { timezone } = useSystem();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    kind: 'telegram' as 'email' | 'webhook' | 'telegram', name: '', min_severity: 'medium' as Severity, recipients: '', url: '', secret: '',
    bot_token: '', chat_id: '', attach_snapshot: false, rate_limit_per_hour: 30,
  });
  const { busy, error, setError, run } = useAsync();

  const load = useCallback(async () => {
    try {
      setChannels(await api<Channel[]>('/notification-channels'));
      setDeliveries(await api<Delivery[]>('/notification-deliveries?limit=20'));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [setError]);
  useEffect(() => {
    load();
  }, [load]);

  const create = () =>
    run(
      () =>
        api('/notification-channels', {
          method: 'POST',
          body: {
            kind: form.kind,
            name: form.name,
            min_severity: form.min_severity,
            rate_limit_per_hour: form.rate_limit_per_hour,
            ...(form.kind === 'email'
              ? { recipients: form.recipients.split(/[,\s]+/).filter(Boolean), attach_snapshot: form.attach_snapshot }
              : form.kind === 'telegram'
                ? { bot_token: form.bot_token.trim(), chat_id: form.chat_id.trim(), attach_snapshot: form.attach_snapshot }
                : { url: form.url, secret: form.secret }),
          },
        }),
      () => {
        setOpen(false);
        load();
      },
    );

  const channelName = (id: number) => channels.find((c) => c.id === id)?.name ?? `#${id}`;

  return (
    <Section id="notifications" title="Notifications" description="in-app always on; email and webhooks optional">
      <p className="small muted" style={{ marginBottom: 12 }}>
        Every alert appears in the app in real time. Channels below also deliver alerts at or above their minimum severity,
        with retries and an hourly limit. Snapshots are attached only when a channel opts in; webhooks never carry images.
        {!emailConfigured && ' Email channels need a mail server: set it up in the Mail server section below.'}
      </p>
      <ErrorBanner error={error} />
      {channels.length === 0 ? (
        <div className="empty" style={{ padding: 12 }}>No external channels.</div>
      ) : (
        <div className="table-wrap" style={{ margin: '0 -16px' }}>
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Sends to</th>
                <th>Minimum severity</th>
                <th>Limit / hour</th>
                <th><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {channels.map((c) => (
                <tr key={c.id}>
                  <td>
                    <strong>{c.name}</strong> {!c.enabled && <span className="badge">Off</span>}
                  </td>
                  <td>{c.kind === 'email' ? 'Email' : c.kind === 'telegram' ? 'Telegram' : 'Webhook'}</td>
                  <td className="small">
                    {c.target}
                    {c.attach_snapshot && <div className="muted">with snapshots</div>}
                  </td>
                  <td>
                    <SeverityBadge severity={c.min_severity} />
                  </td>
                  <td className="num">{c.rate_limit_per_hour}</td>
                  <td style={{ textAlign: 'right' }} className="nowrap">
                    <button type="button" className="btn btn-sm" onClick={() => run(() => api(`/notification-channels/${c.id}/test`, { method: 'POST' }), () => window.setTimeout(load, 3000))}>
                      <Send size={13} /> Test
                    </button>{' '}
                    <button type="button" className="btn btn-sm" onClick={() => run(() => api(`/notification-channels/${c.id}`, { method: 'PATCH', body: { enabled: !c.enabled } }), load)}>
                      {c.enabled ? 'Turn off' : 'Turn on'}
                    </button>{' '}
                    <button
                      type="button"
                      className="btn btn-sm btn-danger"
                      aria-label={`Delete ${c.name}`}
                      onClick={() => window.confirm(`Delete channel "${c.name}"?`) && run(() => api(`/notification-channels/${c.id}`, { method: 'DELETE' }), load)}
                    >
                      <Trash2 size={13} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="form-actions">
        <button type="button" className="btn" onClick={() => { setForm({ ...form, name: '', recipients: '', url: '', secret: '', bot_token: '', chat_id: '', attach_snapshot: false }); setError(null); setOpen(true); }}>
          <Plus size={14} /> Add channel
        </button>
      </div>

      {deliveries.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <p className="section-title">Recent deliveries</p>
          <ul className="audit-list">
            {deliveries.map((d) => (
              <li key={d.id}>
                <strong>{d.status}</strong> · {channelName(d.channel_id)} · {d.subject} · {formatDateTime(d.created_at, timezone)}
                {d.last_error && <span className="muted"> · {d.last_error}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Dialog
        open={open}
        title="Add notification channel"
        onClose={() => setOpen(false)}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button type="button" className="btn btn-primary" onClick={create} disabled={busy || !form.name.trim()}>
              Add
            </button>
          </>
        }
      >
        <div className="segmented" role="group" aria-label="Channel type">
          <button type="button" aria-pressed={form.kind === 'telegram'} onClick={() => setForm({ ...form, kind: 'telegram' })}>
            Telegram
          </button>
          <button type="button" aria-pressed={form.kind === 'email'} onClick={() => setForm({ ...form, kind: 'email' })}>
            Email
          </button>
          <button type="button" aria-pressed={form.kind === 'webhook'} onClick={() => setForm({ ...form, kind: 'webhook' })}>
            Webhook
          </button>
        </div>
        <div className="field">
          <label htmlFor="ch-name">Name</label>
          <input id="ch-name" className="input" maxLength={80} value={form.name} placeholder="Store manager" onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        {form.kind === 'telegram' ? (
          <>
            <div className="field">
              <label htmlFor="ch-token">Bot token</label>
              <input id="ch-token" className="input mono" type="password" autoComplete="off" value={form.bot_token} placeholder="123456789:AA…" onChange={(e) => setForm({ ...form, bot_token: e.target.value })} />
              <span className="field-hint">Create a bot by messaging @BotFather on Telegram (/newbot). Stored encrypted, never shown again.</span>
            </div>
            <div className="field">
              <label htmlFor="ch-chat">Chat ID</label>
              <input id="ch-chat" className="input mono" value={form.chat_id} placeholder="123456789" onChange={(e) => setForm({ ...form, chat_id: e.target.value })} />
              <span className="field-hint">Send /start to your bot first. Your ID comes from @userinfobot; group IDs start with -100.</span>
            </div>
          </>
        ) : form.kind === 'email' ? (
          <div className="field">
            <label htmlFor="ch-rcpt">Recipients</label>
            <input id="ch-rcpt" className="input" value={form.recipients} placeholder="owner@example.com, manager@example.com" onChange={(e) => setForm({ ...form, recipients: e.target.value })} />
          </div>
        ) : (
          <>
            <div className="field">
              <label htmlFor="ch-url">URL</label>
              <input id="ch-url" className="input" value={form.url} placeholder="https://hooks.example.com/viahind" onChange={(e) => setForm({ ...form, url: e.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="ch-secret">Signing secret</label>
              <input id="ch-secret" className="input" type="password" autoComplete="off" value={form.secret} onChange={(e) => setForm({ ...form, secret: e.target.value })} />
              <span className="field-hint">At least 16 characters. Requests carry X-VV-Signature: sha256=HMAC(body).</span>
            </div>
          </>
        )}
        <div className="field">
          <label htmlFor="ch-sev">Minimum severity</label>
          <select id="ch-sev" className="select" value={form.min_severity} onChange={(e) => setForm({ ...form, min_severity: e.target.value as Severity })}>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {SEVERITY_LABELS[s]}
              </option>
            ))}
          </select>
        </div>
        {form.kind !== 'webhook' && (
          <label className="small">
            <input type="checkbox" checked={form.attach_snapshot} onChange={(e) => setForm({ ...form, attach_snapshot: e.target.checked })} /> Attach the evidence
            snapshot <span className="muted">(the image leaves your premises and is stored by {form.kind === 'telegram' ? 'Telegram' : 'the mail provider'})</span>
          </label>
        )}
        <div className="field">
          <label htmlFor="ch-rate">Maximum messages per hour</label>
          <input id="ch-rate" className="input" type="number" min={1} max={1000} value={form.rate_limit_per_hour} onChange={(e) => setForm({ ...form, rate_limit_per_hour: Number(e.target.value) })} />
        </div>
        <ErrorBanner error={error} />
      </Dialog>
    </Section>
  );
}

// -- Mail server ------------------------------------------------------------------------------------

export function MailServerSection({ onSaved }: { onSaved?: () => void }) {
  const [data, setData] = useState<MailServer | null>(null);
  const [form, setForm] = useState({ host: '', port: 587, security: 'starttls' as MailServer['security'], username: '', password: '', from_address: '', from_name: '' });
  const [testTo, setTestTo] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const { busy, error, setError, run } = useAsync();

  const apply = useCallback((d: MailServer) => {
    setData(d);
    setForm({ host: d.host, port: d.port, security: d.security, username: d.username, password: '', from_address: d.from_address, from_name: d.from_name });
  }, []);
  const load = useCallback(async () => {
    try {
      apply(await api<MailServer>('/mail-server'));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [apply, setError]);
  useEffect(() => {
    load();
  }, [load]);

  const preset = (key: string) => {
    const p = data?.presets[key];
    if (!p) return;
    setForm({ ...form, host: p.host || form.host, port: p.port, security: p.security });
    setNotice(p.hint || null);
  };
  const save = () =>
    run(
      async () => {
        const body = { ...form, password: form.password ? form.password : null };
        apply(await api<MailServer>('/mail-server', { method: 'PUT', body }));
        setNotice('Mail server saved. Send a test email to check it.');
      },
      onSaved,
    );
  const test = () =>
    run(async () => {
      const r = await api<{ via: string }>('/mail-server/test', { method: 'POST', body: { to: testTo } });
      setNotice(`Test email sent via ${r.via}. Check the inbox (and spam folder) of ${testTo}.`);
    });
  const remove = () =>
    window.confirm('Remove the mail server settings? Email channels will stop until a new one is set.') &&
    run(async () => {
      await api('/mail-server', { method: 'DELETE' });
      setNotice(null);
      await load();
    }, onSaved);

  const presetLabel = (k: string) => (k === 'gmail' ? 'Gmail' : k === 'outlook' ? 'Outlook / Microsoft 365' : k === 'zoho' ? 'Zoho' : 'Other');

  return (
    <Section id="mail-server" title="Mail server" description="the account that sends alert and briefing emails">
      <p className="small muted" style={{ marginBottom: 12 }}>
        {data?.source === 'environment'
          ? 'Currently using the SMTP settings from the server environment (.env). Saving here overrides them for your organization.'
          : data?.configured
            ? 'Emails are sent through the account below. The password is stored encrypted and never shown again.'
            : 'No mail server yet. For Gmail, turn on 2-Step Verification and create an App Password, then choose the Gmail preset.'}
      </p>
      {data?.error && <ErrorBanner error={data.error} />}
      <div className="segmented" role="group" aria-label="Provider preset" style={{ marginBottom: 12 }}>
        {Object.keys(data?.presets ?? {}).map((k) => (
          <button key={k} type="button" aria-pressed={k !== 'custom' && form.host === data?.presets[k].host} onClick={() => preset(k)}>
            {presetLabel(k)}
          </button>
        ))}
      </div>
      <div className="form-grid">
        <div className="field">
          <label htmlFor="mail-host">SMTP host</label>
          <input id="mail-host" className="input mono" value={form.host} placeholder="smtp.gmail.com" onChange={(e) => setForm({ ...form, host: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="mail-port">Port</label>
          <input id="mail-port" className="input" type="number" min={1} max={65535} value={form.port} onChange={(e) => setForm({ ...form, port: Number(e.target.value) })} />
        </div>
        <div className="field">
          <label htmlFor="mail-sec">Security</label>
          <select id="mail-sec" className="select" value={form.security} onChange={(e) => setForm({ ...form, security: e.target.value as MailServer['security'] })}>
            <option value="starttls">STARTTLS (port 587)</option>
            <option value="ssl">SSL/TLS (port 465)</option>
            <option value="none">None (local relay only)</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="mail-user">Username</label>
          <input id="mail-user" className="input" autoComplete="off" value={form.username} placeholder="you@gmail.com" onChange={(e) => setForm({ ...form, username: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="mail-pass">Password / App Password</label>
          <input
            id="mail-pass"
            className="input"
            type="password"
            autoComplete="new-password"
            value={form.password}
            placeholder={data?.has_password ? '•••••••• (unchanged)' : ''}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
        </div>
        <div className="field">
          <label htmlFor="mail-from">Send from (address)</label>
          <input id="mail-from" className="input" value={form.from_address} placeholder="you@gmail.com" onChange={(e) => setForm({ ...form, from_address: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="mail-name">Sender name</label>
          <input id="mail-name" className="input" maxLength={80} value={form.from_name} placeholder="Sunrise PG Security" onChange={(e) => setForm({ ...form, from_name: e.target.value })} />
        </div>
      </div>
      {notice && (
        <div className="banner banner-info" role="status" style={{ margin: '12px 0' }}>
          {notice}
        </div>
      )}
      <ErrorBanner error={error} />
      <div className="form-actions">
        <button type="button" className="btn btn-primary" onClick={save} disabled={busy || !form.host.trim() || !form.from_address.trim()}>
          <Mail size={14} /> Save mail server
        </button>
        {data?.source === 'console' && (
          <button type="button" className="btn btn-danger" onClick={remove} disabled={busy}>
            Remove
          </button>
        )}
      </div>
      {data?.configured && (
        <div className="form-actions" style={{ alignItems: 'flex-end' }}>
          <div className="field" style={{ flex: 1, maxWidth: 320, marginBottom: 0 }}>
            <label htmlFor="mail-test">Send a test email to</label>
            <input id="mail-test" className="input" value={testTo} placeholder="owner@example.com" onChange={(e) => setTestTo(e.target.value)} />
          </div>
          <button type="button" className="btn" onClick={test} disabled={busy || !testTo.includes('@')}>
            <Send size={14} /> Send test
          </button>
        </div>
      )}
    </Section>
  );
}

// -- Scheduled reports --------------------------------------------------------------------------------

export function SchedulesSection() {
  const { locations, timezone } = useSystem();
  const [rows, setRows] = useState<ReportSchedule[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [form, setForm] = useState({ name: 'Weekly footfall', frequency: 'weekly', location_id: '', channel_id: '' });
  const { busy, error, setError, run } = useAsync();
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api<ReportSchedule[]>('/report-schedules'));
      setChannels(await api<Channel[]>('/notification-channels'));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [setError]);
  useEffect(() => {
    load();
  }, [load]);

  return (
    <Section id="schedules" title="Scheduled reports" description="sent after each completed period">
      <ErrorBanner error={error} />
      {notice && <p className="small" role="status" style={{ color: 'var(--ok)', marginBottom: 8 }}>{notice}</p>}
      {rows.length > 0 && (
        <ul className="audit-list" style={{ marginBottom: 12 }}>
          {rows.map((r) => (
            <li key={r.id} className="control-row" style={{ justifyContent: 'space-between' }}>
              <span>
                <strong>{r.name}</strong> · {r.frequency} · {r.location_id ? locations.find((l) => l.id === r.location_id)?.name : 'All locations'} ·{' '}
                {channels.find((c) => c.id === r.channel_id)?.name ?? 'channel removed'}
                {r.last_run_at && <span className="muted"> · last sent {formatDateTime(r.last_run_at, timezone)}</span>}
              </span>
              <span className="nowrap">
                <button type="button" className="btn btn-sm" onClick={() => run(() => api(`/report-schedules/${r.id}/send`, { method: 'POST' }), () => setNotice('Report queued.'))}>
                  Send now
                </button>{' '}
                <button type="button" className="btn btn-sm btn-danger" aria-label={`Delete ${r.name}`} onClick={() => run(() => api(`/report-schedules/${r.id}`, { method: 'DELETE' }), load)}>
                  <Trash2 size={13} />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {channels.length === 0 ? (
        <p className="muted small">Add an email or webhook channel under Notifications to schedule reports.</p>
      ) : (
        <div className="form-grid">
          <div className="field">
            <label htmlFor="s-name">Name</label>
            <input id="s-name" className="input" maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="s-freq">Frequency</label>
            <select id="s-freq" className="select" value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value })}>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly (Mon–Sun)</option>
              <option value="monthly">Monthly</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="s-loc">Location</label>
            <select id="s-loc" className="select" value={form.location_id} onChange={(e) => setForm({ ...form, location_id: e.target.value })}>
              <option value="">All locations</option>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="s-ch">Send to</label>
            <select id="s-ch" className="select" value={form.channel_id} onChange={(e) => setForm({ ...form, channel_id: e.target.value })}>
              <option value="">Choose a channel</option>
              {channels.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ justifyContent: 'end' }}>
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy || !form.channel_id || !form.name.trim()}
              onClick={() =>
                run(
                  () => api('/report-schedules', { method: 'POST', body: { name: form.name, frequency: form.frequency, location_id: form.location_id ? Number(form.location_id) : null, channel_id: Number(form.channel_id) } }),
                  load,
                )
              }
            >
              <Plus size={14} /> Add schedule
            </button>
          </div>
        </div>
      )}
    </Section>
  );
}

// -- Anomaly model --------------------------------------------------------------------------------------

const MODEL_STATUS: Record<string, string> = { ready: 'Ready', insufficient_data: 'Not enough data', failed: 'Failed', retired: 'Retired' };

export function AnomalyModelSection() {
  const { timezone } = useSystem();
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [days, setDays] = useState(60);
  const { busy, error, run } = useAsync();
  const load = useCallback(() => run(async () => setStatus(await api<ModelStatus>('/ml/anomaly-model'))), [run]);
  useEffect(() => {
    load();
  }, [load]);

  const latest = status?.history[0];
  return (
    <Section id="anomaly-model" title="Unusual-pattern detection" description="optional statistical baseline">
      <p className="small muted" style={{ marginBottom: 12 }}>
        An Isolation Forest learns each location&apos;s normal hourly activity (entries, exits, unclassified crossings, time of day and
        weekday) from real recorded events only, then raises low-severity alerts for unusual hours. A score is a statistical outlier,
        never evidence of a problem. It needs at least {status?.requirements.min_hours ?? 168} hours of data over {status?.requirements.min_days ?? 7} days.
      </p>
      <ErrorBanner error={error} />
      {!status ? (
        <p className="muted">Loading…</p>
      ) : (
        <div style={{ display: 'grid', gap: 12 }}>
          {!status.available && <div className="banner banner-warn">{status.message}</div>}
          <dl className="kv">
            <dt>Active model</dt>
            <dd>{status.active ? `${status.active.version} · trained ${formatDateTime(status.active.trained_at, timezone)} on ${status.active.n_samples} hours` : 'None'}</dd>
            {status.active && (
              <>
                <dt>Last scored</dt>
                <dd>{status.active.last_inference_at ? formatDateTime(status.active.last_inference_at, timezone) : 'Not yet (runs hourly)'}</dd>
              </>
            )}
            {latest && (
              <>
                <dt>Last training run</dt>
                <dd>
                  <span className={`badge ${latest.status === 'ready' ? 'badge-ok' : latest.status === 'failed' ? 'badge-err' : 'badge-warn'}`}>{MODEL_STATUS[latest.status] ?? latest.status}</span>{' '}
                  {latest.message}
                </dd>
              </>
            )}
            <dt>Review feedback</dt>
            <dd>
              {status.review_feedback.alerts} alert(s): {status.review_feedback.resolved} resolved, {status.review_feedback.dismissed} dismissed as false positives
              {status.review_feedback.dismissed_rate !== null && ` (${Math.round(status.review_feedback.dismissed_rate * 100)}% dismissed)`}.
            </dd>
          </dl>
          <div className="control-row">
            <label htmlFor="ml-days" className="small">
              Train on the last
            </label>
            <input id="ml-days" className="input" type="number" min={7} max={180} value={days} style={{ width: 80 }} onChange={(e) => setDays(Number(e.target.value))} />
            <span className="small">days</span>
            <button type="button" className="btn btn-primary" disabled={busy || !status.enabled || !status.available} onClick={() => run(() => api('/ml/anomaly-model/train', { method: 'POST', body: { days } }), load)}>
              <BrainCircuit size={14} /> {busy ? 'Training…' : 'Train now'}
            </button>
          </div>
        </div>
      )}
    </Section>
  );
}

// -- Video anomaly detection ----------------------------------------------------------------------------

export function VideoAnomalySection() {
  const { settings } = useSystem();
  const a = settings?.system.anomaly;
  if (!a) return null;
  const m = a.holdout_metrics;
  const modeLabel =
    a.status === 'disabled'
      ? 'Disabled'
      : a.mode === 'model'
        ? 'Trained classifier'
        : a.mode === 'motion'
          ? 'Motion detector (no trained weights)'
          : a.status === 'error'
            ? 'Error'
            : 'Not running';
  const tone = a.status === 'ready' ? 'badge-ok' : a.status === 'motion' ? 'badge-info' : a.status === 'error' ? 'badge-err' : 'badge-warn';
  return (
    <Section id="video-anomaly" title="Video anomaly detection" description={a.model_name ?? 'VIAHIND-FightClassifier-MobileNetV3'}>
      <div style={{ display: 'grid', gap: 12 }}>
        <div className="control-row">
          <span className={`badge ${tone}`}>{modeLabel}</span>
          {a.model_version && <span className="small muted">version {a.model_version}</span>}
        </div>
        {a.message && <p className="small">{a.message}</p>}
        <dl className="kv">
          {a.mode === 'model' && (
            <>
              <dt>Decision threshold</dt>
              <dd>{a.threshold?.toFixed(2)}</dd>
              {m && (
                <>
                  <dt>Hold-out results</dt>
                  <dd>
                    accuracy {m.accuracy}, precision {m.precision}, recall {m.recall}, F1 {m.f1}
                    <div className="small muted">Measured on the videos held out during training; real cameras usually perform worse.</div>
                  </dd>
                </>
              )}
            </>
          )}
          {a.status !== 'disabled' && (
            <>
              <dt>Confirmation</dt>
              <dd>An alert needs {a.min_consecutive_clips ?? 2} positive clips in a row on the same camera.</dd>
              <dt>Activity</dt>
              <dd>
                {a.processed_clips ?? 0} clips analysed, {a.positive_clips ?? 0} positive, {a.dropped_clips ?? 0} skipped while busy
                {a.last_inference_ms ? `, last analysis ${a.last_inference_ms} ms` : ''}
                {a.failed_inferences ? `, ${a.failed_inferences} failed` : ''}.
              </dd>
            </>
          )}
        </dl>
        <div className="banner banner-info" style={{ marginBottom: 0 }}>
          <div className="small">
            <strong>How it works.</strong> Without trained weights, the motion detector reports <em>vigorous movement between people in
            close contact</em> (it needs person detection on the camera). It does not recognise fights: hugging, play and crowding can
            trigger it. To use the altercation classifier, train it on labelled clips you are licensed to use (for example the RWF-2000
            dataset layout), then set <span className="mono">FIGHT_MODEL_PATH</span> and restart:
            <pre className="mono small" style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>python manage.py train-fight-model --data path/to/clips --pretrained-backbone</pre>
            Every detection is a reviewable alert with a snapshot; never act on it without checking the footage.
          </div>
        </div>
      </div>
    </Section>
  );
}
