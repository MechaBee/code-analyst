'use client';

import React, { useState } from 'react';
import { useApi } from '@/hooks/useApi';
import { cn } from '@/lib/utils';

export default function WorkspaceImport() {
  const api = useApi();
  const [url, setUrl] = useState('');
  const [ref, setRef] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<{ workspaceId: string; snapshotId: string } | null>(null);

  const handleImport = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setImportResult(null);
    setLoading(true);

    try {
      const importRes = await api.importWorkspace({
        tenant_id: 'tenant_local',
        repo_url: url.trim(),
        ref: ref.trim(),
        github_credential_ref: 'public',
      });
      setImportResult({
        workspaceId: importRes.workspace_id,
        snapshotId: importRes.snapshot_id,
      });
      setNotice(
        'Raw workspace import still works, but starting a conversation now requires a repository definition and checkout. Use the dashboard repository flow next.'
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-md rounded-2xl border border-line bg-panel p-8 shadow-sm">
        <h1 className="mb-2 text-3xl font-bold tracking-tight text-ink">Code Analyst</h1>
        <p className="mb-6 text-sm text-muted">
          Analyze any codebase. Import a GitHub repository to begin.
        </p>

        <form onSubmit={handleImport} className="space-y-4">
          <div>
            <label htmlFor="repo-url" className="mb-1 block text-sm font-medium text-ink">
              GitHub Repository URL
            </label>
            <input
              id="repo-url"
              type="url"
              required
              placeholder="https://github.com/owner/repo"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className={cn(
                'w-full rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none transition',
                'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                error ? 'border-red-400' : 'border-line'
              )}
            />
          </div>

          <div>
            <label htmlFor="repo-ref" className="mb-1 block text-sm font-medium text-ink">
              Branch / Tag / Ref
            </label>
            <input
              id="repo-ref"
              type="text"
              placeholder="main"
              value={ref}
              onChange={(e) => setRef(e.target.value)}
              className={cn(
                'w-full rounded-lg border bg-cream px-3 py-2 text-sm text-ink outline-none transition',
                'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
                error ? 'border-red-400' : 'border-line'
              )}
            />
            <p className="mt-1 text-xs text-muted">
              Leave empty to auto-detect the default branch.
            </p>
          </div>

          {error && (
            <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
              {error}
            </div>
          )}

          {notice && (
            <div className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {notice}
            </div>
          )}

          {importResult && (
            <div className="rounded-lg border border-line bg-cream px-3 py-2 text-sm text-ink">
              <div>
                Workspace: <span className="font-mono">{importResult.workspaceId}</span>
              </div>
              <div>
                Snapshot: <span className="font-mono">{importResult.snapshotId}</span>
              </div>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className={cn(
              'w-full rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition',
              loading
                ? 'cursor-not-allowed bg-accent/60'
                : 'bg-accent hover:bg-accent/90 active:scale-[0.98]'
            )}
          >
            {loading ? 'Importing…' : 'Import Repository'}
          </button>
        </form>
      </div>
    </div>
  );
}
