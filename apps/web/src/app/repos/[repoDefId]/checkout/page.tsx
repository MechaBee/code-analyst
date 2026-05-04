'use client';

import React, { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { useApi } from '@/hooks/useApi';
import { cn } from '@/lib/utils';
import NavBar from '@/components/NavBar';
import type { CheckoutCreateResponse } from '@/types/api';

export default function CheckoutPage() {
  const params = useParams<{ repoDefId: string }>();
  const repoDefId = params.repoDefId;
  const api = useApi();
  const [checkout, setCheckout] = useState<CheckoutCreateResponse | null>(null);
  const [ref, setRef] = useState('main');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCheckout = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.createCheckout(repoDefId, { repo_def_id: repoDefId, ref });
      setCheckout(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Checkout failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-cream">
      <NavBar active="repos" />
      <div className="p-6">
        <div className="mx-auto max-w-2xl space-y-6">
          <h1 className="text-2xl font-bold text-ink">Checkout Repository</h1>

          {error && (
            <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
              {error}
            </div>
          )}

          <div className="space-y-4 rounded-xl border border-line bg-panel p-5 shadow-sm">
            <div>
              <label className="mb-1 block text-xs font-medium text-ink">Branch / Ref</label>
              <input
                type="text"
                value={ref}
                onChange={(e) => setRef(e.target.value)}
                className={cn(
                  'w-full rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                  'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                  'border-line'
                )}
              />
            </div>
            <button
              onClick={handleCheckout}
              disabled={loading}
              className={cn(
                'w-full rounded-lg px-4 py-2 text-sm font-semibold text-white transition',
                loading ? 'cursor-not-allowed bg-accent/60' : 'bg-accent hover:bg-accent/90'
              )}
            >
              {loading ? 'Checking out…' : 'Checkout'}
            </button>
          </div>

          {checkout && (
            <div className="space-y-4 rounded-xl border border-line bg-panel p-5 shadow-sm">
              <h2 className="text-lg font-semibold text-ink">Checkout Created</h2>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <span className="text-muted">Checkout ID:</span>
                  <div className="font-mono text-ink">{checkout.checkout_id}</div>
                </div>
                <div>
                  <span className="text-muted">Branch:</span>
                  <div className="text-ink">{checkout.branch}</div>
                </div>
                <div>
                  <span className="text-muted">Commit:</span>
                  <div className="font-mono text-ink">{checkout.commit_sha.slice(0, 12)}</div>
                </div>
                <div>
                  <span className="text-muted">Workspace:</span>
                  <div className="font-mono text-ink">{checkout.workspace_id.slice(0, 12)}…</div>
                </div>
                <div>
                  <span className="text-muted">Snapshot:</span>
                  <div className="font-mono text-ink">{checkout.snapshot_id.slice(0, 12)}…</div>
                </div>
                <div>
                  <span className="text-muted">Timestamp:</span>
                  <div className="text-ink">
                    {new Date(checkout.run_timestamp).toLocaleString()}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
