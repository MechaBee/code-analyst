'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState, useTransition } from 'react';
import { useParams, useRouter } from 'next/navigation';
import ChatView from '@/components/ChatView';
import ConfirmDialog from '@/components/ConfirmDialog';
import ConversationSidebar, {
  getConversationDisplayTitle,
} from '@/components/ConversationSidebar';
import { useApi } from '@/hooks/useApi';
import { useAppState } from '@/hooks/useAppState';
import type {
  Checkout,
  ConversationEvent,
  ConversationHead,
  EvidenceRef,
  Message,
  RepositoryDefinition,
} from '@/types/api';

function hydrateMessages(events: ConversationEvent[]): Message[] {
  return events.reduce<Message[]>((messages, event) => {
    if (event.type === 'user.message.created') {
      const content = typeof event.payload.message === 'string' ? event.payload.message : '';
      messages.push({
        id: event.event_id,
        role: 'user',
        content,
      });
      return messages;
    }

    if (event.type === 'assistant.message.created') {
      const content =
        typeof event.payload.answer_markdown === 'string' ? event.payload.answer_markdown : '';
      const citations = Array.isArray(event.payload.citations)
        ? (event.payload.citations as EvidenceRef[])
        : [];
      const followups = Array.isArray(event.payload.followups)
        ? event.payload.followups.filter((item): item is string => typeof item === 'string')
        : [];

      messages.push({
        id: event.event_id,
        role: 'assistant',
        content,
        citations,
        followups,
      });
    }

    return messages;
  }, []);
}

