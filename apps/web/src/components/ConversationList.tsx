'use client';

import React from 'react';
import Link from 'next/link';
import type { ConversationHead } from '@/types/api';

interface Props {
  conversations: ConversationHead[];
  repoNames: Record<string, string>;
  onSelect: (conv: ConversationHead) => void;
}

export default function ConversationList({ conversations, repoNames, onSelect }: Props) {
  // Group conversations by repo_def_id
  const grouped = conversations.reduce<Record<string, ConversationHead[]>>((acc, conv) => {
    const key = conv.repo_def_id || '__none__';
    (acc[key] = acc[key] || []).push(conv);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      {Object.entries(grouped).map(([repoDefId, convs]) => (
        <div key={repoDefId} className="space-y-2">
          <h4 className="px-3 text-xs font-semibold uppercase tracking-wide text-muted">
            {repoDefId === '__none__' ? 'Unscoped' : (repoNames[repoDefId] || repoDefId)}
          </h4>
          <div className="space-y-1">
            {convs.map((conv) => (
              <button
                key={conv.conversation_id}
                onClick={() => onSelect(conv)}
                className="w-full rounded-lg px-3 py-2 text-left transition hover:bg-panel"
              >
                <div className="text-sm font-medium text-ink">
                  {conv.title || 'Untitled conversation'}
                </div>
                <div className="text-xs text-muted">
                  {new Date(conv.updated_at).toLocaleDateString()} — {conv.status}
                </div>
              </button>
            ))}
          </div>
        </div>
      ))}
      {conversations.length === 0 && (
        <p className="px-3 text-sm text-muted">No conversations yet.</p>
      )}
    </div>
  );
}
