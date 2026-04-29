'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message } from '@/types/api';
import { cn } from '@/lib/utils';
import CitationCard from './CitationCard';

interface MessageBubbleProps {
  message: Message;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <div className={cn('flex w-full', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[85%] rounded-2xl px-5 py-3.5 text-sm leading-relaxed',
          isUser
            ? 'rounded-br-sm bg-accent text-white'
            : 'rounded-bl-sm border border-line bg-panel text-ink'
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose prose-sm max-w-none dark:prose-invert prose-headings:mb-2 prose-headings:mt-4 prose-p:my-1.5 prose-ul:my-1.5 prose-ol:my-1.5">
            {message.isLoading && !message.content ? (
              <div className="flex items-center gap-2 text-muted">
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-muted/30 border-t-accent" />
                Thinking…
              </div>
            ) : (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            )}
          </div>
        )}

        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {message.citations.map((c, i) => (
              <CitationCard key={`${c.path}-${i}`} citation={c} />
            ))}
          </div>
        )}

        {!isUser && message.followups && message.followups.length > 0 && (
          <div className="mt-3 border-t border-line/60 pt-2">
            <p className="mb-1 text-xs font-semibold text-muted">Follow-ups</p>
            <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted">
              {message.followups.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
