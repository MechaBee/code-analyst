'use client';

import React, { useRef, useEffect, useCallback } from 'react';
import { useAppState } from '@/hooks/useAppState';
import MessageBubble from './MessageBubble';
import ApprovalModal from './ApprovalModal';
import { cn, generateId } from '@/lib/utils';
import { useApi } from '@/hooks/useApi';
import { useRunEvents } from '@/hooks/useEventSource';
import type { EvidenceRef, RunEvent, Message } from '@/types/api';

export default function ChatView() {
  const {
    messages,
    conversationId,
    workspaceId,
    snapshotId,
    isLoading,
    pendingApproval,
    chatError,
    addMessage,
    appendToLastAssistant,
    updateLastAssistantMessage,
    setPendingApproval,
    setIsLoading,
    setChatError,
  } = useAppState();

  const api = useApi();
  const { subscribe } = useRunEvents();
  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [inputValue, setInputValue] = React.useState('');
  const currentRunIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  const handleEventSubscription = useCallback((runId: string) => {
    currentRunIdRef.current = runId;

    subscribe(runId, {
      onProgress: (event: RunEvent) => {
        const msg = event.payload.message;
        if (msg) {
          appendToLastAssistant(`\n\n> ${msg}`);
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
        }));
        setIsLoading(false);
        setPendingApproval(null);
      },
      onError: () => {
        // SSE connection closed after replay ends
        setIsLoading(false);
      },
    });
  }, [subscribe, appendToLastAssistant, updateLastAssistantMessage, setPendingApproval, setIsLoading]);

  const handleSend = useCallback(async () => {
    if (!inputValue.trim() || !conversationId || isLoading || pendingApproval) return;

    const userMessage = inputValue.trim();
    setInputValue('');
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
    });

    try {
      const questionRes = await api.askQuestion(conversationId, {
        message: userMessage,
        workspace_snapshot_id: snapshotId,
        resume_sandbox: true,
        approval_policy: 'auto',
      });

      handleEventSubscription(questionRes.run_id);
    } catch (err) {
      setChatError(err instanceof Error ? err.message : 'Failed to send question');
      updateLastAssistantMessage((msg: Message) => ({
        ...msg,
        content: '**Error:** Failed to send question',
        isLoading: false,
        error: true,
      }));
      setIsLoading(false);
    }
  }, [
    inputValue,
    conversationId,
    snapshotId,
    isLoading,
    pendingApproval,
    api,
    handleEventSubscription,
    addMessage,
    updateLastAssistantMessage,
    setChatError,
    setIsLoading,
  ]);

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
          // Re-subscribe to events to receive the resumed run's completion
          addMessage({
            id: generateId('msg'),
            role: 'assistant',
            content: 'Resuming execution…',
            isLoading: true,
          });
          handleEventSubscription(pendingApproval.runId);
        } else {
          addMessage({
            id: generateId('msg'),
            role: 'assistant',
            content: `**Denied:** Execution was denied by user.`,
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
    [pendingApproval, api, handleEventSubscription, addMessage, setPendingApproval, setIsLoading, setChatError]
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex h-screen flex-col bg-cream">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-line bg-panel px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-accent" />
          <h1 className="text-base font-semibold text-ink">Code Analyst</h1>
        </div>
        <div className="text-xs text-muted">
          {workspaceId ? `Workspace: ${workspaceId.slice(0, 12)}…` : 'No workspace'}
        </div>
      </header>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-6 sm:px-6"
      >
        <div className="mx-auto flex max-w-3xl flex-col gap-5">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-center text-muted">
              <p className="text-lg font-medium text-ink">Ready to analyze</p>
              <p className="mt-1 text-sm">Ask a question about the imported repository.</p>
            </div>
          )}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          {isLoading && messages[messages.length - 1]?.role !== 'assistant' && (
            <MessageBubble
              message={{
                id: generateId('msg'),
                role: 'assistant',
                content: '',
                isLoading: true,
              }}
            />
          )}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-line bg-panel px-4 py-4 sm:px-6">
        <div className="mx-auto flex max-w-3xl gap-3">
          <input
            ref={inputRef}
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading || !!pendingApproval}
            placeholder={
              pendingApproval
                ? 'Waiting for approval...'
                : isLoading
                ? 'Thinking...'
                : 'Ask a question about the codebase...'
            }
            className={cn(
              'flex-1 rounded-xl border bg-cream px-4 py-3 text-sm text-ink outline-none transition',
              'placeholder:text-muted/60 focus:border-accent focus:ring-1 focus:ring-accent',
              (isLoading || pendingApproval) && 'cursor-not-allowed opacity-60',
              chatError ? 'border-red-400' : 'border-line'
            )}
          />
          <button
            onClick={handleSend}
            disabled={isLoading || !!pendingApproval || !inputValue.trim()}
            className={cn(
              'rounded-xl px-5 py-3 text-sm font-semibold text-white transition',
              isLoading || !!pendingApproval || !inputValue.trim()
                ? 'cursor-not-allowed bg-accent/60'
                : 'bg-accent hover:bg-accent/90 active:scale-[0.98]'
            )}
          >
            Send
          </button>
        </div>
        {chatError && (
          <div className="mx-auto mt-2 max-w-3xl text-xs text-red-600">
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
    </div>
  );
}
