'use client';

import dynamic from 'next/dynamic';
import React from 'react';
import type { CitationPreviewResponse } from '@/types/api';
import type { SourceCodePreviewProps } from './SourceCodePreview';

const SourceCodePreview = dynamic<SourceCodePreviewProps>(() => import('./SourceCodePreview'), {
  ssr: false,
  loading: () => (
    <div className="rounded-2xl border border-line bg-panel px-4 py-5 text-sm text-muted">
      Loading code preview...
    </div>
  ),
});

interface SourcePreviewDrawerProps {
  open: boolean;
  preview: CitationPreviewResponse | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}

export default function SourcePreviewDrawer({
  open,
  preview,
  loading,
  error,
  onClose,
}: SourcePreviewDrawerProps) {
  React.useEffect(() => {
    if (!open) {
      return undefined;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose();
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, open]);

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-40" data-testid="citation-preview-drawer">
      <button
        type="button"
        onClick={onClose}
        className="absolute inset-0 bg-ink/30"
        aria-label="Close source preview"
      />
      <aside className="absolute inset-x-0 bottom-0 top-0 flex flex-col bg-panel shadow-2xl md:inset-y-0 md:left-auto md:right-0 md:w-[min(720px,48vw)] md:border-l md:border-line">
        <div className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-5">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted">
              Source preview
            </p>
            <p className="mt-1 truncate text-sm font-medium text-ink">
              {preview?.path ?? 'Loading source...'}
            </p>
            {preview && (
              <p className="mt-1 text-xs text-muted">
                Lines {preview.requested_start_line}-{preview.requested_end_line}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl p-2 text-muted transition hover:bg-cream hover:text-ink"
            aria-label="Close source preview"
          >
            <CloseIcon />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto bg-cream px-3 py-3 sm:px-4">
          {loading ? (
            <div className="rounded-2xl border border-line bg-panel px-4 py-5 text-sm text-muted">
              Loading cited lines...
            </div>
          ) : error ? (
            <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-5 text-sm text-red-700">
              {error}
            </div>
          ) : preview ? (
            <SourceCodePreview preview={preview} />
          ) : null}
        </div>
      </aside>
    </div>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5" aria-hidden="true">
      <path d="M5 5L15 15M15 5L5 15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
