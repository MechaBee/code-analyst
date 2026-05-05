'use client';

import Link from 'next/link';
import React, { useEffect, useMemo, useState } from 'react';

import { useApi } from '@/hooks/useApi';
import { useAuth } from '@/hooks/useAuth';
import { cn } from '@/lib/utils';
import type {
  AdminUserRecord,
  PendingRegistrationInvite,
  RegistrationInviteCreateResponse,
  TeamSummary,
} from '@/types/api';

import NavBar from './NavBar';

type GeneratedLink = {
  kind: 'invite' | 'sign-in';
  email: string;
  url: string;
  expiresAt: string;
};

function buildMailtoHref(link: GeneratedLink): string {
  const subject =
    link.kind === 'invite'
      ? 'Your Code Analyst registration link'
      : 'Your Code Analyst sign-in link';
  const body =
    link.kind === 'invite'
      ? `Use this link to register for Code Analyst:\n\n${link.url}\n\nThis link expires on ${new Date(
          link.expiresAt
        ).toLocaleString()}.`
      : `Use this link to sign in to Code Analyst:\n\n${link.url}\n\nThis link expires on ${new Date(
          link.expiresAt
        ).toLocaleString()}.`;

  return `mailto:${encodeURIComponent(link.email)}?subject=${encodeURIComponent(
    subject
  )}&body=${encodeURIComponent(body)}`;
}

