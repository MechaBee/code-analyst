'use client';

import React, { useState, useEffect } from 'react';
import { useApi } from '@/hooks/useApi';
import { useAuth } from '@/hooks/useAuth';
import { cn } from '@/lib/utils';
import NavBar from './NavBar';
import type {
  RepositoryDefinition,
  RepositoryAdapterCreateRequest,
  Checkout,
} from '@/types/api';

export default function RepoManager() {
  const { isAdmin, isLoading: authLoading } = useAuth();
  const api = useApi();
  const [repos, setRepos] = useState<RepositoryDefinition[]>([]);
  const [checkoutsMap, setCheckoutsMap] = useState<Record<string, Checkout[]>>({});
  const [name, setName] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [repoKind, setRepoKind] = useState('github');
  const [authKind, setAuthKind] = useState('public');
  const [secretJson, setSecretJson] = useState('');
  const [teamIds, setTeamIds] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api
      .listRepoDefinitions()
      .then((res) => {
        setRepos(res.repo_definitions);
        // Load checkouts for each repo
        const promises = res.repo_definitions.map((repo) =>
          api.listCheckoutsForRepo(repo.repo_def_id).then((c) => ({
            repoDefId: repo.repo_def_id,
            checkouts: c.checkouts,
          }))
        );
        Promise.all(promises).then((results) => {
          const map: Record<string, Checkout[]> = {};
          results.forEach((r) => {
            map[r.repoDefId] = r.checkouts;
          });
          setCheckoutsMap(map);
        });
      })
      .catch((err: Error) => setError(err.message));
  }, [refreshKey, api]);

  const refresh = () => setRefreshKey((k) => k + 1);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      let accessSecret: Record<string, unknown> | null = null;
      if (authKind !== 'public') {
        const parsed = JSON.parse(secretJson);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          throw new Error('Secret JSON must be a JSON object.');
        }
        accessSecret = parsed as Record<string, unknown>;
      }

      const adapter: RepositoryAdapterCreateRequest = {
        kind: repoKind,
        auth_kind: authKind,
        access_secret: accessSecret,
      };
      await api.createRepoDefinition({
        name: name || null,
        endpoint,
        adapter,
        team_ids: teamIds
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
      });
      setName('');
      setEndpoint('');
      setRepoKind('github');
      setAuthKind('public');
      setSecretJson('');
      setTeamIds('');
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create repository');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-cream">
      <NavBar active="repos" />
      <div className="p-6">
      <div className="mx-auto max-w-4xl space-y-8">
        <h1 className="text-2xl font-bold text-ink">Repositories</h1>

        {error && (
          <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
            {error}
          </div>
        )}

        {isAdmin && !authLoading && (
          <form onSubmit={handleCreate} className="space-y-4 rounded-xl border border-line bg-panel p-5 shadow-sm">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">Add Repository</h2>
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
                <label className="mb-1 block text-xs font-medium text-ink">Repository Kind</label>
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
              <div>
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
              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Team IDs (comma-separated)</label>
                <input
                  type="text"
                  placeholder="team_01, team_02"
                  value={teamIds}
                  onChange={(e) => setTeamIds(e.target.value)}
                  className={cn(
                    'w-full rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                    'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                    'border-line'
                  )}
                />
              </div>
            </div>
            {authKind !== 'public' && (
              <div>
                <label className="mb-1 block text-xs font-medium text-ink">Access Secret JSON</label>
                <textarea
                  value={secretJson}
                  onChange={(e) => setSecretJson(e.target.value)}
                  rows={5}
                  placeholder={'{\n  "token": "ghp_example"\n}'}
                  className={cn(
                    'w-full rounded-lg border bg-cream px-3 py-2 font-mono text-sm text-ink outline-none',
                    'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                    'border-line'
                  )}
                />
              </div>
            )}
            <button
              type="submit"
              disabled={loading || !endpoint.trim() || (authKind !== 'public' && !secretJson.trim())}
              className={cn(
                'rounded-lg px-4 py-2 text-sm font-semibold text-white transition',
                loading || !endpoint.trim() || (authKind !== 'public' && !secretJson.trim())
                  ? 'cursor-not-allowed bg-accent/60'
                  : 'bg-accent hover:bg-accent/90'
              )}
            >
              {loading ? 'Saving…' : 'Add Repository'}
            </button>
          </form>
        )}

        {/* List */}
        <div className="space-y-4">
          {repos.map((repo) => (
            <RepoCard
              key={repo.repo_def_id}
              repo={repo}
              checkouts={checkoutsMap[repo.repo_def_id] || []}
              onCheckoutCreated={refresh}
            />
          ))}
          {repos.length === 0 && (
            <p className="text-sm text-muted">No repositories yet.</p>
          )}
        </div>
      </div>
    </div>
    </div>
  );
}

function RepoCard({
  repo,
  checkouts,
  onCheckoutCreated,
}: {
  repo: RepositoryDefinition;
  checkouts: Checkout[];
  onCheckoutCreated: () => void;
}) {
  const api = useApi();
  const [ref, setRef] = useState('main');
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);

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
    <div className="rounded-xl border border-line bg-panel p-4 shadow-sm">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-medium text-ink">{repo.name || 'Unnamed'}</div>
          <div className="text-xs text-muted">{repo.endpoint}</div>
          <div className="mt-1 text-xs text-muted">Teams: {repo.team_ids.join(', ') || 'none'}</div>
        </div>
        <div className="rounded-md bg-cream px-2 py-1 text-xs font-medium text-ink">
          {repo.adapter.kind} / {repo.adapter.auth_kind}
        </div>
      </div>

      {/* Checkout trigger */}
      <div className="mt-4 flex items-center gap-2">
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
          onClick={handleCheckout}
          disabled={checkoutLoading}
          className={cn(
            'rounded-lg px-3 py-1.5 text-sm font-semibold text-white transition',
            checkoutLoading ? 'cursor-not-allowed bg-accent/60' : 'bg-accent hover:bg-accent/90'
          )}
        >
          {checkoutLoading ? 'Checking out…' : 'Checkout'}
        </button>
      </div>
      {checkoutError && (
        <div className="mt-2 text-xs text-red-600">{checkoutError}</div>
      )}

      {/* Checkout list */}
      {checkouts.length > 0 && (
        <div className="mt-4 space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">Checkouts</h4>
          {checkouts.map((chk) => (
            <div
              key={chk.checkout_id}
              className="flex items-center justify-between rounded-lg bg-cream px-3 py-2"
            >
              <div className="text-xs text-ink">
                {chk.branch} @ {chk.commit_sha.slice(0, 8)}
              </div>
              <div className="text-xs text-muted">
                {new Date(chk.run_timestamp).toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
