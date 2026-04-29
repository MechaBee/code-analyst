'use client';

import { AppStateProvider } from '@/hooks/useAppState';

export default function Providers({ children }: { children: React.ReactNode }) {
  return <AppStateProvider>{children}</AppStateProvider>;
}
