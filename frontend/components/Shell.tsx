'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Building2, Camera as CameraIcon, LayoutDashboard, LogOut, ScrollText, Settings, ShieldCheck, Video, Wifi, WifiOff } from 'lucide-react';
import { useSession } from './SessionProvider';
import { useSystem } from './SystemProvider';
import { formatDate, formatTime } from '@/lib/format';

const NAV = [
  { href: '/overview', label: 'Overview', icon: LayoutDashboard },
  { href: '/live', label: 'Live Camera', icon: Video },
  { href: '/logs', label: 'Entry & Exit Logs', icon: ScrollText },
  { href: '/settings', label: 'Settings', icon: Settings },
];

function Brand() {
  return (
    <div className="brand">
      <div className="brand-mark" aria-hidden="true">
        <ShieldCheck size={18} />
      </div>
      <div>
        <div className="brand-name">VIAHIND Vision</div>
        <div className="brand-sub">PG Surveillance System</div>
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
    <span className="meta-item" title={`Site time (${timezone})`}>
      <span className="hide-md">{formatDate(now, timezone)}</span>
      <span className="mono">{formatTime(now, timezone)}</span>
    </span>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, signOut } = useSession();
  const { settings, timezone, cameras, selectedCameraId, connected } = useSystem();
  const selected = cameras.find((c) => c.id === selectedCameraId);
  const live = cameras.filter((c) => c.runtime.status === 'live').length;

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Main navigation">
        <Brand />
        <nav className="nav">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} className="nav-link" aria-current={pathname === href ? 'page' : undefined}>
              <Icon size={17} aria-hidden="true" />
              {label}
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
            <span className="t1">VIAHIND Vision</span>
            <span className="t2">PG Surveillance System</span>
          </div>
          <div className="topbar-meta">
            {settings && (
              <span className="meta-item hide-md" title="Site">
                <Building2 size={15} aria-hidden="true" />
                {settings.site.site_name}
              </span>
            )}
            {selected && (
              <span className="meta-item hide-md" title="Selected camera">
                <CameraIcon size={15} aria-hidden="true" />
                {selected.name}
              </span>
            )}
            <span className="meta-sep" aria-hidden="true" />
            <Clock timezone={timezone} />
            <span className="meta-sep" aria-hidden="true" />
            {connected ? (
              <span className="badge badge-ok" title={`${live} of ${cameras.length} camera(s) live`}>
                <Wifi size={13} aria-hidden="true" />
                Connected
              </span>
            ) : (
              <span className="badge badge-err" title="The real-time connection to the server is down; retrying.">
                <WifiOff size={13} aria-hidden="true" />
                Offline
              </span>
            )}
          </div>
        </header>
        <nav className="mobile-nav" aria-label="Sections">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} aria-current={pathname === href ? 'page' : undefined}>
              <Icon size={15} aria-hidden="true" />
              {label}
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
