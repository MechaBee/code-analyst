'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import React, { useEffect, useState } from 'react';

import { useApi } from '@/hooks/useApi';
import { useAuth } from '@/hooks/useAuth';
import { cn } from '@/lib/utils';
import type { RepositoryDefinition, Team } from '@/types/api';

import ConfirmDialog from './ConfirmDialog';
import NavBar from './NavBar';

type RepoAction = 'archive' | 'restore' | null;

export default function RepoSettings() {
  const params = useParams<{ repoDefId: string }>();
  const repoDefId = params.repoDefId;
  const { isAdmin, isLoading: authLoading } = useAuth();
  const api = useApi();

  const [repo, setRepo] = useState<RepositoryDefinition | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [name, setName] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [authKind, setAuthKind] = useState('public');
  const [newToken, setNewToken] = useState('');
  const [selectedTeamIds, setSelectedTeamIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionTarget, setActionTarget] = useState<RepoAction>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (authLoading || !isAdmin || !repoDefId) {
      setLoading(authLoading);
      return;
    }

    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const [repoResponse, teamResponse] = await Promise.all([
          api.getRepoDefinition(repoDefId),
          api.listTeams(),
        ]);

        if (cancelled) {
          return;
        }

        setRepo(repoResponse);
        setTeams(teamResponse.teams);
        setName(repoResponse.name || '');
        setEndpoint(repoResponse.endpoint);
        setAuthKind(repoResponse.adapter.auth_kind || 'public');
        setNewToken('');
        setSelectedTeamIds(repoResponse.team_ids);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load repository settings');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [api, authLoading, isAdmin, refreshKey, repoDefId]);

  const refresh = () => setRefreshKey((value) => value + 1);

  const toggleSelectedTeam = (teamId: string) => {
    setSelectedTeamIds((current) =>
      current.includes(teamId)
        ? current.filter((entry) => entry !== teamId)
        : [...current, teamId]
    );
  };

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!repo) {
      return;
    }

    if (authKind === 'token' && repo.adapter.auth_kind !== 'token' && !newToken.trim()) {
      setError('A new token is required when switching a public repository to token auth.');
      return;
    }

    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const adapter =
        authKind === 'public'
          ? { auth_kind: 'public' }
          : newToken.trim()
            ? {
                auth_kind: 'token',
                access_secret: { token: newToken.trim() },
              }
            : { auth_kind: 'token' };

      const updated = await api.updateRepoDefinition(repo.repo_def_id, {
        name: name.trim() ? name.trim() : null,
        endpoint: endpoint.trim(),
        team_ids: selectedTeamIds,
        adapter,
      });

      setRepo(updated);
      setName(updated.name || '');
      setEndpoint(updated.endpoint);
      setAuthKind(updated.adapter.auth_kind || 'public');
      setNewToken('');
      setSelectedTeamIds(updated.team_ids);
      setNotice('Repository settings saved.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save repository settings');
    } finally {
      setSaving(false);
    }
  };

  const handleRepoAction = async () => {
    if (!repo || !actionTarget) {
      return;
    }

    setActionLoading(true);
    setError(null);
    setNotice(null);
    try {
      const updated =
        actionTarget === 'archive'
          ? await api.archiveRepoDefinition(repo.repo_def_id)
          : await api.restoreRepoDefinition(repo.repo_def_id);

      setRepo(updated);
      setActionTarget(null);
      setNotice(
        actionTarget === 'archive'
          ? 'Repository archived. Existing conversations remain available.'
          : 'Repository restored to active lists.'
      );
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Repository update failed');
    } finally {
      setActionLoading(false);
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-screen bg-cream">
        <NavBar active="repos" />
        <div className="mx-auto max-w-5xl px-6 py-10 text-sm text-muted">Loading...</div>
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="min-h-screen bg-cream">
        <NavBar active="repos" />
        <div className="flex h-[calc(100vh-3rem)] items-center justify-center text-ink">
          <div className="text-center">
            <h1 className="text-xl font-semibold">Access Denied</h1>
            <p className="mt-2 text-sm text-muted">Admin privileges required.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-cream">
      <NavBar active="repos" />
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <Link href="/repos" className="text-sm font-medium text-accent hover:underline">
              Back to Repositories
            </Link>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-bold text-ink">
                {repo?.name || 'Repository Settings'}
              </h1>
              {repo?.archived_at && (
                <span className="rounded-full bg-red-50 px-2.5 py-1 text-xs font-medium text-red-700">
                  Archived
                </span>
              )}
            </div>
            <p className="mt-2 break-all text-sm text-muted">{repo?.endpoint || repoDefId}</p>
          </div>
        </div>

        {error && (
          <div className="mt-6 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
            {error}
          </div>
        )}

        {notice && (
          <div className="mt-6 rounded-lg bg-emerald-50 px-4 py-2 text-sm text-emerald-700">
            {notice}
          </div>
        )}

        {loading ? (
          <div className="mt-8 rounded-2xl border border-line bg-panel px-5 py-8 text-sm text-muted shadow-sm">
            Loading repository settings...
          </div>
        ) : repo ? (
          <div className="mt-8 grid gap-8 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,0.7fr)]">
            <form
              onSubmit={handleSave}
              className="space-y-6 rounded-2xl border border-line bg-panel p-6 shadow-sm"
            >
              <div>
                <h2 className="text-lg font-semibold text-ink">Repository Settings</h2>
                <p className="mt-1 text-sm text-muted">
                  Update the endpoint, authentication, and team access for this repository.
                </p>
              </div>

              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-medium text-ink">Display name</label>
                  <input
                    type="text"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    className={cn(
                      'w-full rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                      'focus:border-accent focus:ring-1 focus:ring-accent',
                      'border-line'
                    )}
                  />
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-ink">
                    Repository kind
                  </label>
                  <input
                    type="text"
                    value={repo.adapter.kind}
                    disabled
                    className="w-full rounded-lg border border-line bg-stone-100 px-3 py-2 text-sm text-muted"
                  />
                </div>

                <div className="sm:col-span-2">
                  <label className="mb-1 block text-xs font-medium text-ink">Endpoint URL</label>
                  <input
                    type="url"
                    required
                    value={endpoint}
                    onChange={(event) => setEndpoint(event.target.value)}
                    className={cn(
                      'w-full rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                      'focus:border-accent focus:ring-1 focus:ring-accent',
                      'border-line'
                    )}
                  />
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-ink">Access mode</label>
                  <select
                    value={authKind}
                    onChange={(event) => setAuthKind(event.target.value)}
                    className={cn(
                      'w-full rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                      'focus:border-accent focus:ring-1 focus:ring-accent',
                      'border-line'
                    )}
                  >
                    <option value="public">Public</option>
                    <option value="token">Private token</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-ink">Current auth</label>
                  <div className="rounded-lg border border-line bg-cream px-3 py-2 text-sm text-muted">
                    {repo.adapter.auth_kind === 'token' ? 'Token configured' : 'Public repository'}
                  </div>
                </div>

                {authKind === 'token' && (
                  <div className="sm:col-span-2">
                    <label className="mb-1 block text-xs font-medium text-ink">
                      New token
                    </label>
                    <input
                      type="password"
                      value={newToken}
                      onChange={(event) => setNewToken(event.target.value)}
                      placeholder="Leave blank to keep the existing token"
                      className={cn(
                        'w-full rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                        'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                        'border-line'
                      )}
                    />
                    <p className="mt-2 text-xs text-muted">
                      The existing token is never shown. A blank field preserves the current token.
                    </p>
                  </div>
                )}
              </div>

              <div>
                <label className="mb-2 block text-xs font-medium text-ink">Team access</label>
                {teams.length === 0 ? (
                  <p className="text-sm text-muted">No teams available.</p>
                ) : (
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {teams.map((team) => (
                      <label
                        key={team.team_id}
                        className="flex items-center gap-2 rounded-xl border border-line bg-cream px-3 py-2 text-sm text-ink"
                      >
                        <input
                          type="checkbox"
                          checked={selectedTeamIds.includes(team.team_id)}
                          onChange={() => toggleSelectedTeam(team.team_id)}
                        />
                        <span>{team.name}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>

              <button
                type="submit"
                disabled={saving || !endpoint.trim()}
                className={cn(
                  'rounded-lg px-4 py-2 text-sm font-semibold text-white transition',
                  saving || !endpoint.trim()
                    ? 'cursor-not-allowed bg-accent/60'
                    : 'bg-accent hover:bg-accent/90'
                )}
              >
                {saving ? 'Saving...' : 'Save settings'}
              </button>
            </form>

            <aside className="space-y-6">
              <section className="rounded-2xl border border-line bg-panel p-6 shadow-sm">
                <h2 className="text-lg font-semibold text-ink">Repository Details</h2>
                <dl className="mt-4 space-y-3 text-sm">
                  <div>
                    <dt className="text-muted">Repository ID</dt>
                    <dd className="mt-1 font-mono text-ink">{repo.repo_def_id}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Created</dt>
                    <dd className="mt-1 text-ink">
                      {new Date(repo.created_at).toLocaleString()}
                    </dd>
                  </div>
                  {repo.archived_at && (
                    <div>
                      <dt className="text-muted">Archived</dt>
                      <dd className="mt-1 text-ink">
                        {new Date(repo.archived_at).toLocaleString()}
                      </dd>
                    </div>
                  )}
                </dl>
              </section>

              <section className="rounded-2xl border border-red-200 bg-red-50 p-6 shadow-sm">
                <h2 className="text-lg font-semibold text-red-700">Danger Zone</h2>
                <p className="mt-2 text-sm text-red-700/80">
                  {repo.archived_at
                    ? 'Restore this repository to make it visible in normal repository lists again.'
                    : 'Archive this repository to hide it from normal lists while preserving existing conversations and snapshots.'}
                </p>
                <button
                  type="button"
                  onClick={() => setActionTarget(repo.archived_at ? 'restore' : 'archive')}
                  className={cn(
                    'mt-4 rounded-2xl px-4 py-2 text-sm font-semibold text-white transition',
                    repo.archived_at
                      ? 'bg-accent hover:bg-accent/90'
                      : 'bg-red-600 hover:bg-red-700'
                  )}
                >
                  {repo.archived_at ? 'Restore repository' : 'Archive repository'}
                </button>
              </section>
            </aside>
          </div>
        ) : (
          <div className="mt-8 rounded-2xl border border-line bg-panel px-5 py-8 text-sm text-muted shadow-sm">
            Repository not found.
          </div>
        )}
      </div>

      <ConfirmDialog
        open={actionTarget !== null}
        title={actionTarget === 'archive' ? 'Archive repository' : 'Restore repository'}
        message={
          actionTarget === 'archive'
            ? `Archive "${repo?.name || repo?.endpoint || repoDefId}"? Existing conversations and snapshots stay available, but the repository disappears from normal lists and new checkouts are blocked.`
            : `Restore "${repo?.name || repo?.endpoint || repoDefId}" to active repository lists?`
        }
        confirmLabel={actionTarget === 'archive' ? 'Archive repository' : 'Restore repository'}
        onConfirm={() => {
          void handleRepoAction();
        }}
        onCancel={() => setActionTarget(null)}
        destructive={actionTarget === 'archive'}
        isLoading={actionLoading}
      />
    </div>
  );
}
