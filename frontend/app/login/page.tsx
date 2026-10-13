'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ShieldCheck } from 'lucide-react';
import { api } from '@/lib/api';

function safeNext(): string {
  if (typeof window === 'undefined') return '/overview';
  const next = new URLSearchParams(window.location.search).get('next') || '/overview';
  // Only allow same-site relative paths.
  return next.startsWith('/') && !next.startsWith('//') ? next : '/overview';
}

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [hasUsers, setHasUsers] = useState<boolean | null>(null);

  useEffect(() => {
    api<{ has_users: boolean }>('/auth/setup-status')
      .then((s) => setHasUsers(s.has_users))
      .catch((err) => setError(err.message));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api('/auth/login', { method: 'POST', body: { username, password } });
      router.replace(safeNext());
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <main className="login-page">
      <div className="panel login-card">
        <div className="panel-body">
          <div className="brand">
            <div className="brand-mark" aria-hidden="true">
              <ShieldCheck size={18} />
            </div>
            <div>
              <h1 className="brand-name">VIAHIND Vision</h1>
              <div className="brand-sub">PG Surveillance System</div>
            </div>
          </div>

          {hasUsers === false && (
            <div className="banner banner-info" role="note">
              <div>
                No operator accounts exist yet. On the server, run
                <br />
                <code className="mono">python manage.py create-user &lt;name&gt; --role admin</code>
                <br />
                from the <code className="mono">backend</code> folder.
              </div>
            </div>
          )}

          <form onSubmit={submit} noValidate>
            <div className="field">
              <label htmlFor="username">Username</label>
              <input id="username" className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input id="password" type="password" className="input" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            {error && (
              <div className="banner banner-err" role="alert" style={{ marginBottom: 0 }}>
                {error}
              </div>
            )}
            <button type="submit" className="btn btn-primary" disabled={busy || !username || !password}>
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
            <p className="muted small">
              Authorised operators only. Camera footage and records are personal data; access is logged.
            </p>
          </form>
        </div>
      </div>
    </main>
  );
}
