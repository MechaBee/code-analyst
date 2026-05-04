'use client';

import { AuthProvider } from '@/hooks/useAuth';
import { AppStateProvider } from '@/hooks/useAppState';

export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AppStateProvider>{children}</AppStateProvider>
    </AuthProvider>
  );
}
