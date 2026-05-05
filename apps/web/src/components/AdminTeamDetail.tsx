'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import React, { useEffect, useMemo, useState } from 'react';

import { useApi } from '@/hooks/useApi';
import { useAuth } from '@/hooks/useAuth';
import { cn } from '@/lib/utils';
import type { RepositoryDefinition, TeamDetailResponse, User } from '@/types/api';

import NavBar from './NavBar';

export default function AdminTeamDetail() {
  const params = useParams<{ teamId: string }>();
  const teamId = params.teamId;
  const { isAdmin, isAuthenticated, email, isLoading: authLoading } = useAuth();
  const api = useApi();

  const [detail, setDetail] = useState<TeamDetailResponse | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [allRepos, setAllRepos] = useState<RepositoryDefinition[]>([]);
  const [selectedUserEmail, setSelectedUserEmail] = useState('');
  const [selectedRepoId, setSelectedRepoId] = useState('');
  const [loading, setLoading] = useState(true);
  const [addingMember, setAddingMember] = useState(false);
  const [removingMemberEmail, setRemovingMemberEmail] = useState<string | null>(null);
  const [addingRepo, setAddingRepo] = useState(false);
  const [removingRepoId, setRemovingRepoId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!isAuthenticated || !isAdmin || !teamId) {
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const [teamResponse, userResponse, repoResponse] = await Promise.all([
          api.getAdminTeamDetail(teamId),
          api.listUsers(),
          api.listAdminRepoDefinitions(),
        ]);

        if (cancelled) return;
        setDetail(teamResponse);
        setUsers(userResponse.users);
        setAllRepos(repoResponse.repo_definitions);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load team detail');
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
  }, [api, isAdmin, isAuthenticated, refreshKey, teamId]);

  const refresh = () => setRefreshKey((value) => value + 1);

  const memberEmails = useMemo(
    () => new Set(detail?.members.map((member) => member.user_email) || []),
    [detail]
  );

  const availableUsers = useMemo(
    () => users.filter((user) => !memberEmails.has(user.email)),
    [memberEmails, users]
  );

  const teamRepoIds = useMemo(
    () => new Set(detail?.repositories.map((repository) => repository.repo_def_id) || []),
    [detail]
  );

  const availableRepos = useMemo(
    () => allRepos.filter((repository) => !teamRepoIds.has(repository.repo_def_id)),
    [allRepos, teamRepoIds]
  );

  useEffect(() => {
    if (!selectedUserEmail && availableUsers.length > 0) {
      setSelectedUserEmail(availableUsers[0].email);
    }
    if (selectedUserEmail && !availableUsers.some((user) => user.email === selectedUserEmail)) {
      setSelectedUserEmail(availableUsers[0]?.email || '');
    }
  }, [availableUsers, selectedUserEmail]);

  useEffect(() => {
    if (!selectedRepoId && availableRepos.length > 0) {
      setSelectedRepoId(availableRepos[0].repo_def_id);
    }
    if (
      selectedRepoId &&
      !availableRepos.some((repository) => repository.repo_def_id === selectedRepoId)
    ) {
      setSelectedRepoId(availableRepos[0]?.repo_def_id || '');
    }
  }, [availableRepos, selectedRepoId]);

  const handleAddMember = async () => {
    if (!teamId || !selectedUserEmail) return;
    setAddingMember(true);
    setError(null);
    try {
      await api.addTeamMember(teamId, { user_email: selectedUserEmail });
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add team member');
    } finally {
      setAddingMember(false);
    }
  };

  const handleRemoveMember = async (userEmail: string) => {
    if (!teamId) return;
    setRemovingMemberEmail(userEmail);
    setError(null);
    try {
      await api.removeTeamMember(teamId, userEmail);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove team member');
    } finally {
      setRemovingMemberEmail(null);
    }
  };

  const handleAddRepository = async () => {
    if (!detail || !selectedRepoId) return;
    const repository = allRepos.find((entry) => entry.repo_def_id === selectedRepoId);
    if (!repository) return;

    setAddingRepo(true);
    setError(null);
    try {
      await api.updateRepoDefinitionTeams(repository.repo_def_id, {
        team_ids: Array.from(new Set([...repository.team_ids, detail.team.team_id])),
      });
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update repository access');
    } finally {
      setAddingRepo(false);
    }
  };

  const handleRemoveRepository = async (repository: RepositoryDefinition) => {
    if (!detail) return;
    setRemovingRepoId(repository.repo_def_id);
    setError(null);
    try {
      await api.updateRepoDefinitionTeams(repository.repo_def_id, {
        team_ids: repository.team_ids.filter((entry) => entry !== detail.team.team_id),
      });
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove repository access');
    } finally {
      setRemovingRepoId(null);
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-screen bg-cream">
        <NavBar active="admin" />
        <div className="mx-auto max-w-6xl px-6 py-10 text-sm text-muted">Loading…</div>
      </div>
    );
  }

  if (!isAdmin) {
    if (!isAuthenticated) {
      return (
        <div className="min-h-screen bg-cream">
          <NavBar active="admin" />
          <div className="mx-auto max-w-2xl px-6 py-16">
            <div className="rounded-3xl border border-line bg-panel p-8 text-center shadow-sm">
              <h1 className="text-2xl font-semibold text-ink">Sign-In Required</h1>
              <p className="mt-3 text-sm text-muted">
                Use an admin access link to manage team membership.
              </p>
            </div>
          </div>
        </div>
      );
    }
    return (
      <div className="min-h-screen bg-cream">
        <NavBar active="admin" />
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
      <NavBar active="admin" />
      <div className="mx-auto max-w-6xl px-6 py-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <Link href="/admin" className="text-sm font-medium text-accent hover:underline">
              Back to Admin
            </Link>
            <h1 className="mt-3 text-2xl font-bold text-ink">
              {detail?.team.name || 'Team'}
            </h1>
            <div className="mt-1 font-mono text-xs text-muted">{detail?.team.team_id || teamId}</div>
          </div>
          <div className="text-sm text-muted">{email}</div>
        </div>

        {error && (
          <div className="mt-6 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
            {error}
          </div>
        )}

        {loading ? (
          <div className="mt-8 text-sm text-muted">Loading team details…</div>
        ) : detail ? (
          <div className="mt-8 grid gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <section className="space-y-5">
              <div className="rounded-2xl border border-line bg-panel p-5 shadow-sm">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-lg font-semibold text-ink">Repository Access</h2>
                    <p className="mt-1 text-sm text-muted">Attach repositories that this team can use.</p>
                  </div>
                  <div className="rounded-full bg-cream px-3 py-1 text-xs font-semibold uppercase tracking-wide text-muted">
                    {detail.repositories.length} assigned
                  </div>
                </div>

                <div className="mt-5 flex flex-col gap-3 md:flex-row">
                  <select
                    value={selectedRepoId}
                    onChange={(event) => setSelectedRepoId(event.target.value)}
                    disabled={availableRepos.length === 0}
                    className={cn(
                      'flex-1 rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                      'focus:border-accent focus:ring-1 focus:ring-accent',
                      'border-line disabled:cursor-not-allowed disabled:text-muted'
                    )}
                  >
                    {availableRepos.length === 0 ? (
                      <option value="">All repositories already assigned</option>
                    ) : (
                      availableRepos.map((repository) => (
                        <option key={repository.repo_def_id} value={repository.repo_def_id}>
                          {repository.name || repository.endpoint}
                        </option>
                      ))
                    )}
                  </select>
                  <button
                    onClick={handleAddRepository}
                    disabled={addingRepo || !selectedRepoId}
                    className={cn(
                      'rounded-lg px-4 py-2 text-sm font-semibold text-white transition',
                      addingRepo || !selectedRepoId
                        ? 'cursor-not-allowed bg-accent/60'
                        : 'bg-accent hover:bg-accent/90'
                    )}
                  >
                    {addingRepo ? 'Adding…' : 'Add Repository'}
                  </button>
                </div>
              </div>

              <div className="space-y-4">
                {detail.repositories.map((repository) => (
                  <article
                    key={repository.repo_def_id}
                    className="rounded-2xl border border-line bg-panel p-5 shadow-sm"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h3 className="truncate text-base font-semibold text-ink">
                          {repository.name || 'Unnamed Repository'}
                        </h3>
                        <div className="mt-1 break-all text-xs text-muted">{repository.endpoint}</div>
                        <div className="mt-2 font-mono text-xs text-muted">{repository.repo_def_id}</div>
                      </div>
                      <button
                        onClick={() => handleRemoveRepository(repository)}
                        disabled={removingRepoId === repository.repo_def_id}
                        className="rounded-lg border border-line px-3 py-1.5 text-sm font-semibold text-ink transition hover:border-red-300 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {removingRepoId === repository.repo_def_id ? 'Removing…' : 'Remove'}
                      </button>
                    </div>
                  </article>
                ))}
              </div>

              {detail.repositories.length === 0 && (
                <p className="text-sm text-muted">This team has no repository access yet.</p>
              )}
            </section>

            <section className="space-y-5">
              <div className="rounded-2xl border border-line bg-panel p-5 shadow-sm">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-lg font-semibold text-ink">Team Members</h2>
                    <p className="mt-1 text-sm text-muted">Add existing users to this team.</p>
                  </div>
                  <div className="rounded-full bg-cream px-3 py-1 text-xs font-semibold uppercase tracking-wide text-muted">
                    {detail.members.length} members
                  </div>
                </div>

                <div className="mt-5 flex flex-col gap-3 md:flex-row">
                  <select
                    value={selectedUserEmail}
                    onChange={(event) => setSelectedUserEmail(event.target.value)}
                    disabled={availableUsers.length === 0}
                    className={cn(
                      'flex-1 rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                      'focus:border-accent focus:ring-1 focus:ring-accent',
                      'border-line disabled:cursor-not-allowed disabled:text-muted'
                    )}
                  >
                    {availableUsers.length === 0 ? (
                      <option value="">All users are already members</option>
                    ) : (
                      availableUsers.map((user) => (
                        <option key={user.email} value={user.email}>
                          {user.email}
                          {user.name ? ` — ${user.name}` : ''}
                        </option>
                      ))
                    )}
                  </select>
                  <button
                    onClick={handleAddMember}
                    disabled={addingMember || !selectedUserEmail}
                    className={cn(
                      'rounded-lg px-4 py-2 text-sm font-semibold text-white transition',
                      addingMember || !selectedUserEmail
                        ? 'cursor-not-allowed bg-accent/60'
                        : 'bg-accent hover:bg-accent/90'
                    )}
                  >
                    {addingMember ? 'Adding…' : 'Add Member'}
                  </button>
                </div>
              </div>

              <div className="overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
                <div className="border-b border-line px-5 py-4">
                  <h3 className="text-base font-semibold text-ink">Current Members</h3>
                </div>

                <div className="divide-y divide-line">
                  {detail.members.map((member) => (
                    <div
                      key={member.user_email}
                      className="flex flex-wrap items-center justify-between gap-3 px-5 py-4"
                    >
                      <div className="min-w-0">
                        <div className="font-mono text-xs text-ink">{member.user_email}</div>
                        <div className="mt-1 text-sm text-ink">{member.name || 'Unnamed user'}</div>
                        <div className="mt-1 text-xs text-muted">
                          {member.is_admin ? 'admin' : 'user'} · joined{' '}
                          {new Date(member.joined_at).toLocaleDateString()}
                        </div>
                      </div>
                      <button
                        onClick={() => handleRemoveMember(member.user_email)}
                        disabled={removingMemberEmail === member.user_email}
                        className="rounded-lg border border-line px-3 py-1.5 text-sm font-semibold text-ink transition hover:border-red-300 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {removingMemberEmail === member.user_email ? 'Removing…' : 'Remove'}
                      </button>
                    </div>
                  ))}
                </div>
              </div>

              {detail.members.length === 0 && (
                <p className="text-sm text-muted">This team has no members yet.</p>
              )}
            </section>
          </div>
        ) : (
          <div className="mt-8 text-sm text-muted">Team not found.</div>
        )}
      </div>
    </div>
  );
}
