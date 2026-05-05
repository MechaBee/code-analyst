'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { EvidenceRef, Message } from '@/types/api';
import { cn } from '@/lib/utils';
import CitationCard from './CitationCard';

interface MessageBubbleProps {
  message: Message;
  onFollowupClick?: (followup: string) => void;
  onCitationClick?: (citation: EvidenceRef) => void;
  activeCitationKey?: string | null;
}

export default function MessageBubble({
  message,
  onFollowupClick,
  onCitationClick,
  activeCitationKey,
}: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const [copied, setCopied] = React.useState(false);

  React.useEffect(() => {
    if (!copied) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timeoutId);
  }, [copied]);

  async function handleCopy() {
    if (!message.content.trim()) {
      return;
    }

    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  if (isUser) {
    return (
      <div className="flex w-full justify-end" data-testid="user-message">
        <div className="max-w-[min(42rem,82%)] rounded-3xl rounded-br-md bg-accent px-5 py-3.5 text-sm leading-7 text-white shadow-sm">
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
      </div>
    );
  }

  return (
    <article
      className="group/message w-full"
      data-testid="assistant-message"
    >
      <div className="max-w-[78ch]">
        <div
          className={cn(
            'text-[15px] leading-7 text-ink sm:text-base',
            message.error && 'text-red-700'
          )}
        >
          {message.isLoading && !message.content ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm font-medium text-muted">
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-muted/25 border-t-accent" />
                Thinking…
              </div>
              {message.statusUpdates && message.statusUpdates.length > 0 && (
                <ul className="space-y-1.5 text-sm text-muted">
                  {message.statusUpdates.slice(-4).map((status, index) => (
                    <li key={`${status}-${index}`}>{status}</li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <div className="prose prose-neutral max-w-none prose-headings:mb-3 prose-headings:mt-8 prose-p:my-3 prose-p:leading-7 prose-ul:my-4 prose-ol:my-4 prose-li:my-1.5 prose-code:rounded prose-code:bg-panel prose-code:px-1 prose-code:py-0.5 prose-code:text-[0.95em] prose-pre:rounded-2xl prose-pre:border prose-pre:border-line prose-pre:bg-panel prose-pre:px-4 prose-pre:py-3 prose-strong:text-ink">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {!message.isLoading && message.content.trim() && (
          <div className="mt-3 flex items-center gap-2 text-xs md:opacity-0 md:transition md:group-hover/message:opacity-100 md:group-focus-within/message:opacity-100">
            <button
              type="button"
              onClick={() => {
                void handleCopy();
              }}
              className="rounded-full border border-line px-2.5 py-1 font-medium text-muted transition hover:border-accent/30 hover:bg-panel hover:text-ink"
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        )}

        {message.citations && message.citations.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {message.citations.map((citation, index) => {
              const citationKey = `${citation.snapshot_id}:${citation.path}:${citation.start_line}:${citation.end_line}`;
              return (
                <CitationCard
                  key={`${citation.path}-${index}`}
                  citation={citation}
                  onClick={onCitationClick}
                  isLoading={activeCitationKey === citationKey}
                />
              );
            })}
          </div>
        )}

        {message.followups && message.followups.length > 0 && (
          <div className="mt-5 border-t border-line/70 pt-4">
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-muted">
              Follow-ups
            </p>
            <div className="flex flex-wrap gap-2">
              {message.followups.map((followup, index) => (
                <button
                  key={`${followup}-${index}`}
                  type="button"
                  onClick={() => onFollowupClick?.(followup)}
                  className="rounded-full border border-line bg-panel px-3 py-1.5 text-sm text-ink transition hover:border-accent/30 hover:bg-accent/5 hover:text-accent"
                  data-testid="followup-chip"
                >
                  {followup}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </article>
  );
}
