'use client';

import Link from 'next/link';
import React, { useEffect, useMemo, useState } from 'react';

import { useApi } from '@/hooks/useApi';
import { useAuth } from '@/hooks/useAuth';
import { cn } from '@/lib/utils';
import type {
  Checkout,
  RepositoryAdapterCreateRequest,
  RepositoryDefinition,
  Team,
} from '@/types/api';

import ConfirmDialog from './ConfirmDialog';
import NavBar from './NavBar';

type RepoActionTarget =
  | {
      action: 'archive' | 'restore';
      repo: RepositoryDefinition;
    }
  | null;

export default function RepoManager() {
  const { isAdmin, isAuthenticated, isLoading: authLoading } = useAuth();
  const api = useApi();

  const [repos, setRepos] = useState<RepositoryDefinition[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [checkoutsMap, setCheckoutsMap] = useState<Record<string, Checkout[]>>({});
  const [name, setName] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [repoKind, setRepoKind] = useState('github');
  const [authKind, setAuthKind] = useState('public');
  const [token, setToken] = useState('');
  const [selectedTeamIds, setSelectedTeamIds] = useState<string[]>([]);
  const [pageLoading, setPageLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [showArchived, setShowArchived] = useState(false);
  const [actionTarget, setActionTarget] = useState<RepoActionTarget>(null);
  const [actionLoading, setActionLoading] = useState(false);

  useEffect(() => {
    if (authLoading) {
      return;
    }
    if (!isAuthenticated) {
      setPageLoading(false);
      return;
    }

    let cancelled = false;

    async function load() {
      setPageLoading(true);
      try {
        const repoResponse = isAdmin
          ? await api.listAdminRepoDefinitions(true)
          : await api.listRepoDefinitions();
        const repoDefinitions = repoResponse.repo_definitions;
        const activeRepos = repoDefinitions.filter((repo) => repo.archived_at == null);

        const checkoutPromises = activeRepos.map((repo) =>
          api.listCheckoutsForRepo(repo.repo_def_id).then((checkoutResponse) => ({
            repoDefId: repo.repo_def_id,
            checkouts: checkoutResponse.checkouts,
          }))
        );

        const [checkoutResults, teamResponse] = await Promise.all([
          Promise.all(checkoutPromises),
          isAdmin ? api.listTeams() : Promise.resolve(null),
        ]);

        if (cancelled) {
          return;
        }

        const nextCheckoutsMap: Record<string, Checkout[]> = {};
        checkoutResults.forEach((result) => {
          nextCheckoutsMap[result.repoDefId] = result.checkouts;
        });

        setRepos(repoDefinitions);
        setTeams(teamResponse?.teams || []);
        setCheckoutsMap(nextCheckoutsMap);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load repositories');
        }
      } finally {
        if (!cancelled) {
          setPageLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [api, authLoading, isAdmin, isAuthenticated, refreshKey]);

  if (!authLoading && !isAuthenticated) {
    return (
      <div className="min-h-screen bg-cream">
        <NavBar active="repos" />
        <div className="mx-auto max-w-2xl px-6 py-16">
          <div className="rounded-3xl border border-line bg-panel p-8 text-center shadow-sm">
            <h1 className="text-2xl font-semibold text-ink">Sign-In Required</h1>
            <p className="mt-3 text-sm text-muted">
              Use a registration or sign-in link to view repositories.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const refresh = () => setRefreshKey((value) => value + 1);

  const teamNamesById = useMemo(() => {
    return teams.reduce<Record<string, string>>((accumulator, team) => {
      accumulator[team.team_id] = team.name;
      return accumulator;
    }, {});
  }, [teams]);

  const activeRepos = repos.filter((repo) => repo.archived_at == null);
  const archivedRepos = repos.filter((repo) => repo.archived_at != null);

  const toggleSelectedTeam = (teamId: string) => {
    setSelectedTeamIds((current) =>
      current.includes(teamId)
        ? current.filter((entry) => entry !== teamId)
        : [...current, teamId]
    );
  };

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    setCreating(true);
    setError(null);
    try {
      const adapter: RepositoryAdapterCreateRequest = {
        kind: repoKind,
        auth_kind: authKind,
        access_secret: authKind === 'token' ? { token } : null,
      };

      await api.createRepoDefinition({
        name: name || null,
        endpoint,
        adapter,
        team_ids: selectedTeamIds,
      });

      setName('');
      setEndpoint('');
      setRepoKind('github');
      setAuthKind('public');
      setToken('');
      setSelectedTeamIds([]);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create repository');
    } finally {
      setCreating(false);
    }
  };

  const handleConfirmAction = async () => {
    if (!actionTarget) {
      return;
    }

    setActionLoading(true);
    setError(null);
    try {
      if (actionTarget.action === 'archive') {
        await api.archiveRepoDefinition(actionTarget.repo.repo_def_id);
      } else {
        await api.restoreRepoDefinition(actionTarget.repo.repo_def_id);
      }
      setActionTarget(null);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Repository update failed');
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-cream">
      <NavBar active="repos" />
      <div className="p-6">
        <div className="mx-auto max-w-5xl space-y-8">
          <div className="flex items-end justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-ink">Repositories</h1>
              <p className="mt-1 text-sm text-muted">
                {isAdmin
                  ? 'Manage repository settings, access, and archive state.'
                  : 'Browse repositories you can analyze.'}
              </p>
            </div>
            {isAdmin && archivedRepos.length > 0 && (
              <button
                type="button"
                onClick={() => setShowArchived((current) => !current)}
                className="rounded-2xl border border-line bg-panel px-4 py-2 text-sm font-medium text-ink transition hover:border-accent/20 hover:text-accent"
              >
                {showArchived ? 'Hide archived' : `Show archived (${archivedRepos.length})`}
              </button>
            )}
          </div>

          {error && (
            <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
              {error}
            </div>
          )}

          {isAdmin && !authLoading && (
            <form
              onSubmit={handleCreate}
              className="space-y-5 rounded-2xl border border-line bg-panel p-5 shadow-sm"
            >
              <div>
                <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
                  Add Repository
                </h2>
                <p className="mt-1 text-sm text-muted">
                  Create a repository definition and grant initial team access.
                </p>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-xs font-medium text-ink">Name</label>
                  <input
                    type="text"
                    placeholder="My Project"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className={cn(
                      'w-full rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                      'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                      'border-line'
                    )}
                  />
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-ink">
                    Repository Kind
                  </label>
                  <select
                    value={repoKind}
                    onChange={(e) => setRepoKind(e.target.value)}
                    className={cn(
                      'w-full rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                      'focus:border-accent focus:ring-1 focus:ring-accent',
                      'border-line'
                    )}
                  >
                    <option value="github">GitHub</option>
                  </select>
                </div>

                <div className="sm:col-span-2">
                  <label className="mb-1 block text-xs font-medium text-ink">Endpoint URL</label>
                  <input
                    type="url"
                    required
                    placeholder="https://github.com/owner/repo.git"
                    value={endpoint}
                    onChange={(e) => setEndpoint(e.target.value)}
                    className={cn(
                      'w-full rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                      'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                      'border-line'
                    )}
                  />
                </div>

                <div>
                  <label className="mb-1 block text-xs font-medium text-ink">Access Mode</label>
                  <select
                    value={authKind}
                    onChange={(e) => setAuthKind(e.target.value)}
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

                {authKind === 'token' && (
                  <div>
                    <label className="mb-1 block text-xs font-medium text-ink">Token</label>
                    <input
                      type="password"
                      value={token}
                      onChange={(e) => setToken(e.target.value)}
                      placeholder="ghp_example"
                      className={cn(
                        'w-full rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                        'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                        'border-line'
                      )}
                    />
                  </div>
                )}
              </div>

              <div>
                <label className="mb-2 block text-xs font-medium text-ink">Team Access</label>
                {teams.length === 0 ? (
                  <p className="text-sm text-muted">
                    No teams available yet. You can still create the repository and assign teams
                    later.
                  </p>
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
                disabled={creating || !endpoint.trim() || (authKind === 'token' && !token.trim())}
                className={cn(
                  'rounded-lg px-4 py-2 text-sm font-semibold text-white transition',
                  creating || !endpoint.trim() || (authKind === 'token' && !token.trim())
                    ? 'cursor-not-allowed bg-accent/60'
                    : 'bg-accent hover:bg-accent/90'
                )}
              >
                {creating ? 'Saving...' : 'Add Repository'}
              </button>
            </form>
          )}

          {pageLoading ? (
            <div className="rounded-2xl border border-line bg-panel px-5 py-8 text-sm text-muted shadow-sm">
              Loading repositories...
            </div>
          ) : (
            <>
              <RepoSection
                title="Active Repositories"
                emptyMessage="No active repositories yet."
                repos={activeRepos}
                checkoutsMap={checkoutsMap}
                isAdmin={isAdmin}
                teamNamesById={teamNamesById}
                onArchive={(repo) => setActionTarget({ action: 'archive', repo })}
                onRestore={(repo) => setActionTarget({ action: 'restore', repo })}
                onCheckoutCreated={refresh}
              />

              {isAdmin && showArchived && (
                <RepoSection
                  title="Archived Repositories"
                  emptyMessage="No archived repositories."
                  repos={archivedRepos}
                  checkoutsMap={checkoutsMap}
                  isAdmin
                  teamNamesById={teamNamesById}
                  onArchive={(repo) => setActionTarget({ action: 'archive', repo })}
                  onRestore={(repo) => setActionTarget({ action: 'restore', repo })}
                  onCheckoutCreated={refresh}
                />
              )}
            </>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={Boolean(actionTarget)}
        title={actionTarget?.action === 'archive' ? 'Archive repository' : 'Restore repository'}
        message={
          actionTarget?.action === 'archive'
            ? `Archive "${actionTarget.repo.name || actionTarget.repo.endpoint}"? Existing conversations and snapshots stay available, but the repository will disappear from normal lists and new checkouts will be blocked.`
            : `Restore "${actionTarget?.repo.name || actionTarget?.repo.endpoint}" to active repository lists?`
        }
        confirmLabel={actionTarget?.action === 'archive' ? 'Archive repository' : 'Restore repository'}
        onConfirm={() => {
          void handleConfirmAction();
        }}
        onCancel={() => setActionTarget(null)}
        destructive={actionTarget?.action === 'archive'}
        isLoading={actionLoading}
      />
    </div>
  );
}

function RepoSection({
  title,
  emptyMessage,
  repos,
  checkoutsMap,
  isAdmin,
  teamNamesById,
  onArchive,
  onRestore,
  onCheckoutCreated,
}: {
  title: string;
  emptyMessage: string;
  repos: RepositoryDefinition[];
  checkoutsMap: Record<string, Checkout[]>;
  isAdmin: boolean;
  teamNamesById: Record<string, string>;
  onArchive: (repo: RepositoryDefinition) => void;
  onRestore: (repo: RepositoryDefinition) => void;
  onCheckoutCreated: () => void;
}) {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        <div className="rounded-full bg-panel px-3 py-1 text-xs font-semibold uppercase tracking-wide text-muted">
          {repos.length}
        </div>
      </div>

      <div className="space-y-4">
        {repos.map((repo) => (
          <RepoCard
            key={repo.repo_def_id}
            repo={repo}
            checkouts={checkoutsMap[repo.repo_def_id] || []}
            isAdmin={isAdmin}
            teamNamesById={teamNamesById}
            onArchive={onArchive}
            onRestore={onRestore}
            onCheckoutCreated={onCheckoutCreated}
          />
        ))}
        {repos.length === 0 && <p className="text-sm text-muted">{emptyMessage}</p>}
      </div>
    </section>
  );
}

function RepoCard({
  repo,
  checkouts,
  isAdmin,
  teamNamesById,
  onArchive,
  onRestore,
  onCheckoutCreated,
}: {
  repo: RepositoryDefinition;
  checkouts: Checkout[];
  isAdmin: boolean;
  teamNamesById: Record<string, string>;
  onArchive: (repo: RepositoryDefinition) => void;
  onRestore: (repo: RepositoryDefinition) => void;
  onCheckoutCreated: () => void;
}) {
  const api = useApi();
  const [ref, setRef] = useState('main');
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);

  const isArchived = repo.archived_at != null;
  const teamLabels = repo.team_ids.map((teamId) => teamNamesById[teamId] || teamId);

  const handleCheckout = async () => {
    setCheckoutLoading(true);
    setCheckoutError(null);
    try {
      await api.createCheckout(repo.repo_def_id, { repo_def_id: repo.repo_def_id, ref });
      setRef('main');
      onCheckoutCreated();
    } catch (err) {
      setCheckoutError(err instanceof Error ? err.message : 'Checkout failed');
    } finally {
      setCheckoutLoading(false);
    }
  };

  return (
    <article className="rounded-2xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-lg font-semibold text-ink">
              {repo.name || 'Unnamed repository'}
            </h3>
            <span className="rounded-full bg-cream px-2.5 py-1 text-xs font-medium text-muted">
              {repo.adapter.kind} / {repo.adapter.auth_kind}
            </span>
            {isArchived && (
              <span className="rounded-full bg-red-50 px-2.5 py-1 text-xs font-medium text-red-700">
                Archived
              </span>
            )}
          </div>

          <div className="mt-2 break-all text-sm text-muted">{repo.endpoint}</div>
          <div className="mt-3 grid gap-2 text-xs text-muted sm:grid-cols-2">
            <div>Repo ID: {repo.repo_def_id}</div>
            <div>Teams: {teamLabels.join(', ') || 'none'}</div>
            {isArchived && repo.archived_at && (
              <div>Archived: {new Date(repo.archived_at).toLocaleString()}</div>
            )}
          </div>
        </div>

        {isAdmin && (
          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
            <Link
              href={`/repos/${repo.repo_def_id}`}
              className="rounded-2xl border border-line bg-cream px-3 py-2 text-sm font-medium text-ink transition hover:border-accent/20 hover:text-accent"
            >
              {isArchived ? 'View settings' : 'Edit'}
            </Link>
            {isArchived ? (
              <button
                type="button"
                onClick={() => onRestore(repo)}
                className="rounded-2xl border border-line bg-cream px-3 py-2 text-sm font-medium text-ink transition hover:border-accent/20 hover:text-accent"
              >
                Restore
              </button>
            ) : (
              <button
                type="button"
                onClick={() => onArchive(repo)}
                className="rounded-2xl border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-100"
              >
                Archive
              </button>
            )}
          </div>
        )}
      </div>

      {!isArchived && (
        <>
          <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:items-center">
            <input
              type="text"
              placeholder="Branch or ref"
              value={ref}
              onChange={(e) => setRef(e.target.value)}
              className={cn(
                'flex-1 rounded-lg border bg-cream px-3 py-1.5 text-sm text-ink outline-none',
                'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                'border-line'
              )}
            />
            <button
              type="button"
              onClick={() => {
                void handleCheckout();
              }}
              disabled={checkoutLoading}
              className={cn(
                'rounded-lg px-3 py-1.5 text-sm font-semibold text-white transition',
                checkoutLoading ? 'cursor-not-allowed bg-accent/60' : 'bg-accent hover:bg-accent/90'
              )}
            >
              {checkoutLoading ? 'Checking out...' : 'Checkout'}
            </button>
          </div>

          {checkoutError && <div className="mt-2 text-xs text-red-600">{checkoutError}</div>}

          {checkouts.length > 0 && (
            <div className="mt-4 space-y-2">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
                Checkouts
              </h4>
              {checkouts.map((checkout) => (
                <div
                  key={checkout.checkout_id}
                  className="flex items-center justify-between rounded-lg bg-cream px-3 py-2"
                >
                  <div className="text-xs text-ink">
                    {checkout.branch} @ {checkout.commit_sha.slice(0, 8)}
                  </div>
                  <div className="text-xs text-muted">
                    {new Date(checkout.run_timestamp).toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </article>
  );
}
