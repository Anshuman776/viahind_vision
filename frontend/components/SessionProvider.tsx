'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { api, onUnauthorized } from '@/lib/api';
import type { User } from '@/lib/types';

interface SessionValue {
  user: User;
  isAdmin: boolean;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useSession must be used inside SessionProvider');
  return value;
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  const toLogin = useCallback(() => {
    router.replace(`/login?next=${encodeURIComponent(pathname || '/overview')}`);
  }, [router, pathname]);

  const load = useCallback(() => {
    setError(null);
    api<User>('/auth/me')
      .then(setUser)
      .catch((err) => {
        if (err.status === 401) toLogin();
        else setError(err.message);
      });
  }, [toLogin]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => onUnauthorized(toLogin), [toLogin]);

  const signOut = useCallback(async () => {
    try {
      await api('/auth/logout', { method: 'POST' });
    } finally {
      router.replace('/login');
    }
  }, [router]);

  if (error) {
    return (
      <div className="login-page">
        <div className="panel login-card" role="alert">
          <div className="panel-body">
            <p className="section-title">Cannot load VIAHIND Vision</p>
            <p className="muted" style={{ marginBottom: 12 }}>{error}</p>
            <button type="button" className="btn btn-primary" onClick={load}>
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }
  if (!user) {
    return (
      <div className="login-page" aria-busy="true">
        <p className="muted">Checking your session…</p>
      </div>
    );
  }
  return (
    <SessionContext.Provider value={{ user, isAdmin: user.role === 'admin', signOut }}>{children}</SessionContext.Provider>
  );
}
