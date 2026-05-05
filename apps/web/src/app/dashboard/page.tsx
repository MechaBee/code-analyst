'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';
import { useApi } from '@/hooks/useApi';
import { useAppState } from '@/hooks/useAppState';
import NavBar from '@/components/NavBar';
import ConversationList from '@/components/ConversationList';
import type { RepositoryDefinition, ConversationHead, Checkout } from '@/types/api';

export default function DashboardPage() {
  const router = useRouter();
  const { email, isAuthenticated, isLoading: authLoading } = useAuth();
  const api = useApi();
  const { setConversationContext, setWorkspace } = useAppState();

  const [repos, setRepos] = useState<RepositoryDefinition[]>([]);
  const [conversations, setConversations] = useState<ConversationHead[]>([]);
  const [checkouts, setCheckouts] = useState<Checkout[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string | null>(null);
  const [selectedCheckout, setSelectedCheckout] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!isAuthenticated) {
      setLoading(false);
      return;
    }

    async function load() {
      try {
        const [repoRes, convRes] = await Promise.all([
          api.listRepoDefinitions(),
          api.listConversations(),
        ]);
        setRepos(repoRes.repo_definitions);
        setConversations(convRes.conversations);

        // Load checkouts for all repos
        const checkoutLists = await Promise.all(
          repoRes.repo_definitions.map((r) => api.listCheckoutsForRepo(r.repo_def_id))
        );
        const allCheckouts = checkoutLists.flatMap((c) => c.checkouts);
        setCheckouts(allCheckouts);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load dashboard');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [api, isAuthenticated]);

  const repoNames = React.useMemo(() => {
    return repos.reduce<Record<string, string>>((acc, r) => {
      acc[r.repo_def_id] = r.name || r.endpoint;
      return acc;
    }, {});
  }, [repos]);

  const selectedRepoCheckouts = React.useMemo(
    () => checkouts.filter((c) => c.repo_def_id === selectedRepo),
    [checkouts, selectedRepo]
  );

  const handleSelectConversation = (conv: ConversationHead) => {
    if (!conv.workspace_id || !conv.latest_snapshot_id) return;
    setConversationContext(conv.conversation_id, conv.repo_def_id || undefined, conv.checkout_id || undefined);
    setWorkspace(conv.workspace_id, conv.latest_snapshot_id);
    router.push(`/chat/${conv.conversation_id}`);
  };

  const handleCreateConversation = async () => {
    if (!selectedRepo) return;
    const checkout = selectedCheckout
      ? checkouts.find((c) => c.checkout_id === selectedCheckout)
      : selectedRepoCheckouts[0];
    if (!checkout) {
      setError('Create a checkout for this repository first.');
      return;
    }

    setCreating(true);
    setError(null);

    const tenantId = process.env.NEXT_PUBLIC_TENANT_ID || 'tenant_local';

    try {
      const res = await api.createConversation({
        tenant_id: tenantId,
        repo_def_id: selectedRepo,
        checkout_id: checkout?.checkout_id || null,
        workspace_id: checkout?.workspace_id || null,
        title: title || undefined,
      });

      const workspaceId = checkout?.workspace_id || '';
      const snapshotId = checkout?.snapshot_id || '';
      setConversationContext(res.conversation_id, selectedRepo, selectedCheckout || undefined);
      if (workspaceId && snapshotId) {
        setWorkspace(workspaceId, snapshotId);
      }
      router.push(`/chat/${res.conversation_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create conversation');
    } finally {
      setCreating(false);
    }
  };

  if (authLoading || loading) {
    return (
      <div className="min-h-screen bg-cream">
        <NavBar active="dashboard" />
        <div className="mx-auto max-w-6xl px-6 py-10 text-sm text-muted">Loading…</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-cream">
        <NavBar active="dashboard" />
        <div className="mx-auto max-w-2xl px-6 py-16">
          <div className="rounded-3xl border border-line bg-panel p-8 text-center shadow-sm">
            <h1 className="text-2xl font-semibold text-ink">Access Link Required</h1>
            <p className="mt-3 text-sm text-muted">
              Ask your admin to send you a registration or sign-in link.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-cream">
      <NavBar active="dashboard" />
      <div className="mx-auto flex max-w-6xl gap-6 px-6 py-8">
        {/* Sidebar */}
        <aside className="w-64 shrink-0 space-y-6">
          <div>
            <h3 className="mb-2 text-sm font-semibold text-ink">Repositories</h3>
            <div className="space-y-1">
              {repos.map((repo) => (
                <button
                  key={repo.repo_def_id}
                  onClick={() => {
                    setSelectedRepo(repo.repo_def_id);
                    const repoCheckouts = checkouts.filter((c) => c.repo_def_id === repo.repo_def_id);
                    setSelectedCheckout(repoCheckouts[0]?.checkout_id || null);
                  }}
                  className={`w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                    selectedRepo === repo.repo_def_id
                      ? 'bg-panel font-medium text-accent'
                      : 'text-ink hover:bg-panel'
                  }`}
                >
                  {repo.name || repo.endpoint}
                </button>
              ))}
              {repos.length === 0 && (
                <p className="px-3 text-xs text-muted">
                  No repos.{' '}
                  <a href="/repos" className="text-accent underline">
                    Add one
                  </a>
                </p>
              )}
            </div>
          </div>

          <div>
            <h3 className="mb-2 text-sm font-semibold text-ink">New Conversation</h3>
            <div className="space-y-2">
              <select
                value={selectedRepo || ''}
                onChange={(e) => {
                  const nextRepoId = e.target.value || null;
                  setSelectedRepo(nextRepoId);
                  const repoCheckouts = checkouts.filter((c) => c.repo_def_id === nextRepoId);
                  setSelectedCheckout(repoCheckouts[0]?.checkout_id || null);
                }}
                className="w-full rounded-lg border border-line bg-cream px-3 py-2 text-sm text-ink outline-none focus:border-accent"
              >
                <option value="">Select repository</option>
                {repos.map((r) => (
                  <option key={r.repo_def_id} value={r.repo_def_id}>
                    {r.name || r.endpoint}
                  </option>
                ))}
              </select>

              {selectedRepo && (
                <select
                  value={selectedCheckout || ''}
                  onChange={(e) => setSelectedCheckout(e.target.value || null)}
                  className="w-full rounded-lg border border-line bg-cream px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                >
                  <option value="">Select checkout</option>
                  {selectedRepoCheckouts.map((c) => (
                      <option key={c.checkout_id} value={c.checkout_id}>
                        {c.branch} @ {c.commit_sha.slice(0, 7)}
                      </option>
                    ))}
                </select>
              )}

              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Conversation title (optional)"
                className="w-full rounded-lg border border-line bg-cream px-3 py-2 text-sm text-ink outline-none focus:border-accent"
              />

              <button
                onClick={handleCreateConversation}
                disabled={!selectedRepo || creating || selectedRepoCheckouts.length === 0}
                className="w-full rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {creating ? 'Creating…' : 'Start conversation'}
              </button>
              {error && <p className="text-xs text-red-600">{error}</p>}
            </div>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1">
          <h2 className="mb-4 text-lg font-semibold text-ink">Recent conversations</h2>
          <ConversationList
            conversations={conversations}
            repoNames={repoNames}
            onSelect={handleSelectConversation}
          />
        </main>
      </div>
    </div>
  );
}
