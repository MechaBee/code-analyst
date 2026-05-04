'use client';

import { useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import ChatView from '@/components/ChatView';
import NavBar from '@/components/NavBar';
import { useApi } from '@/hooks/useApi';
import { useAppState } from '@/hooks/useAppState';
import type { ConversationEvent, EvidenceRef, Message } from '@/types/api';

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
        typeof event.payload.answer_markdown === 'string'
          ? event.payload.answer_markdown
          : '';
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
  const params = useParams();
  const router = useRouter();
  const api = useApi();
  const {
    setConversationContext,
    setWorkspace,
    replaceMessages,
    setPendingApproval,
    setIsLoading,
    setChatError,
  } = useAppState();

  const convId = params.conversationId as string;

  useEffect(() => {
    if (!convId) return;

    let cancelled = false;

    async function load() {
      try {
        setChatError(null);
        setPendingApproval(null);
        setIsLoading(false);

        const [conv, events] = await Promise.all([
          api.getConversation(convId),
          api.listConversationEvents(convId),
        ]);
        if (cancelled) return;

        setConversationContext(
          conv.conversation_id,
          conv.repo_def_id || undefined,
          conv.checkout_id || undefined
        );
        if (conv.workspace_id && conv.latest_snapshot_id) {
          setWorkspace(conv.workspace_id, conv.latest_snapshot_id);
        }
        replaceMessages(hydrateMessages(events));
      } catch (err) {
        if (cancelled) return;
        setChatError(err instanceof Error ? err.message : 'Failed to load conversation');
        router.push('/dashboard');
      }
    }
    load();

    return () => {
      cancelled = true;
    };
  }, [
    convId,
    api,
    setConversationContext,
    setWorkspace,
    replaceMessages,
    setPendingApproval,
    setIsLoading,
    setChatError,
    router,
  ]);

  return (
    <div className="flex h-screen flex-col">
      <NavBar active="dashboard" />
      <div className="min-h-0 flex-1 overflow-hidden">
        <ChatView />
      </div>
    </div>
  );
}
