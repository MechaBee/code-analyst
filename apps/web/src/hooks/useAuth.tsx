'use client';

import React, { createContext, useContext, useState, useEffect } from 'react';
import type { UserMeResponse } from '@/types/api';
import { useApi } from '@/hooks/useApi';

export interface AuthState {
  tenantId: string;
  email: string;
  name: string | null;
  isAdmin: boolean;
  isLoading: boolean;
  error: string | null;
}

interface AuthContextValue extends AuthState {
  refresh: () => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const api = useApi();
  const [state, setState] = useState<AuthState>({
    tenantId: '',
    email: '',
    name: null,
    isAdmin: false,
    isLoading: true,
    error: null,
  });

  const refresh = () => {
    setState((s) => ({ ...s, isLoading: true, error: null }));
    api
      .me()
      .then((me: UserMeResponse) => {
        setState({
          tenantId: me.tenant_id,
          email: me.email,
          name: me.name || null,
          isAdmin: me.is_admin,
          isLoading: false,
          error: null,
        });
      })
      .catch((err: Error) => {
        setState((s) => ({
          ...s,
          isLoading: false,
          error: err.message,
        }));
      });
  };

  const logout = () => {
    setState({
      tenantId: '',
      email: '',
      name: null,
      isAdmin: false,
      isLoading: false,
      error: null,
    });
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
