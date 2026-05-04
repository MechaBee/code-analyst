'use client';

import Link from 'next/link';
import React, { useEffect, useState } from 'react';

import { useApi } from '@/hooks/useApi';
import { useAuth } from '@/hooks/useAuth';
import { cn } from '@/lib/utils';
import type { TeamSummary, User } from '@/types/api';

import NavBar from './NavBar';

export default function AdminDashboard() {
  const { isAdmin, email, isLoading: authLoading } = useAuth();
  const api = useApi();

  const [teams, setTeams] = useState<TeamSummary[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [teamName, setTeamName] = useState('');
  const [userEmail, setUserEmail] = useState('');
  const [userName, setUserName] = useState('');
  const [userIsAdmin, setUserIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submittingTeam, setSubmittingTeam] = useState(false);
  const [submittingUser, setSubmittingUser] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!isAdmin) {
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const [teamResponse, userResponse] = await Promise.all([
          api.listAdminTeams(),
          api.listUsers(),
        ]);

        if (cancelled) return;
        setTeams(teamResponse.teams);
        setUsers(userResponse.users);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load admin data');
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
  }, [api, isAdmin, refreshKey]);

  const refresh = () => setRefreshKey((value) => value + 1);

  const handleCreateTeam = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmittingTeam(true);
    setError(null);
    try {
      await api.createTeam({ name: teamName });
      setTeamName('');
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create team');
    } finally {
      setSubmittingTeam(false);
    }
  };

  const handleCreateUser = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmittingUser(true);
    setError(null);
    try {
      await api.createUser({
        email: userEmail,
        name: userName || null,
        is_admin: userIsAdmin,
      });
      setUserEmail('');
      setUserName('');
      setUserIsAdmin(false);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create user');
    } finally {
      setSubmittingUser(false);
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
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-ink">Admin Dashboard</h1>
            <p className="mt-1 text-sm text-muted">Manage teams, users, and repository access.</p>
          </div>
          <div className="text-sm text-muted">{email}</div>
        </div>

        {error && (
          <div className="mt-6 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
            {error}
          </div>
        )}

        <div className="mt-8 grid gap-8 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
          <section className="space-y-5">
            <div className="rounded-2xl border border-line bg-panel p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-ink">Teams</h2>
                  <p className="mt-1 text-sm text-muted">Create teams and jump into access management.</p>
                </div>
                <div className="rounded-full bg-cream px-3 py-1 text-xs font-semibold uppercase tracking-wide text-muted">
                  {teams.length} total
                </div>
              </div>

              <form onSubmit={handleCreateTeam} className="mt-5 flex gap-3">
                <input
                  type="text"
                  placeholder="Team name"
                  value={teamName}
                  onChange={(event) => setTeamName(event.target.value)}
                  className={cn(
                    'flex-1 rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                    'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                    'border-line'
                  )}
                />
                <button
                  type="submit"
                  disabled={submittingTeam || !teamName.trim()}
                  className={cn(
                    'rounded-lg px-4 py-2 text-sm font-semibold text-white transition',
                    submittingTeam || !teamName.trim()
                      ? 'cursor-not-allowed bg-accent/60'
                      : 'bg-accent hover:bg-accent/90'
                  )}
                >
                  {submittingTeam ? 'Creating…' : 'Create Team'}
                </button>
              </form>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              {teams.map((team) => (
                <article
                  key={team.team_id}
                  className="rounded-2xl border border-line bg-panel p-5 shadow-sm"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="truncate text-lg font-semibold text-ink">{team.name}</h3>
                      <div className="mt-1 font-mono text-xs text-muted">{team.team_id}</div>
                    </div>
                    <div className="rounded-full bg-cream px-3 py-1 text-xs font-semibold text-ink">
                      {team.member_count} {team.member_count === 1 ? 'user' : 'users'}
                    </div>
                  </div>

                  <div className="mt-5 flex items-center justify-between">
                    <div className="text-xs text-muted">
                      Created {new Date(team.created_at).toLocaleDateString()}
                    </div>
                    <Link
                      href={`/admin/teams/${team.team_id}`}
                      className="rounded-lg border border-line px-3 py-1.5 text-sm font-semibold text-ink transition hover:border-accent hover:text-accent"
                    >
                      Edit Team
                    </Link>
                  </div>
                </article>
              ))}
            </div>

            {!loading && teams.length === 0 && (
              <p className="text-sm text-muted">No teams yet.</p>
            )}
          </section>

          <section className="space-y-5">
            <div className="rounded-2xl border border-line bg-panel p-5 shadow-sm">
              <div>
                <h2 className="text-lg font-semibold text-ink">Users</h2>
                <p className="mt-1 text-sm text-muted">Add users and review their role assignments.</p>
              </div>

              <form
                onSubmit={handleCreateUser}
                className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]"
              >
                <input
                  type="email"
                  placeholder="Email"
                  value={userEmail}
                  onChange={(event) => setUserEmail(event.target.value)}
                  className={cn(
                    'rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                    'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                    'border-line'
                  )}
                />
                <input
                  type="text"
                  placeholder="Name"
                  value={userName}
                  onChange={(event) => setUserName(event.target.value)}
                  className={cn(
                    'rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                    'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                    'border-line'
                  )}
                />
                <button
                  type="submit"
                  disabled={submittingUser || !userEmail.trim()}
                  className={cn(
                    'rounded-lg px-4 py-2 text-sm font-semibold text-white transition',
                    submittingUser || !userEmail.trim()
                      ? 'cursor-not-allowed bg-accent/60'
                      : 'bg-accent hover:bg-accent/90'
                  )}
                >
                  {submittingUser ? 'Adding…' : 'Add User'}
                </button>

                <label className="flex items-center gap-2 text-sm text-ink md:col-span-3">
                  <input
                    type="checkbox"
                    checked={userIsAdmin}
                    onChange={(event) => setUserIsAdmin(event.target.checked)}
                    className="rounded border-line"
                  />
                  Grant admin access
                </label>
              </form>
            </div>

            <div className="overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
              <div className="border-b border-line px-5 py-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-semibold text-ink">All Users</h3>
                  <div className="text-xs uppercase tracking-wide text-muted">{users.length} entries</div>
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-line text-sm">
                  <thead className="bg-cream/70">
                    <tr className="text-left text-xs font-semibold uppercase tracking-wide text-muted">
                      <th className="px-5 py-3">Email</th>
                      <th className="px-5 py-3">Name</th>
                      <th className="px-5 py-3">Role</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {users.map((user) => (
                      <tr key={user.email}>
                        <td className="px-5 py-3 font-mono text-xs text-ink">{user.email}</td>
                        <td className="px-5 py-3 text-ink">{user.name || '—'}</td>
                        <td className="px-5 py-3">
                          <span
                            className={cn(
                              'inline-flex rounded-full px-2.5 py-1 text-xs font-semibold',
                              user.is_admin
                                ? 'bg-accent/10 text-accent'
                                : 'bg-cream text-ink'
                            )}
                          >
                            {user.is_admin ? 'admin' : 'user'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {!loading && users.length === 0 && (
                <div className="px-5 py-4 text-sm text-muted">No users yet.</div>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
