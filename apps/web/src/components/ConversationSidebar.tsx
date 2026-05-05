'use client';

import React from 'react';
import type { ConversationHead } from '@/types/api';
import { cn } from '@/lib/utils';

interface ConversationSidebarProps {
  scopeLabel: string;
  scopeSubLabel?: string | null;
  currentConversationId: string;
  conversations: ConversationHead[];
  isCreatingConversation: boolean;
  mobileOpen: boolean;
  desktopCollapsed: boolean;
  busyConversationId: string | null;
  onCloseMobile: () => void;
  onCreateConversation: () => void;
  onDeleteConversation: (conversation: ConversationHead) => void;
  onRenameConversation: (conversation: ConversationHead, title: string | null) => Promise<void>;
  onSelectConversation: (conversation: ConversationHead) => void;
  onTogglePinConversation: (conversation: ConversationHead) => void;
  onToggleDesktopCollapsed: () => void;
}

interface ConversationGroup {
  key: 'pinned' | 'today' | 'lastWeek' | 'earlier';
  label: string;
  conversations: ConversationHead[];
}

export default function ConversationSidebar({
  scopeLabel,
  scopeSubLabel,
  currentConversationId,
  conversations,
  isCreatingConversation,
  mobileOpen,
  desktopCollapsed,
  busyConversationId,
  onCloseMobile,
  onCreateConversation,
  onDeleteConversation,
  onRenameConversation,
  onSelectConversation,
  onTogglePinConversation,
  onToggleDesktopCollapsed,
}: ConversationSidebarProps) {
  const [searchValue, setSearchValue] = React.useState('');

  const filteredConversations = React.useMemo(() => {
    const query = searchValue.trim().toLowerCase();
    if (!query) {
      return conversations;
    }

    return conversations.filter((conversation) =>
      getConversationDisplayTitle(conversation).toLowerCase().includes(query)
    );
  }, [conversations, searchValue]);

  const groups = React.useMemo(
    () => groupConversations(filteredConversations),
    [filteredConversations]
  );

  const shortcuts = React.useMemo(
    () => buildShortcutConversations(conversations).slice(0, 8),
    [conversations]
  );

  return (
    <>
      <div
        className={cn(
          'fixed inset-0 z-30 bg-ink/35 transition md:hidden',
          mobileOpen ? 'pointer-events-auto opacity-100' : 'pointer-events-none opacity-0'
        )}
        onClick={onCloseMobile}
      />
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-40 flex w-[320px] flex-col border-r border-line bg-panel transition-transform duration-200 md:static md:z-auto md:translate-x-0',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
          desktopCollapsed ? 'md:w-[72px]' : 'md:w-[320px]'
        )}
      >
        <div className={cn('flex h-full flex-col', desktopCollapsed ? 'md:hidden' : 'md:flex')}>
          <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-4">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold leading-snug text-ink [overflow-wrap:anywhere]">
                {scopeLabel}
              </p>
              <p className="mt-1 text-xs leading-snug text-muted [overflow-wrap:anywhere]">
                {scopeSubLabel || 'All conversations in this repository'}
              </p>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={onToggleDesktopCollapsed}
                className="hidden rounded-xl p-2 text-muted transition hover:bg-cream hover:text-ink md:inline-flex"
                aria-label="Collapse conversation sidebar"
                data-testid="sidebar-collapse-toggle"
              >
                <CollapseIcon />
              </button>
              <button
                type="button"
                onClick={onCloseMobile}
                className="rounded-xl p-2 text-muted transition hover:bg-cream hover:text-ink md:hidden"
                aria-label="Close conversations sidebar"
              >
                <CloseIcon />
              </button>
            </div>
          </div>

          <div className="border-b border-line px-4 py-4">
            <button
              type="button"
              onClick={onCreateConversation}
              disabled={isCreatingConversation}
              className="flex w-full items-center justify-center gap-2 rounded-2xl bg-accent px-4 py-3 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <PlusIcon />
              {isCreatingConversation ? 'Creating...' : 'New conversation'}
            </button>
            <label className="mt-3 block">
              <span className="sr-only">Search conversations</span>
              <input
                type="text"
                value={searchValue}
                onChange={(event) => setSearchValue(event.target.value)}
                placeholder="Search conversations"
                className="w-full rounded-2xl border border-line bg-cream px-3 py-2 text-sm text-ink outline-none transition placeholder:text-muted/70 focus:border-accent"
              />
            </label>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-3 py-4">
            {groups.every((group) => group.conversations.length === 0) ? (
              <div className="rounded-2xl border border-dashed border-line bg-cream px-4 py-6 text-sm text-muted">
                {searchValue.trim()
                  ? 'No conversations match this search.'
                  : 'No conversations in this repository scope yet.'}
              </div>
            ) : (
              <div className="space-y-5">
                {groups.map((group) => (
                  <ConversationSidebarGroup
                    key={group.key}
                    group={group}
                    currentConversationId={currentConversationId}
                    busyConversationId={busyConversationId}
                    onDeleteConversation={onDeleteConversation}
                    onRenameConversation={onRenameConversation}
                    onSelectConversation={onSelectConversation}
                    onTogglePinConversation={onTogglePinConversation}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        <div className={cn('hidden h-full flex-col items-center gap-3 py-4 md:flex', desktopCollapsed ? 'md:flex' : 'md:hidden')}>
          <button
            type="button"
            onClick={onToggleDesktopCollapsed}
            className="rounded-2xl border border-line bg-cream p-3 text-muted transition hover:border-accent/20 hover:text-ink"
            aria-label="Expand conversation sidebar"
            data-testid="sidebar-collapse-toggle"
          >
            <ExpandIcon />
          </button>
          <button
            type="button"
            onClick={onCreateConversation}
            disabled={isCreatingConversation}
            className="rounded-2xl bg-accent p-3 text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-60"
            aria-label={isCreatingConversation ? 'Creating conversation' : 'New conversation'}
            title={isCreatingConversation ? 'Creating conversation' : 'New conversation'}
          >
            <PlusIcon />
          </button>
          <div className="h-px w-8 bg-line" />
          <div className="flex flex-col items-center gap-2">
            {shortcuts.map((conversation) => (
              <button
                key={conversation.conversation_id}
                type="button"
                onClick={() => onSelectConversation(conversation)}
                disabled={busyConversationId === conversation.conversation_id}
                className={cn(
                  'flex h-11 w-11 items-center justify-center rounded-2xl border text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60',
                  conversation.conversation_id === currentConversationId
                    ? 'border-accent/25 bg-accent/10 text-accent'
                    : 'border-transparent bg-cream text-ink hover:border-line hover:bg-panel'
                )}
                title={getConversationDisplayTitle(conversation)}
              >
                {getConversationShortcutLabel(conversation)}
              </button>
            ))}
          </div>
        </div>
      </aside>
    </>
  );
}

function ConversationSidebarGroup({
  group,
  currentConversationId,
  busyConversationId,
  onDeleteConversation,
  onRenameConversation,
  onSelectConversation,
  onTogglePinConversation,
}: {
  group: ConversationGroup;
  currentConversationId: string;
  busyConversationId: string | null;
  onDeleteConversation: (conversation: ConversationHead) => void;
  onRenameConversation: (conversation: ConversationHead, title: string | null) => Promise<void>;
  onSelectConversation: (conversation: ConversationHead) => void;
  onTogglePinConversation: (conversation: ConversationHead) => void;
}) {
  if (group.conversations.length === 0) {
    return null;
  }

  return (
    <section>
      <h2 className="px-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
        {group.label}
      </h2>
      <div className="mt-2 space-y-1">
        {group.conversations.map((conversation) => (
          <ConversationRow
            key={conversation.conversation_id}
            conversation={conversation}
            isActive={conversation.conversation_id === currentConversationId}
            isBusy={busyConversationId === conversation.conversation_id}
            onDelete={() => onDeleteConversation(conversation)}
            onRename={(title) => onRenameConversation(conversation, title)}
            onSelect={() => onSelectConversation(conversation)}
            onTogglePin={() => onTogglePinConversation(conversation)}
          />
        ))}
      </div>
    </section>
  );
}

function ConversationRow({
  conversation,
  isActive,
  isBusy,
  onDelete,
  onRename,
  onSelect,
  onTogglePin,
}: {
  conversation: ConversationHead;
  isActive: boolean;
  isBusy: boolean;
  onDelete: () => void;
  onRename: (title: string | null) => Promise<void>;
  onSelect: () => void;
  onTogglePin: () => void;
}) {
  const [isEditing, setIsEditing] = React.useState(false);
  const [draftTitle, setDraftTitle] = React.useState(conversation.title ?? '');

  React.useEffect(() => {
    if (!isEditing) {
      setDraftTitle(conversation.title ?? '');
    }
  }, [conversation.title, isEditing]);

  async function handleRenameSubmit() {
    await onRename(draftTitle.trim() ? draftTitle.trim() : null);
    setIsEditing(false);
  }

  return (
    <div
      className={cn(
        'group rounded-2xl border px-3 py-3 transition',
        isActive
          ? 'border-accent/25 bg-accent/10 shadow-sm'
          : 'border-transparent hover:border-line hover:bg-cream'
      )}
    >
      <div className="flex items-start gap-3">
        {isEditing ? (
          <div className="min-w-0 flex-1 space-y-2">
            <input
              autoFocus
              type="text"
              value={draftTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  void handleRenameSubmit();
                }
                if (event.key === 'Escape') {
                  event.preventDefault();
                  setIsEditing(false);
                  setDraftTitle(conversation.title ?? '');
                }
              }}
              className="w-full rounded-xl border border-line bg-panel px-3 py-2 text-sm text-ink outline-none focus:border-accent"
              placeholder="Conversation title"
            />
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  void handleRenameSubmit();
                }}
                disabled={isBusy}
                className="rounded-xl bg-accent px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => {
                  setIsEditing(false);
                  setDraftTitle(conversation.title ?? '');
                }}
                className="rounded-xl border border-line px-3 py-1.5 text-xs font-medium text-ink transition hover:bg-panel"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={onSelect}
            disabled={isBusy}
            className="min-w-0 flex-1 text-left disabled:cursor-not-allowed disabled:opacity-60"
          >
            <p className="truncate text-sm font-medium text-ink">
              {getConversationDisplayTitle(conversation)}
            </p>
            <p className="mt-1 text-xs text-muted">{formatCreatedAt(conversation.created_at)}</p>
          </button>
        )}

        {!isEditing && (
          <div className="flex shrink-0 items-center gap-1 opacity-100 md:opacity-0 md:transition md:group-hover:opacity-100 md:group-focus-within:opacity-100">
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onTogglePin();
              }}
              disabled={isBusy}
              className={cn(
                'rounded-xl p-2 transition disabled:cursor-not-allowed disabled:opacity-60',
                conversation.pinned_at
                  ? 'bg-accent/10 text-accent'
                  : 'text-muted hover:bg-panel hover:text-ink'
              )}
              aria-label={conversation.pinned_at ? 'Unpin conversation' : 'Pin conversation'}
            >
              <PinIcon />
            </button>
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                setIsEditing(true);
              }}
              disabled={isBusy}
              className="rounded-xl p-2 text-muted transition hover:bg-panel hover:text-ink disabled:cursor-not-allowed disabled:opacity-60"
              aria-label="Rename conversation"
            >
              <EditIcon />
            </button>
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onDelete();
              }}
              disabled={isBusy}
              className="rounded-xl p-2 text-muted transition hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-60"
              aria-label="Delete conversation"
            >
              <TrashIcon />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function buildShortcutConversations(conversations: ConversationHead[]): ConversationHead[] {
  return [...conversations].sort((left, right) => {
    const pinnedDelta = sortByPinnedAtThenUpdatedAt(left, right);
    if (pinnedDelta !== 0) {
      return pinnedDelta;
    }
    return sortByUpdatedAtDesc(left, right);
  });
}

