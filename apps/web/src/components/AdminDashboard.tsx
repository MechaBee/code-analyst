'use client';

import React, { useState, useEffect } from 'react';
import { useAuth } from '@/hooks/useAuth';
import { useApi } from '@/hooks/useApi';
import { cn } from '@/lib/utils';
import NavBar from './NavBar';
import type {
  Team,
  TeamCreateRequest,
  TeamMemberAddRequest,
  UserCreateRequest,
} from '@/types/api';

export default function AdminDashboard() {
  const { isAdmin, email } = useAuth();
  const api = useApi();
  const [teams, setTeams] = useState<Team[]>([]);
  const [users, setUsers] = useState<{ email: string; name: string | null; is_admin: boolean }[]>([]);
  const [teamName, setTeamName] = useState('');
  const [userEmail, setUserEmail] = useState('');
  const [userName, setUserName] = useState('');
  const [userIsAdmin, setUserIsAdmin] = useState(false);
  const [memberEmail, setMemberEmail] = useState('');
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!isAdmin) return;
    api
      .listTeams()
      .then((res) => setTeams(res.teams))
      .catch((err: Error) => setError(err.message));
  }, [isAdmin, refreshKey, api]);

  const refresh = () => setRefreshKey((k) => k + 1);

  const handleCreateTeam = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await api.createTeam({ name: teamName });
      setTeamName('');
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create team');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await api.createUser({ email: userEmail, name: userName || null, is_admin: userIsAdmin });
      setUserEmail('');
      setUserName('');
      setUserIsAdmin(false);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create user');
    } finally {
      setLoading(false);
    }
  };

  const handleAddMember = async (teamId: string) => {
    setLoading(true);
    setError(null);
    try {
      await api.addTeamMember(teamId, { user_email: memberEmail });
      setMemberEmail('');
      setSelectedTeamId(null);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add member');
    } finally {
      setLoading(false);
    }
  };

  const handleRemoveMember = async (teamId: string, emailToRemove: string) => {
    setLoading(true);
    setError(null);
    try {
      await api.removeTeamMember(teamId, emailToRemove);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove member');
    } finally {
      setLoading(false);
    }
  };

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
      <div className="p-6">
        <div className="mx-auto max-w-5xl space-y-8">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-ink">Admin Dashboard</h1>
          <div className="text-sm text-muted">{email}</div>
        </div>

        {error && (
          <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
            {error}
          </div>
        )}

        {/* Teams Section */}
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-ink">Teams</h2>
          <form onSubmit={handleCreateTeam} className="flex gap-3">
            <input
              type="text"
              placeholder="Team name"
              value={teamName}
              onChange={(e) => setTeamName(e.target.value)}
              className={cn(
                'flex-1 rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                'border-line'
              )}
            />
            <button
              type="submit"
              disabled={loading || !teamName.trim()}
              className={cn(
                'rounded-lg px-4 py-2 text-sm font-semibold text-white transition',
                loading || !teamName.trim()
                  ? 'cursor-not-allowed bg-accent/60'
                  : 'bg-accent hover:bg-accent/90'
              )}
            >
              Create Team
            </button>
          </form>

          <div className="space-y-3">
            {teams.map((team) => (
              <div
                key={team.team_id}
                className="rounded-xl border border-line bg-panel p-4 shadow-sm"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-medium text-ink">{team.name}</div>
                    <div className="text-xs text-muted">{team.team_id}</div>
                  </div>
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <input
                    type="text"
                    placeholder="Member email"
                    value={selectedTeamId === team.team_id ? memberEmail : ''}
                    onChange={(e) => {
                      setSelectedTeamId(team.team_id);
                      setMemberEmail(e.target.value);
                    }}
                    className={cn(
                      'flex-1 rounded-lg border bg-cream px-3 py-1.5 text-sm text-ink outline-none',
                      'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                      'border-line'
                    )}
                  />
                  <button
                    onClick={() => handleAddMember(team.team_id)}
                    disabled={loading || !memberEmail.trim()}
                    className={cn(
                      'rounded-lg px-3 py-1.5 text-sm font-semibold text-white transition',
                      loading || !memberEmail.trim()
                        ? 'cursor-not-allowed bg-accent/60'
                        : 'bg-accent hover:bg-accent/90'
                    )}
                  >
                    Add
                  </button>
                </div>
              </div>
            ))}
            {teams.length === 0 && (
              <p className="text-sm text-muted">No teams yet.</p>
            )}
          </div>
        </div>

        {/* Users Section */}
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-ink">Users</h2>
          <form onSubmit={handleCreateUser} className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <input
              type="email"
              placeholder="Email"
              value={userEmail}
              onChange={(e) => setUserEmail(e.target.value)}
              className={cn(
                'rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                'border-line'
              )}
            />
            <input
              type="text"
              placeholder="Name (optional)"
              value={userName}
              onChange={(e) => setUserName(e.target.value)}
              className={cn(
                'rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none',
                'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                'border-line'
              )}
            />
            <label className="flex items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={userIsAdmin}
                onChange={(e) => setUserIsAdmin(e.target.checked)}
                className="rounded border-line"
              />
              Admin
            </label>
            <button
              type="submit"
              disabled={loading || !userEmail.trim()}
              className={cn(
                'rounded-lg px-4 py-2 text-sm font-semibold text-white transition',
                loading || !userEmail.trim()
                  ? 'cursor-not-allowed bg-accent/60'
                  : 'bg-accent hover:bg-accent/90'
              )}
            >
              Create User
            </button>
          </form>
        </div>
      </div>
    </div>
    </div>
  );
}
