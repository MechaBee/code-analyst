'use client';

import { useAppState } from '@/hooks/useAppState';
import WorkspaceImport from '@/components/WorkspaceImport';
import ChatView from '@/components/ChatView';

export default function Home() {
  const { currentView } = useAppState();

  return (
    <main>
      {currentView === 'import' ? <WorkspaceImport /> : <ChatView />}
    </main>
  );
}