function groupConversations(conversations: ConversationHead[]): ConversationGroup[] {
  const todayBoundary = new Date();
  todayBoundary.setHours(0, 0, 0, 0);

  const lastWeekBoundary = new Date(todayBoundary);
  lastWeekBoundary.setDate(lastWeekBoundary.getDate() - 7);

  const pinned = conversations
    .filter((conversation) => Boolean(conversation.pinned_at))
    .sort(sortByPinnedAtThenUpdatedAt);

  const unpinned = conversations
    .filter((conversation) => !conversation.pinned_at)
    .sort(sortByUpdatedAtDesc);

  return [
    {
      key: 'pinned',
      label: 'Pinned',
      conversations: pinned,
    },
    {
      key: 'today',
      label: 'Today',
      conversations: unpinned.filter((conversation) => new Date(conversation.updated_at) >= todayBoundary),
    },
    {
      key: 'lastWeek',
      label: 'Last week',
      conversations: unpinned.filter((conversation) => {
        const updatedAt = new Date(conversation.updated_at);
        return updatedAt < todayBoundary && updatedAt >= lastWeekBoundary;
      }),
    },
    {
      key: 'earlier',
      label: 'Earlier',
      conversations: unpinned.filter((conversation) => new Date(conversation.updated_at) < lastWeekBoundary),
    },
  ];
}

