'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import NavBar from '@/components/NavBar';
import { useApi } from '@/hooks/useApi';
import type { RegistrationInvitePreviewResponse } from '@/types/api';

type RegisterPageClientProps = {
  token: string;
};

export default function RegisterPageClient({ token }: RegisterPageClientProps) {
  const api = useApi();
  const [preview, setPreview] = useState<RegistrationInvitePreviewResponse | null>(null);
  const [name, setName] = useState('');
  const [loadingPreview, setLoadingPreview] = useState(Boolean(token));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setLoadingPreview(false);
      return;
    }

    let cancelled = false;

    async function loadPreview() {
      try {
        const result = await api.previewRegistrationInvite(token);
        if (cancelled) {
          return;
        }
        setPreview(result);
        setName(result.name_hint || '');
      } catch (err) {
        if (cancelled) {
          return;
        }
        setError(err instanceof Error ? err.message : 'Failed to load registration link');
      } finally {
        if (!cancelled) {
          setLoadingPreview(false);
        }
      }
    }

    void loadPreview();
    return () => {
      cancelled = true;
    };
  }, [api, token]);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token) {
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await api.consumeRegistrationInvite({
        token,
        name: name.trim() ? name.trim() : null,
      });
      window.location.href = '/dashboard';
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to complete registration');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-cream">
      <NavBar />
      <div className="mx-auto max-w-2xl px-6 py-16">
        <div className="rounded-3xl border border-line bg-panel p-8 shadow-sm">
          <h1 className="text-2xl font-semibold text-ink">Complete Registration</h1>

          {!token && (
            <p className="mt-3 text-sm text-muted">
              Open this page from a registration link sent by your admin.
            </p>
          )}

          {loadingPreview && <p className="mt-3 text-sm text-muted">Validating your invite…</p>}

          {error && (
            <div className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600">
              {error}
            </div>
          )}

          {preview && !loadingPreview && (
            <form onSubmit={handleSubmit} className="mt-6 space-y-4">
              <div className="rounded-2xl bg-cream px-4 py-3 text-sm text-ink">
                <div className="font-mono text-xs text-muted">{preview.email}</div>
                <div className="mt-1">
                  {preview.is_admin ? 'Admin access' : 'User access'} • {preview.team_ids.length}{' '}
                  team assignment{preview.team_ids.length === 1 ? '' : 's'}
                </div>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Display Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Your name"
                  className="w-full rounded-lg border border-line bg-cream px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                />
              </div>

              <button
                type="submit"
                disabled={submitting}
                className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {submitting ? 'Creating account…' : 'Create account'}
              </button>
            </form>
          )}

          <div className="mt-6">
            <Link href="/auth/sign-in" className="text-sm font-medium text-accent hover:underline">
              Need a sign-in link instead?
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
