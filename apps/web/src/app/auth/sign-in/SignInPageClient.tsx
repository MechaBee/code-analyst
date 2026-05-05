'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import NavBar from '@/components/NavBar';
import { useApi } from '@/hooks/useApi';

type SignInPageClientProps = {
  token: string;
};

export default function SignInPageClient({ token }: SignInPageClientProps) {
  const api = useApi();
  const [status, setStatus] = useState<'idle' | 'loading' | 'success' | 'error'>(
    token ? 'loading' : 'idle'
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      return;
    }

    let cancelled = false;

    async function consume() {
      try {
        await api.consumeSignInLink({ token });
        if (cancelled) {
          return;
        }
        setStatus('success');
        window.location.href = '/dashboard';
      } catch (err) {
        if (cancelled) {
          return;
        }
        setStatus('error');
        setError(err instanceof Error ? err.message : 'Failed to sign in');
      }
    }

    void consume();
    return () => {
      cancelled = true;
    };
  }, [api, token]);

  return (
    <div className="min-h-screen bg-cream">
      <NavBar />
      <div className="mx-auto max-w-2xl px-6 py-16">
        <div className="rounded-3xl border border-line bg-panel p-8 shadow-sm">
          <h1 className="text-2xl font-semibold text-ink">Sign In</h1>

          {!token && (
            <p className="mt-3 text-sm text-muted">
              Ask your admin to send you a sign-in link.
            </p>
          )}

          {token && status === 'loading' && (
            <p className="mt-3 text-sm text-muted">Validating your sign-in link…</p>
          )}

          {token && status === 'error' && (
            <div className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600">
              {error || 'This sign-in link is invalid or has expired.'}
            </div>
          )}

          {token && status === 'error' && (
            <p className="mt-4 text-sm text-muted">
              Request a fresh sign-in link from your admin.
            </p>
          )}

          {status === 'success' && (
            <p className="mt-3 text-sm text-muted">Redirecting to your dashboard…</p>
          )}

          <div className="mt-6">
            <Link href="/dashboard" className="text-sm font-medium text-accent hover:underline">
              Back to dashboard
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