function sortByUpdatedAtDesc(left: ConversationHead, right: ConversationHead): number {
  return new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime();
}

function sortByPinnedAtThenUpdatedAt(left: ConversationHead, right: ConversationHead): number {
  const pinnedDelta =
    new Date(right.pinned_at || right.updated_at).getTime() -
    new Date(left.pinned_at || left.updated_at).getTime();

  if (pinnedDelta !== 0) {
    return pinnedDelta;
  }

  return sortByUpdatedAtDesc(left, right);
}

function formatCreatedAt(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(value));
}

function getConversationShortcutLabel(conversation: ConversationHead): string {
  const title = getConversationDisplayTitle(conversation).trim();
  const words = title.split(/\s+/).filter(Boolean);
  if (words.length === 0) {
    return 'N';
  }
  if (words.length === 1) {
    return words[0].slice(0, 1).toUpperCase();
  }
  return `${words[0][0] ?? ''}${words[1][0] ?? ''}`.toUpperCase();
}

export function getConversationDisplayTitle(conversation: ConversationHead): string {
  const normalized = conversation.title?.trim();
  if (normalized) {
    return normalized;
  }

  return 'New conversation';
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5" aria-hidden="true">
      <path d="M5 5L15 15M15 5L5 15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function CollapseIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5" aria-hidden="true">
      <path
        d="M12.5 4.167L7.5 10L12.5 15.833"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ExpandIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5" aria-hidden="true">
      <path
        d="M7.5 4.167L12.5 10L7.5 15.833"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function EditIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4" aria-hidden="true">
      <path
        d="M13.75 3.75L16.25 6.25M4.583 15.417L7.236 14.887C7.555 14.823 7.848 14.666 8.078 14.436L15.625 6.889C16.316 6.198 16.316 5.077 15.625 4.386L15.614 4.375C14.923 3.684 13.802 3.684 13.111 4.375L5.564 11.922C5.334 12.152 5.177 12.445 5.113 12.764L4.583 15.417Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function PinIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4" aria-hidden="true">
      <path
        d="M6.667 4.167H13.333L12.5 8.333L15 10.833V11.667H10.833L10 15.833L9.167 11.667H5V10.833L7.5 8.333L6.667 4.167Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4" aria-hidden="true">
      <path d="M10 4.167V15.833M4.167 10H15.833" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-4 w-4" aria-hidden="true">
      <path
        d="M4.167 5.833H15.833M7.5 5.833V4.167C7.5 3.707 7.873 3.333 8.333 3.333H11.667C12.127 3.333 12.5 3.707 12.5 4.167V5.833M6.667 5.833V14.167C6.667 15.087 7.413 15.833 8.333 15.833H11.667C12.587 15.833 13.333 15.087 13.333 14.167V5.833"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
