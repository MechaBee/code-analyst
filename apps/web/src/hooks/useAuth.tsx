'use client';

import React, { createContext, useContext, useState, useEffect } from 'react';
import type { UserMeResponse } from '@/types/api';
import { useApi } from '@/hooks/useApi';

export interface AuthState {
  tenantId: string;
  email: string;
  name: string | null;
  isAdmin: boolean;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
}

interface AuthContextValue extends AuthState {
  refresh: () => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const api = useApi();
  const [state, setState] = useState<AuthState>({
    tenantId: '',
    email: '',
    name: null,
    isAdmin: false,
    isAuthenticated: false,
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
          isAuthenticated: true,
          isLoading: false,
          error: null,
        });
      })
      .catch((err: Error) => {
        if (err.message.startsWith('HTTP 401')) {
          setState({
            tenantId: '',
            email: '',
            name: null,
            isAdmin: false,
            isAuthenticated: false,
            isLoading: false,
            error: null,
          });
          return;
        }
        setState((s) => ({
          ...s,
          isAuthenticated: false,
          isLoading: false,
          error: err.message,
        }));
      });
  };

  const logout = async () => {
    try {
      await api.logout();
    } catch {
      // Ignore logout failures and clear local auth state anyway.
    }
    setState({
      tenantId: '',
      email: '',
      name: null,
      isAdmin: false,
      isAuthenticated: false,
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
