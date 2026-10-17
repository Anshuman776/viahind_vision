'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { BarChart3, Bell, Images, LayoutDashboard, LogOut, ScanEye, ScrollText, Settings, ShieldCheck, Video, Wifi, WifiOff } from 'lucide-react';
import { useSession } from './SessionProvider';
import { useSystem } from './SystemProvider';
import { formatDate, formatTime } from '@/lib/format';

interface NavItem {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  operatorOnly?: boolean;
  badge?: 'alerts';
}

const NAV: NavItem[] = [
  { href: '/overview', label: 'Overview', icon: LayoutDashboard },
  { href: '/live', label: 'Live Cameras', icon: Video, operatorOnly: true },
  { href: '/guards', label: 'Guard Room', icon: ShieldCheck, operatorOnly: true },
  { href: '/alerts', label: 'Alerts', icon: Bell, operatorOnly: true, badge: 'alerts' },
  { href: '/logs', label: 'Entry & Exit Logs', icon: ScrollText, operatorOnly: true },
  { href: '/evidence', label: 'Event Evidence', icon: Images, operatorOnly: true },
  { href: '/reports', label: 'Reports', icon: BarChart3 },
  { href: '/settings', label: 'Settings', icon: Settings },
];

export const PRODUCT_TAGLINE = 'AI CCTV Business Intelligence';

function Brand() {
  return (
    <div className="brand">
      <div className="brand-mark" aria-hidden="true">
        <ScanEye size={18} />
      </div>
      <div>
        <div className="brand-name">VIAHIND Vision</div>
        <div className="brand-sub">{PRODUCT_TAGLINE}</div>
      </div>
    </div>
  );
}

function Clock({ timezone }: { timezone: string }) {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const t = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(t);
  }, []);
  if (!now) return null;
  return (
    <span className="meta-item" title={`Business time (${timezone})`}>
      <span className="hide-md">{formatDate(now, timezone)}</span>
      <span className="mono">{formatTime(now, timezone)}</span>
    </span>
  );
}

export function LocationSwitcher({ compact = false }: { compact?: boolean }) {
  const { locations, locationId, selectLocation } = useSystem();
  if (locations.length < 2) return null;
  return (
    <span className="meta-item">
      <label className="sr-only" htmlFor={compact ? 'loc-switch-m' : 'loc-switch'}>
        Location
      </label>
      <select
        id={compact ? 'loc-switch-m' : 'loc-switch'}
        className="select select-sm"
        value={locationId ?? ''}
        onChange={(e) => selectLocation(e.target.value ? Number(e.target.value) : null)}
      >
        <option value="">All locations</option>
        {locations
          .filter((l) => l.is_active)
          .map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
      </select>
    </span>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, isOperator, signOut } = useSession();
  const { settings, timezone, cameras, connected, newAlerts } = useSystem();
  const live = cameras.filter((c) => c.runtime.status === 'live').length;
  const nav = NAV.filter((n) => isOperator || !n.operatorOnly);
  const orgName = user.organization?.name ?? settings?.site.site_name;

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Main navigation">
        <Brand />
        <nav className="nav">
          {nav.map(({ href, label, icon: Icon, badge }) => (
            <Link key={href} href={href} className="nav-link" aria-current={pathname === href ? 'page' : undefined}>
              <Icon size={17} aria-hidden="true" />
              {label}
              {badge === 'alerts' && newAlerts > 0 && (
                <span className="nav-count" aria-label={`${newAlerts} new alerts`}>
                  {newAlerts > 99 ? '99+' : newAlerts}
                </span>
              )}
            </Link>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="user-meta">
            <div className="user-name">{user.username}</div>
            <div className="user-role">{user.role}</div>
          </div>
          <button type="button" className="btn btn-ghost btn-icon" onClick={signOut} title="Sign out" aria-label="Sign out">
            <LogOut size={16} />
          </button>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-title">
            <span className="t1">{orgName || 'VIAHIND Vision'}</span>
            <span className="t2">{PRODUCT_TAGLINE}</span>
          </div>
          <div className="topbar-meta">
            <LocationSwitcher />
            <span className="meta-sep" aria-hidden="true" />
            <Clock timezone={timezone} />
            <span className="meta-sep" aria-hidden="true" />
            {connected ? (
              <span className="badge badge-ok" title={`Real-time updates connected · ${live} of ${cameras.length} camera(s) live`}>
                <Wifi size={13} aria-hidden="true" />
                Real-time
              </span>
            ) : (
              <span className="badge badge-err" title="The real-time connection to the server is down; figures may be delayed. Retrying.">
                <WifiOff size={13} aria-hidden="true" />
                Offline
              </span>
            )}
          </div>
        </header>
        <nav className="mobile-nav" aria-label="Sections">
          {nav.map(({ href, label, icon: Icon, badge }) => (
            <Link key={href} href={href} aria-current={pathname === href ? 'page' : undefined}>
              <Icon size={15} aria-hidden="true" />
              {label}
              {badge === 'alerts' && newAlerts > 0 && <span className="nav-count">{newAlerts}</span>}
            </Link>
          ))}
          <button type="button" className="btn btn-ghost btn-sm" onClick={signOut} style={{ marginLeft: 'auto', alignSelf: 'center' }}>
            Sign out
          </button>
        </nav>
        {settings?.system.demo_mode && (
          <div className="banner banner-warn" style={{ margin: '12px 24px 0', borderRadius: 6 }} role="note">
            Demo mode: all records shown are synthetic sample data from a separate demo database.
          </div>
        )}
        <main className="content" id="main">
          {children}
        </main>
      </div>
    </div>
  );
}
