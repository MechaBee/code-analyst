'use client';

import React from 'react';
import Link from 'next/link';
import { useAuth } from '@/hooks/useAuth';
import { cn } from '@/lib/utils';

interface NavBarProps {
  active?: 'dashboard' | 'repos' | 'admin';
}

export default function NavBar({ active }: NavBarProps) {
  const { email, isAdmin, logout } = useAuth();

  const navItem = (href: string, label: string, key?: string) => (
    <Link
      href={href}
      className={cn(
        'text-sm font-medium transition',
        active === key ? 'text-accent' : 'text-muted hover:text-ink'
      )}
    >
      {label}
    </Link>
  );

  return (
    <header className="border-b border-line bg-panel px-6 py-3">
      <div className="mx-auto flex max-w-6xl items-center justify-between">
        <div className="flex items-center gap-6">
          <Link href="/dashboard" className="text-lg font-bold text-ink">
            Code Analyst
          </Link>
          <nav className="flex items-center gap-4">
            {navItem('/dashboard', 'Dashboard', 'dashboard')}
            {navItem('/repos', 'Repositories', 'repos')}
            {isAdmin && navItem('/admin', 'Admin', 'admin')}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted">{email}</span>
          <button
            onClick={logout}
            className="rounded-md px-2 py-1 text-xs font-medium text-muted transition hover:text-ink"
          >
            Logout
          </button>
        </div>
      </div>
    </header>
  );
}
