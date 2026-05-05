'use client';

import React, { useCallback, useEffect, useRef } from 'react';
import { useAppState } from '@/hooks/useAppState';
import MessageBubble from './MessageBubble';
import ApprovalModal from './ApprovalModal';
import SourcePreviewDrawer from './SourcePreviewDrawer';
import { cn, generateId } from '@/lib/utils';
import { useApi } from '@/hooks/useApi';
import { useRunEvents } from '@/hooks/useEventSource';
import type { CitationPreviewResponse, EvidenceRef, RunEvent, Message } from '@/types/api';

interface ChatViewProps {
  canAutoTitle: boolean;
  onAutoTitleCandidate?: (candidate: string) => void | Promise<void>;
}

export default function ChatView({ canAutoTitle, onAutoTitleCandidate }: ChatViewProps) {
  const {
    messages,
    conversationId,
    snapshotId,
    isLoading,
    pendingApproval,
    chatError,
    addMessage,
    appendStatusUpdateToLastAssistant,
    updateLastAssistantMessage,
    setPendingApproval,
    setIsLoading,
    setChatError,
  } = useAppState();

  const api = useApi();
  const { subscribe } = useRunEvents();
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [inputValue, setInputValue] = React.useState('');
  const [isComposerFocused, setIsComposerFocused] = React.useState(false);
  const [activeCitationKey, setActiveCitationKey] = React.useState<string | null>(null);
  const [sourcePreviewOpen, setSourcePreviewOpen] = React.useState(false);
  const [sourcePreviewLoading, setSourcePreviewLoading] = React.useState(false);
  const [sourcePreviewError, setSourcePreviewError] = React.useState<string | null>(null);
  const [sourcePreview, setSourcePreview] = React.useState<CitationPreviewResponse | null>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  useEffect(() => {
    const composer = composerRef.current;
    if (!composer) {
      return;
    }

    composer.style.height = '0px';
    composer.style.height = `${Math.min(composer.scrollHeight, 192)}px`;
  }, [inputValue]);

  useEffect(() => {
    setInputValue('');
    setSourcePreviewOpen(false);
    setSourcePreviewLoading(false);
    setSourcePreviewError(null);
    setSourcePreview(null);
    setActiveCitationKey(null);
  }, [conversationId]);

  const handleEventSubscription = useCallback(
    (runId: string) => {
      subscribe(runId, {
        onProgress: (event: RunEvent) => {
          const message = event.payload.message;
          if (message) {
            appendStatusUpdateToLastAssistant(message);
          }
        },
        onApproval: (event: RunEvent) => {
          setPendingApproval({
            runId,
            approvalId: event.payload.approval_id || '',
            message: event.payload.message || 'Approval required',
          });
          setIsLoading(false);
        },
        onCompleted: (event: RunEvent) => {
          const answer = event.payload.answer_markdown || '';
          const citations = (event.payload.citations || []) as EvidenceRef[];
          const followups = (event.payload.followups || []) as string[];

          updateLastAssistantMessage((msg: Message) => ({
            ...msg,
            content: answer,
            isLoading: false,
            citations,
            followups,
            statusUpdates: [],
          }));
          setIsLoading(false);
          setPendingApproval(null);
        },
        onFailed: (event: RunEvent) => {
          const message = event.payload.message || 'Run failed';
          updateLastAssistantMessage((msg: Message) => ({
            ...msg,
            content: `**Error:** ${message}`,
            isLoading: false,
            error: true,
            statusUpdates: [],
          }));
          setIsLoading(false);
          setPendingApproval(null);
        },
        onError: () => {
          setIsLoading(false);
        },
      });
    },
    [appendStatusUpdateToLastAssistant, setIsLoading, setPendingApproval, subscribe, updateLastAssistantMessage]
  );

  const sendMessage = useCallback(
    async (text: string): Promise<boolean> => {
      const userMessage = text.trim();
      if (!userMessage || !conversationId || isLoading || pendingApproval) {
        return false;
      }

      const shouldAutoTitle = canAutoTitle && !messages.some((message) => message.role === 'user');

      setChatError(null);
      setIsLoading(true);

      addMessage({
        id: generateId('msg'),
        role: 'user',
        content: userMessage,
      });

      addMessage({
        id: generateId('msg'),
        role: 'assistant',
        content: '',
        isLoading: true,
        statusUpdates: [],
      });

      try {
        const questionRes = await api.askQuestion(conversationId, {
          message: userMessage,
          workspace_snapshot_id: snapshotId,
          resume_sandbox: true,
          approval_policy: 'auto',
        });

        if (shouldAutoTitle) {
          void onAutoTitleCandidate?.(userMessage);
        }
        handleEventSubscription(questionRes.run_id);
        return true;
      } catch (err) {
        setChatError(err instanceof Error ? err.message : 'Failed to send question');
        updateLastAssistantMessage((msg: Message) => ({
          ...msg,
          content: '**Error:** Failed to send question',
          isLoading: false,
          error: true,
          statusUpdates: [],
        }));
        setIsLoading(false);
        return false;
      }
    },
    [
      addMessage,
      api,
      canAutoTitle,
      conversationId,
      handleEventSubscription,
      isLoading,
      messages,
      onAutoTitleCandidate,
      pendingApproval,
      setChatError,
      setIsLoading,
      snapshotId,
      updateLastAssistantMessage,
    ]
  );

  const handleComposerSend = useCallback(async () => {
    const draft = inputValue;
    if (!draft.trim()) {
      return;
    }

    setInputValue('');
    const sent = await sendMessage(draft);
    if (!sent) {
      setInputValue(draft);
    }
  }, [inputValue, sendMessage]);

  const handleApprovalDecision = useCallback(
    async (decision: 'approve' | 'deny') => {
      if (!pendingApproval) return;

      setIsLoading(true);
      setChatError(null);

      try {
        await api.resolveApproval(pendingApproval.runId, pendingApproval.approvalId, {
          decision,
          reason: decision === 'approve' ? 'Approved by user' : 'Denied by user',
        });

        if (decision === 'approve') {
          addMessage({
            id: generateId('msg'),
            role: 'assistant',
            content: '',
            isLoading: true,
            statusUpdates: ['Resuming execution...'],
          });
          handleEventSubscription(pendingApproval.runId);
        } else {
          addMessage({
            id: generateId('msg'),
            role: 'assistant',
            content: '**Denied:** Execution was denied by user.',
            isLoading: false,
            error: true,
          });
          setIsLoading(false);
        }

        setPendingApproval(null);
      } catch (err) {
        setChatError(err instanceof Error ? err.message : 'Approval action failed');
        setIsLoading(false);
      }
    },
    [addMessage, api, handleEventSubscription, pendingApproval, setChatError, setIsLoading, setPendingApproval]
  );

  const handleCitationClick = useCallback(
    async (citation: EvidenceRef) => {
      if (!conversationId) {
        return;
      }

      const citationKey = `${citation.snapshot_id}:${citation.path}:${citation.start_line}:${citation.end_line}`;
      setSourcePreviewOpen(true);
      setSourcePreviewLoading(true);
      setSourcePreviewError(null);
      setActiveCitationKey(citationKey);

      try {
        const preview = await api.getCitationPreview(conversationId, {
          snapshotId: citation.snapshot_id,
          path: citation.path,
          startLine: citation.start_line,
          endLine: citation.end_line,
        });
        setSourcePreview(preview);
      } catch (error) {
        setSourcePreview(null);
        setSourcePreviewError(
          error instanceof Error ? error.message : 'Failed to load cited source preview'
        );
      } finally {
        setSourcePreviewLoading(false);
        setActiveCitationKey(null);
      }
    },
    [api, conversationId]
  );

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void handleComposerSend();
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-cream">
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-8 sm:px-6"
      >
        <div className="mx-auto flex w-full max-w-[74rem] flex-col gap-8">
          {messages.length === 0 && (
            <div className="px-1 py-12 text-center">
              <p className="text-lg font-medium text-ink">Ready to analyze</p>
              <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-muted">
                Ask for architecture walkthroughs, code tracing, debugging help, refactors, or
                implementation plans for this checkout.
              </p>
            </div>
          )}
          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              onFollowupClick={(followup) => {
                void sendMessage(followup);
              }}
              onCitationClick={handleCitationClick}
              activeCitationKey={activeCitationKey}
            />
          ))}
          {isLoading && messages[messages.length - 1]?.role !== 'assistant' && (
            <MessageBubble
              message={{
                id: generateId('msg'),
                role: 'assistant',
                content: '',
                isLoading: true,
                statusUpdates: [],
              }}
            />
          )}
        </div>
      </div>

      <div className="border-t border-line bg-panel px-4 py-4 sm:px-6">
        <div className="mx-auto max-w-[74rem]">
          <div className="rounded-[28px] border border-line bg-cream px-4 py-3 shadow-sm">
            <textarea
              ref={composerRef}
              aria-label="Message composer"
              aria-describedby="composer-hint"
              rows={1}
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
              onKeyDown={handleKeyDown}
              onFocus={() => setIsComposerFocused(true)}
              onBlur={() => setIsComposerFocused(false)}
              disabled={isLoading || !!pendingApproval}
              placeholder={
                pendingApproval
                  ? 'Waiting for approval...'
                  : isLoading
                  ? 'Thinking...'
                  : 'Ask a question about the codebase, request a change, or ask for a walkthrough...'
              }
              className={cn(
                'max-h-48 min-h-[44px] w-full resize-none bg-transparent px-1 py-1 text-[15px] leading-7 text-ink outline-none transition',
                'placeholder:text-muted/60',
                (isLoading || pendingApproval) && 'cursor-not-allowed opacity-60'
              )}
            />
            <div className="mt-3 flex items-center justify-between gap-3 border-t border-line pt-3">
              <p
                id="composer-hint"
                className={cn(
                  'text-xs text-muted transition',
                  isComposerFocused ? 'opacity-100' : 'opacity-0'
                )}
              >
                Enter to send · Shift+Enter for a new line
              </p>
              <button
                onClick={() => {
                  void handleComposerSend();
                }}
                disabled={isLoading || !!pendingApproval || !inputValue.trim()}
                className={cn(
                  'rounded-2xl px-5 py-2.5 text-sm font-semibold text-white transition',
                  isLoading || !!pendingApproval || !inputValue.trim()
                    ? 'cursor-not-allowed bg-accent/60'
                    : 'bg-accent hover:bg-accent/90 active:scale-[0.98]'
                )}
              >
                Send
              </button>
            </div>
          </div>
        </div>
        {chatError && (
          <div className="mx-auto mt-2 max-w-[74rem] text-xs text-red-600">
            {chatError}
          </div>
        )}
      </div>

      {pendingApproval && (
        <ApprovalModal
          runId={pendingApproval.runId}
          approvalId={pendingApproval.approvalId}
          message={pendingApproval.message}
          onDecision={handleApprovalDecision}
          onClose={() => setPendingApproval(null)}
        />
      )}

      <SourcePreviewDrawer
        open={sourcePreviewOpen}
        preview={sourcePreview}
        loading={sourcePreviewLoading}
        error={sourcePreviewError}
        onClose={() => setSourcePreviewOpen(false)}
      />
    </div>
  );
}
