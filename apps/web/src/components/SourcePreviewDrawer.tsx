'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import type { CitationPreviewResponse } from '@/types/api';

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

  const highlightedStart = preview?.requested_start_line ?? 0;
  const highlightedEnd = preview?.requested_end_line ?? 0;

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
            <div className="overflow-hidden rounded-2xl border border-line bg-panel">
              <div className="border-b border-line bg-panel px-4 py-2 text-xs text-muted">
                Preview window {preview.preview_start_line}-{preview.preview_end_line}
              </div>
              <div className="overflow-auto">
                <pre className="min-w-full text-sm leading-6 text-ink">
                  {preview.lines.map((line) => {
                    const highlighted =
                      line.line_number >= highlightedStart && line.line_number <= highlightedEnd;
                    return (
                      <div
                        key={line.line_number}
                        className={cn(
                          'grid grid-cols-[64px_1fr] gap-4 px-4 py-1.5 font-mono',
                          highlighted ? 'bg-accent/10' : 'bg-transparent'
                        )}
                        data-testid={highlighted ? 'citation-preview-highlighted-line' : undefined}
                      >
                        <span className="select-none text-right text-xs text-muted" data-testid="citation-preview-line-number">
                          {line.line_number}
                        </span>
                        <span className="overflow-x-auto whitespace-pre-wrap break-words">
                          {line.content || ' '}
                        </span>
                      </div>
                    );
                  })}
                </pre>
              </div>
            </div>
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