export default function AdminDashboard() {
  const { isAdmin, isAuthenticated, email, isLoading: authLoading } = useAuth();
  const api = useApi();

  const [teams, setTeams] = useState<TeamSummary[]>([]);
  const [users, setUsers] = useState<AdminUserRecord[]>([]);
  const [pendingInvites, setPendingInvites] = useState<PendingRegistrationInvite[]>([]);
  const [teamName, setTeamName] = useState('');
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteName, setInviteName] = useState('');
  const [inviteIsAdmin, setInviteIsAdmin] = useState(false);
  const [inviteTeamIds, setInviteTeamIds] = useState<string[]>([]);
  const [generatedLink, setGeneratedLink] = useState<GeneratedLink | null>(null);
  const [loading, setLoading] = useState(true);
  const [submittingTeam, setSubmittingTeam] = useState(false);
  const [submittingInvite, setSubmittingInvite] = useState(false);
  const [signingInEmail, setSigningInEmail] = useState<string | null>(null);
  const [shareNotice, setShareNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const canUseWebShare =
    typeof navigator !== 'undefined' && typeof navigator.share === 'function';

  useEffect(() => {
    if (!isAuthenticated || !isAdmin) {
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

        if (cancelled) {
          return;
        }

        setTeams(teamResponse.teams);
        setUsers(userResponse.users);
        setPendingInvites(userResponse.pending_invites);
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
  }, [api, isAdmin, isAuthenticated, refreshKey]);

  const refresh = () => setRefreshKey((value) => value + 1);

  const mailtoHref = generatedLink ? buildMailtoHref(generatedLink) : null;

  const inviteableTeams = useMemo(
    () => [...teams].sort((left, right) => left.name.localeCompare(right.name)),
    [teams]
  );

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

  const handleToggleInviteTeam = (teamId: string) => {
    setInviteTeamIds((current) =>
      current.includes(teamId)
        ? current.filter((entry) => entry !== teamId)
        : [...current, teamId]
    );
  };

  const handleCreateInvite = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmittingInvite(true);
    setError(null);
    setShareNotice(null);

    try {
      const result = await api.createRegistrationInvite({
        email: inviteEmail,
        name: inviteName || null,
        team_ids: inviteTeamIds,
        is_admin: inviteIsAdmin,
      });
      setGeneratedLink({
        kind: 'invite',
        email: result.email,
        url: result.invite_url,
        expiresAt: result.expires_at,
      });
      setInviteEmail('');
      setInviteName('');
      setInviteIsAdmin(false);
      setInviteTeamIds([]);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create invite');
    } finally {
      setSubmittingInvite(false);
    }
  };

  const handleCreateSignInLink = async (targetEmail: string) => {
    setSigningInEmail(targetEmail);
    setError(null);
    setShareNotice(null);
    try {
      const result = await api.createSignInLink({ email: targetEmail });
      setGeneratedLink({
        kind: 'sign-in',
        email: result.email,
        url: result.sign_in_url,
        expiresAt: result.expires_at,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create sign-in link');
    } finally {
      setSigningInEmail(null);
    }
  };

  const handleCopyLink = async () => {
    if (!generatedLink) {
      return;
    }
    try {
      await navigator.clipboard.writeText(generatedLink.url);
      setShareNotice('Link copied to clipboard.');
    } catch {
      setShareNotice('Copy failed. Use your browser copy command instead.');
    }
  };

  const handleWebShare = async () => {
    if (!generatedLink || !canUseWebShare) {
      return;
    }
    try {
      await navigator.share({
        title:
          generatedLink.kind === 'invite'
            ? 'Code Analyst registration link'
            : 'Code Analyst sign-in link',
        url: generatedLink.url,
      });
      setShareNotice('Link shared.');
    } catch {
      // Ignore cancelled shares.
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

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-cream">
        <NavBar active="admin" />
        <div className="mx-auto max-w-2xl px-6 py-16">
          <div className="rounded-3xl border border-line bg-panel p-8 text-center shadow-sm">
            <h1 className="text-2xl font-semibold text-ink">Admin Access Requires Sign-In</h1>
            <p className="mt-3 text-sm text-muted">
              Use an admin sign-in link to access the dashboard.
            </p>
          </div>
        </div>
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
            <p className="mt-1 text-sm text-muted">
              Manage teams, onboarding, and access link distribution.
            </p>
          </div>
          <div className="text-sm text-muted">{email}</div>
        </div>

        {error && (
          <div className="mt-6 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
            {error}
          </div>
        )}

        {shareNotice && (
          <div className="mt-4 rounded-lg bg-emerald-50 px-4 py-2 text-sm text-emerald-700">
            {shareNotice}
          </div>
        )}

        {generatedLink && (
          <section className="mt-6 rounded-2xl border border-line bg-panel p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-ink">
                  {generatedLink.kind === 'invite' ? 'Registration Link Ready' : 'Sign-In Link Ready'}
                </h2>
                <p className="mt-1 text-sm text-muted">
                  Deliver this link to {generatedLink.email}. It expires{' '}
                  {new Date(generatedLink.expiresAt).toLocaleString()}.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {mailtoHref && (
                  <a
                    href={mailtoHref}
                    className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent/90"
                  >
                    Open Mail App
                  </a>
                )}
                <button
                  type="button"
                  onClick={() => void handleCopyLink()}
                  className="rounded-lg border border-line px-4 py-2 text-sm font-semibold text-ink transition hover:border-accent hover:text-accent"
                >
                  Copy Link
                </button>
                {canUseWebShare && (
                  <button
                    type="button"
                    onClick={() => void handleWebShare()}
                    className="rounded-lg border border-line px-4 py-2 text-sm font-semibold text-ink transition hover:border-accent hover:text-accent"
                  >
                    Share
                  </button>
                )}
              </div>
            </div>

            <div className="mt-4 rounded-xl bg-cream px-4 py-3 font-mono text-xs text-ink">
              {generatedLink.url}
            </div>
          </section>
        )}

        <div className="mt-8 grid gap-8 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
          <section className="space-y-5">
            <div className="rounded-2xl border border-line bg-panel p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-ink">Teams</h2>
                  <p className="mt-1 text-sm text-muted">
                    Create teams and jump into access management.
                  </p>
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

            {!loading && teams.length === 0 && <p className="text-sm text-muted">No teams yet.</p>}
          </section>

          <section className="space-y-5">
            <div className="rounded-2xl border border-line bg-panel p-5 shadow-sm">
              <div>
                <h2 className="text-lg font-semibold text-ink">Invite User</h2>
                <p className="mt-1 text-sm text-muted">
                  Create a registration link and share it through your local mail app or by copy.
                </p>
              </div>

              <form onSubmit={handleCreateInvite} className="mt-5 space-y-4">
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <input
                    type="email"
                    placeholder="Email"
                    value={inviteEmail}
                    onChange={(event) => setInviteEmail(event.target.value)}
                    className={cn(
                      'rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                      'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                      'border-line'
                    )}
                  />
                  <input
                    type="text"
                    placeholder="Name (optional)"
                    value={inviteName}
                    onChange={(event) => setInviteName(event.target.value)}
                    className={cn(
                      'rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                      'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                      'border-line'
                    )}
                  />
                </div>

                <label className="flex items-center gap-2 text-sm text-ink">
                  <input
                    type="checkbox"
                    checked={inviteIsAdmin}
                    onChange={(event) => setInviteIsAdmin(event.target.checked)}
                    className="rounded border-line"
                  />
                  Grant admin access on registration
                </label>

                <div>
                  <label className="mb-2 block text-xs font-medium text-ink">Initial Team Access</label>
                  {inviteableTeams.length === 0 ? (
                    <p className="text-sm text-muted">
                      No teams available yet. You can still invite the user now and assign teams
                      later.
                    </p>
                  ) : (
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {inviteableTeams.map((team) => (
                        <label
                          key={team.team_id}
                          className="flex items-center gap-2 rounded-xl border border-line bg-cream px-3 py-2 text-sm text-ink"
                        >
                          <input
                            type="checkbox"
                            checked={inviteTeamIds.includes(team.team_id)}
                            onChange={() => handleToggleInviteTeam(team.team_id)}
                            className="rounded border-line"
                          />
                          <span>{team.name}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>

                <button
                  type="submit"
                  disabled={submittingInvite || !inviteEmail.trim()}
                  className={cn(
                    'rounded-lg px-4 py-2 text-sm font-semibold text-white transition',
                    submittingInvite || !inviteEmail.trim()
                      ? 'cursor-not-allowed bg-accent/60'
                      : 'bg-accent hover:bg-accent/90'
                  )}
                >
                  {submittingInvite ? 'Creating…' : 'Create Invite Link'}
                </button>
              </form>
            </div>

            <div className="rounded-2xl border border-line bg-panel p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-ink">Pending Invites</h2>
                  <p className="mt-1 text-sm text-muted">
                    Outstanding registration links that have not been claimed yet.
                  </p>
                </div>
                <div className="rounded-full bg-cream px-3 py-1 text-xs font-semibold uppercase tracking-wide text-muted">
                  {pendingInvites.length} open
                </div>
              </div>

              <div className="mt-4 space-y-3">
                {pendingInvites.map((invite) => (
                  <article key={invite.invite_id} className="rounded-xl border border-line bg-cream p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="font-mono text-xs text-ink">{invite.email}</div>
                        <div className="mt-1 text-sm text-ink">{invite.name_hint || 'Unnamed invite'}</div>
                        <div className="mt-1 text-xs text-muted">
                          Expires {new Date(invite.expires_at).toLocaleString()}
                        </div>
                      </div>
                      <div className="text-right text-xs text-muted">
                        {invite.is_admin ? 'admin invite' : 'user invite'}
                      </div>
                    </div>
                  </article>
                ))}

                {!loading && pendingInvites.length === 0 && (
                  <p className="text-sm text-muted">No pending invites.</p>
                )}
              </div>
            </div>

            <div className="overflow-hidden rounded-2xl border border-line bg-panel shadow-sm">
              <div className="border-b border-line px-5 py-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-semibold text-ink">Registered Users</h3>
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
                      <th className="px-5 py-3">State</th>
                      <th className="px-5 py-3">Action</th>
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
                              user.is_admin ? 'bg-accent/10 text-accent' : 'bg-cream text-ink'
                            )}
                          >
                            {user.is_admin ? 'admin' : 'user'}
                          </span>
                        </td>
                        <td className="px-5 py-3">
                          <span
                            className={cn(
                              'inline-flex rounded-full px-2.5 py-1 text-xs font-semibold',
                              user.has_account
                                ? 'bg-emerald-100 text-emerald-700'
                                : 'bg-amber-100 text-amber-700'
                            )}
                          >
                            {user.has_account ? 'claimed' : 'unclaimed'}
                          </span>
                        </td>
                        <td className="px-5 py-3">
                          {user.has_account ? (
                            <button
                              type="button"
                              onClick={() => void handleCreateSignInLink(user.email)}
                              disabled={signingInEmail === user.email}
                              className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-ink transition hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {signingInEmail === user.email ? 'Creating…' : 'Create sign-in link'}
                            </button>
                          ) : (
                            <span className="text-xs text-muted">Send a registration invite instead</span>
                          )}
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
