import React, { createContext, useContext, useState, useCallback } from 'react';
import type { Message, EvidenceRef } from '@/types/api';

export type View = 'import' | 'chat';

export interface AppState {
  currentView: View;
  workspaceId: string | null;
  snapshotId: string | null;
  conversationId: string | null;
  repoDefId: string | null;
  checkoutId: string | null;
  principalEmail: string | null;
  messages: Message[];
  pendingApproval: { runId: string; approvalId: string; message: string } | null;
  isLoading: boolean;
  importError: string | null;
  chatError: string | null;
}

interface AppStateContextValue extends AppState {
  setView: (view: View) => void;
  setWorkspace: (workspaceId: string, snapshotId: string) => void;
  setConversationContext: (id: string, repoDefId?: string, checkoutId?: string) => void;
  setConversationId: (id: string | null) => void;
  replaceMessages: (messages: Message[]) => void;
  addMessage: (message: Message) => void;
  updateLastAssistantMessage: (updater: (msg: Message) => Message) => void;
  appendToLastAssistant: (text: string) => void;
  setCitationsForLastAssistant: (citations: EvidenceRef[], followups: string[]) => void;
  setPendingApproval: (approval: AppState['pendingApproval']) => void;
  setIsLoading: (loading: boolean) => void;
  setImportError: (error: string | null) => void;
  setChatError: (error: string | null) => void;
  clearMessages: () => void;
}

const AppStateContext = createContext<AppStateContextValue | undefined>(undefined);

export function AppStateProvider({ children }: { children: React.ReactNode }) {
  const [currentView, setView] = useState<View>('import');
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [snapshotId, setSnapshotId] = useState<string | null>(null);
  const [conversationId, setConversationIdState] = useState<string | null>(null);
  const [repoDefId, setRepoDefId] = useState<string | null>(null);
  const [checkoutId, setCheckoutId] = useState<string | null>(null);
  const [principalEmail, setPrincipalEmail] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [pendingApproval, setPendingApprovalState] = useState<AppState['pendingApproval']>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);

  const setWorkspace = useCallback((wid: string, sid: string) => {
    setWorkspaceId(wid);
    setSnapshotId(sid);
  }, []);

  const setConversationContext = useCallback((id: string, r?: string, c?: string) => {
    setConversationIdState(id);
    if (r !== undefined) setRepoDefId(r);
    if (c !== undefined) setCheckoutId(c);
  }, []);

  const setConversationId = useCallback((id: string | null) => {
    setConversationIdState(id);
  }, []);

  const replaceMessages = useCallback((nextMessages: Message[]) => {
    setMessages(nextMessages);
  }, []);

  const addMessage = useCallback((message: Message) => {
    setMessages((prev) => [...prev, message]);
  }, []);

  const updateLastAssistantMessage = useCallback((updater: (msg: Message) => Message) => {
    setMessages((prev) => {
      const lastIdx = prev.length - 1;
      if (lastIdx < 0) return prev;
      const last = prev[lastIdx];
      if (last.role !== 'assistant') return prev;
      const updated = updater(last);
      const next = prev.slice();
      next[lastIdx] = updated;
      return next;
    });
  }, []);

  const appendToLastAssistant = useCallback((text: string) => {
    updateLastAssistantMessage((msg) => ({
      ...msg,
      content: msg.content + text,
    }));
  }, [updateLastAssistantMessage]);

  const setCitationsForLastAssistant = useCallback((citations: EvidenceRef[], followups: string[]) => {
    updateLastAssistantMessage((msg) => ({
      ...msg,
      citations,
      followups,
    }));
  }, [updateLastAssistantMessage]);

  const setPendingApproval = useCallback((approval: AppState['pendingApproval']) => {
    setPendingApprovalState(approval);
  }, []);

  const setImportErrorFn = useCallback((error: string | null) => setImportError(error), []);
  const setChatErrorFn = useCallback((error: string | null) => setChatError(error), []);

  const clearMessages = useCallback(() => setMessages([]), []);

  return (
    <AppStateContext.Provider
      value={{
        currentView,
        workspaceId,
        snapshotId,
        conversationId,
        repoDefId,
        checkoutId,
        principalEmail,
        messages,
        pendingApproval,
        isLoading,
        importError,
        chatError,
        setView,
        setWorkspace,
        setConversationContext,
        setConversationId,
        replaceMessages,
        addMessage,
        updateLastAssistantMessage,
        appendToLastAssistant,
        setCitationsForLastAssistant,
        setPendingApproval,
        setIsLoading,
        setImportError: setImportErrorFn,
        setChatError: setChatErrorFn,
        clearMessages,
      }}
    >
      {children}
    </AppStateContext.Provider>
  );
}

export function useAppState(): AppStateContextValue {
  const ctx = useContext(AppStateContext);
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider');
  return ctx;
}