export default function ChatPage() {
  const params = useParams<{ conversationId: string }>();
  const router = useRouter();
  const api = useApi();
  const {
    clearMessages,
    replaceMessages,
    setChatError,
    setConversationContext,
    setIsLoading,
    setPendingApproval,
    setWorkspace,
  } = useAppState();

  const conversationId = params.conversationId;
  const [conversation, setConversation] = useState<ConversationHead | null>(null);
  const [scopedConversations, setScopedConversations] = useState<ConversationHead[]>([]);
  const [repo, setRepo] = useState<RepositoryDefinition | null>(null);
  const [checkout, setCheckout] = useState<Checkout | null>(null);
  const [pageLoading, setPageLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isCreatingConversation, setIsCreatingConversation] = useState(false);
  const [mutatingConversationId, setMutatingConversationId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ConversationHead | null>(null);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [isNavigating, startNavigation] = useTransition();

  useEffect(() => {
    if (!conversationId) {
      return;
    }

    let cancelled = false;

    async function load() {
      try {
        setPageLoading(true);
        setPageError(null);
        setSidebarOpen(false);
        setDeleteTarget(null);
        setIsEditingTitle(false);
        setConversation(null);
        setRepo(null);
        setCheckout(null);
        setChatError(null);
        setPendingApproval(null);
        setIsLoading(false);
        clearMessages();

        const [head, events] = await Promise.all([
          api.getConversation(conversationId),
          api.listConversationEvents(conversationId),
        ]);

        if (cancelled) {
          return;
        }

        setConversation(head);
        setConversationContext(
          head.conversation_id,
          head.repo_def_id || undefined,
          head.checkout_id || undefined
        );
        if (head.workspace_id && head.latest_snapshot_id) {
          setWorkspace(head.workspace_id, head.latest_snapshot_id);
        }
        replaceMessages(hydrateMessages(events));

        const [repoResult, checkoutResult, scopedConversationsResult] = await Promise.allSettled([
          head.repo_def_id ? api.getRepoDefinition(head.repo_def_id) : Promise.resolve(null),
          head.checkout_id ? api.getCheckout(head.checkout_id) : Promise.resolve(null),
          head.repo_def_id
            ? api.listConversations(head.repo_def_id, head.checkout_id || undefined)
            : Promise.resolve({
                tenant_id: head.tenant_id,
                conversations: [head],
              }),
        ]);

        if (cancelled) {
          return;
        }

        setRepo(repoResult.status === 'fulfilled' ? repoResult.value : null);
        setCheckout(checkoutResult.status === 'fulfilled' ? checkoutResult.value : null);
        setScopedConversations(
          ensureConversationInList(
            scopedConversationsResult.status === 'fulfilled'
              ? scopedConversationsResult.value.conversations
              : [],
            head
          )
        );
      } catch (error) {
        if (cancelled) {
          return;
        }

        setPageError(error instanceof Error ? error.message : 'Failed to load conversation');
        router.push('/dashboard');
      } finally {
        if (!cancelled) {
          setPageLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [
    api,
    clearMessages,
    conversationId,
    replaceMessages,
    router,
    setChatError,
    setConversationContext,
    setIsLoading,
    setPendingApproval,
    setWorkspace,
  ]);

  useEffect(() => {
    if (!isEditingTitle) {
      setTitleDraft(conversation?.title ?? '');
    }
  }, [conversation?.conversation_id, conversation?.title, isEditingTitle]);

  const repoLabel = useMemo(() => {
    if (repo) {
      return repo.name || repo.endpoint;
    }
    return conversation?.repo_def_id || 'Repository';
  }, [conversation?.repo_def_id, repo]);

  const branchLabel = useMemo(() => {
    if (checkout?.branch) {
      return checkout.branch;
    }
    if (conversation?.checkout_id) {
      return `Checkout ${conversation.checkout_id.slice(0, 8)}`;
    }
    return null;
  }, [checkout?.branch, conversation?.checkout_id]);

  const sidebarCheckoutLabel = useMemo(() => {
    if (checkout) {
      return `${checkout.branch} @ ${checkout.commit_sha.slice(0, 7)}`;
    }
    if (conversation?.checkout_id) {
      return `Checkout ${conversation.checkout_id.slice(0, 8)}`;
    }
    return null;
  }, [checkout, conversation?.checkout_id]);

  const createdLabel = useMemo(() => {
    if (!conversation) {
      return null;
    }

    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    }).format(new Date(conversation.created_at));
  }, [conversation]);

  const routeToConversation = useCallback(
    (nextConversationId: string, replaceHistory: boolean = false) => {
      setSidebarOpen(false);
      setDeleteTarget(null);
      setIsEditingTitle(false);
      setPageLoading(true);
      setConversation(null);
      setRepo(null);
      setCheckout(null);
      clearMessages();
      startNavigation(() => {
        if (replaceHistory) {
          router.replace(`/chat/${nextConversationId}`);
        } else {
          router.push(`/chat/${nextConversationId}`);
        }
      });
    },
    [clearMessages, router]
  );

  const applyConversationUpdate = useCallback((updated: ConversationHead) => {
    setConversation((current) =>
      current?.conversation_id === updated.conversation_id ? updated : current
    );
    setScopedConversations((current) => upsertConversation(current, updated));
  }, []);

  const handleCreateConversation = useCallback(async () => {
    if (!conversation?.repo_def_id) {
      return;
    }

    setIsCreatingConversation(true);
    setPageError(null);

    try {
      const created = await api.createConversation({
        tenant_id: conversation.tenant_id,
        repo_def_id: conversation.repo_def_id,
        checkout_id: conversation.checkout_id || null,
        workspace_id: conversation.workspace_id,
      });

      routeToConversation(created.conversation_id);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Failed to create conversation');
    } finally {
      setIsCreatingConversation(false);
    }
  }, [api, conversation, routeToConversation]);

  const handleSelectConversation = useCallback(
    (target: ConversationHead) => {
      if (target.conversation_id === conversationId) {
        setSidebarOpen(false);
        return;
      }

      routeToConversation(target.conversation_id);
    },
    [conversationId, routeToConversation]
  );

  const handleRenameConversation = useCallback(
    async (target: ConversationHead, title: string | null) => {
      setMutatingConversationId(target.conversation_id);
      setPageError(null);

      try {
        const updated = await api.updateConversation(target.conversation_id, {
          title,
        });
        applyConversationUpdate(updated);
        if (updated.conversation_id === conversationId) {
          setIsEditingTitle(false);
        }
      } catch (error) {
        setPageError(error instanceof Error ? error.message : 'Failed to rename conversation');
        throw error;
      } finally {
        setMutatingConversationId(null);
      }
    },
    [api, applyConversationUpdate, conversationId]
  );

  const handleSaveTitle = useCallback(async () => {
    if (!conversation) {
      return;
    }

    try {
      await handleRenameConversation(
        conversation,
        titleDraft.trim() ? titleDraft.trim() : null
      );
    } catch {
      return;
    }
  }, [conversation, handleRenameConversation, titleDraft]);

  const handleTogglePinConversation = useCallback(
    async (target: ConversationHead) => {
      setMutatingConversationId(target.conversation_id);
      setPageError(null);

      try {
        const updated = await api.updateConversation(target.conversation_id, {
          pinned: !target.pinned_at,
        });
        applyConversationUpdate(updated);
      } catch (error) {
        setPageError(error instanceof Error ? error.message : 'Failed to update conversation');
      } finally {
        setMutatingConversationId(null);
      }
    },
    [api, applyConversationUpdate]
  );

  const handleDeleteConversation = useCallback((target: ConversationHead) => {
    setDeleteTarget(target);
  }, []);

  const handleConfirmDelete = useCallback(async () => {
    if (!deleteTarget) {
      return;
    }

    const target = deleteTarget;
    setMutatingConversationId(target.conversation_id);
    setPageError(null);

    try {
      await api.deleteConversation(target.conversation_id);
      const remaining = scopedConversations.filter(
        (conversationEntry) => conversationEntry.conversation_id !== target.conversation_id
      );
      setScopedConversations(remaining);
      setDeleteTarget(null);

      if (target.conversation_id === conversationId) {
        setConversation(null);
        if (remaining.length > 0) {
          routeToConversation(remaining[0].conversation_id, true);
        } else {
          clearMessages();
          startNavigation(() => {
            router.replace('/dashboard');
          });
        }
      }
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Failed to delete conversation');
    } finally {
      setMutatingConversationId(null);
    }
  }, [
    api,
    clearMessages,
    conversationId,
    deleteTarget,
    routeToConversation,
    router,
    scopedConversations,
  ]);

  return (
    <div className="flex h-screen overflow-hidden bg-cream">
      <ConversationSidebar
        scopeLabel={repoLabel}
        scopeSubLabel={sidebarCheckoutLabel}
        currentConversationId={conversationId}
        conversations={scopedConversations}
        isCreatingConversation={isCreatingConversation}
        isOpen={sidebarOpen}
        busyConversationId={mutatingConversationId}
        onClose={() => setSidebarOpen(false)}
        onCreateConversation={handleCreateConversation}
        onDeleteConversation={handleDeleteConversation}
        onRenameConversation={handleRenameConversation}
        onSelectConversation={handleSelectConversation}
        onTogglePinConversation={handleTogglePinConversation}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 border-b border-line bg-panel/95 backdrop-blur">
          <div className="flex items-start gap-3 px-4 py-4 sm:px-6">
            <div className="flex items-center gap-2">
              <Link
                href="/dashboard"
                className="rounded-2xl border border-line bg-cream p-2.5 text-muted transition hover:border-accent/20 hover:text-ink"
                aria-label="Back to dashboard"
              >
                <ArrowLeftIcon />
              </Link>
              <button
                type="button"
                onClick={() => setSidebarOpen(true)}
                className="rounded-2xl border border-line bg-cream p-2.5 text-muted transition hover:border-accent/20 hover:text-ink md:hidden"
                aria-label="Open conversations sidebar"
              >
                <SidebarIcon />
              </button>
            </div>

            <div className="min-w-0 flex-1">
              {isEditingTitle && conversation ? (
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                  <input
                    autoFocus
                    type="text"
                    value={titleDraft}
                    onChange={(event) => setTitleDraft(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault();
                        void handleSaveTitle();
                      }
                      if (event.key === 'Escape') {
                        event.preventDefault();
                        setIsEditingTitle(false);
                        setTitleDraft(conversation.title ?? '');
                      }
                    }}
                    className="w-full rounded-2xl border border-line bg-cream px-4 py-2.5 text-sm text-ink outline-none focus:border-accent"
                    placeholder="Conversation title"
                  />
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        void handleSaveTitle();
                      }}
                      disabled={mutatingConversationId === conversation.conversation_id}
                      className="rounded-2xl bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setIsEditingTitle(false);
                        setTitleDraft(conversation.title ?? '');
                      }}
                      className="rounded-2xl border border-line bg-cream px-4 py-2 text-sm font-medium text-ink transition hover:bg-line/40"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-2">
                    <h1 className="truncate text-lg font-semibold text-ink sm:text-xl">
                      {conversation ? getConversationDisplayTitle(conversation) : 'Loading conversation'}
                    </h1>
                    {isNavigating && (
                      <span className="rounded-full bg-accent/10 px-2 py-1 text-xs font-medium text-accent">
                        Switching...
                      </span>
                    )}
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
                    <ScopePill label={repoLabel} />
                    {branchLabel && <ScopePill label={branchLabel} />}
                    {createdLabel && <ScopePill label={`Created ${createdLabel}`} />}
                  </div>
                </>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-end gap-2">
              <button
                type="button"
                onClick={handleCreateConversation}
                disabled={!conversation?.repo_def_id || isCreatingConversation}
                className="rounded-2xl border border-line bg-cream px-3 py-2 text-sm font-medium text-ink transition hover:border-accent/20 hover:text-accent disabled:cursor-not-allowed disabled:opacity-60"
              >
                New
              </button>
              <button
                type="button"
                onClick={() => conversation && void handleTogglePinConversation(conversation)}
                disabled={!conversation || mutatingConversationId === conversation.conversation_id}
                className="rounded-2xl border border-line bg-cream px-3 py-2 text-sm font-medium text-ink transition hover:border-accent/20 hover:text-accent disabled:cursor-not-allowed disabled:opacity-60"
              >
                {conversation?.pinned_at ? 'Unpin' : 'Pin'}
              </button>
              <button
                type="button"
                onClick={() => setIsEditingTitle(true)}
                disabled={!conversation}
                className="rounded-2xl border border-line bg-cream px-3 py-2 text-sm font-medium text-ink transition hover:border-accent/20 hover:text-accent disabled:cursor-not-allowed disabled:opacity-60"
              >
                Rename
              </button>
              <button
                type="button"
                onClick={() => conversation && setDeleteTarget(conversation)}
                disabled={!conversation}
                className="rounded-2xl border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Delete
              </button>
            </div>
          </div>
        </header>

        {pageError && (
          <div className="border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 sm:px-6">
            {pageError}
          </div>
        )}

        <main className="min-h-0 flex-1 overflow-hidden">
          {pageLoading ? (
            <div className="flex h-full items-center justify-center px-6">
              <div className="w-full max-w-2xl rounded-3xl border border-line bg-panel p-10 text-center shadow-sm">
                <p className="text-sm font-medium text-ink">Loading conversation...</p>
                <p className="mt-2 text-sm text-muted">
                  Restoring the transcript, workspace context, and scoped conversation list.
                </p>
              </div>
            </div>
          ) : (
            <ChatView />
          )}
        </main>
      </div>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete conversation"
        message={`Delete "${deleteTarget ? getConversationDisplayTitle(deleteTarget) : ''}"? This removes it from your conversation list for this repository scope.`}
        confirmLabel="Delete conversation"
        onConfirm={() => {
          void handleConfirmDelete();
        }}
        onCancel={() => setDeleteTarget(null)}
        destructive
        isLoading={Boolean(deleteTarget && mutatingConversationId === deleteTarget.conversation_id)}
      />
    </div>
  );
}

function ensureConversationInList(
  conversations: ConversationHead[],
  currentConversation: ConversationHead
): ConversationHead[] {
  return conversations.some(
    (conversation) => conversation.conversation_id === currentConversation.conversation_id
  )
    ? conversations
    : [currentConversation, ...conversations];
}

function upsertConversation(
  conversations: ConversationHead[],
  updatedConversation: ConversationHead
): ConversationHead[] {
  const next = conversations.map((conversation) =>
    conversation.conversation_id === updatedConversation.conversation_id
      ? updatedConversation
      : conversation
  );

  if (
    next.some((conversation) => conversation.conversation_id === updatedConversation.conversation_id)
  ) {
    return next;
  }

  return [updatedConversation, ...next];
}

function ScopePill({ label }: { label: string }) {
  return (
    <span className="rounded-full border border-line bg-cream px-2.5 py-1 text-xs font-medium text-muted">
      {label}
    </span>
  );
}

function ArrowLeftIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5" aria-hidden="true">
      <path
        d="M11.667 4.167L5.833 10L11.667 15.833M6.667 10H15.833"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SidebarIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" className="h-5 w-5" aria-hidden="true">
      <path
        d="M5 5.833H15M5 10H15M5 14.167H10.833"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
