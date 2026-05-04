'use client';

import React from 'react';
import { cn } from '@/lib/utils';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  destructive?: boolean;
  isLoading?: boolean;
}

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  onConfirm,
  onCancel,
  destructive = false,
  isLoading = false,
}: ConfirmDialogProps) {
  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-3xl border border-line bg-panel p-6 shadow-lg">
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">{message}</p>
        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={isLoading}
            className="rounded-2xl border border-line bg-cream px-4 py-2 text-sm font-medium text-ink transition hover:bg-line/40 disabled:cursor-not-allowed disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isLoading}
            className={cn(
              'rounded-2xl px-4 py-2 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-60',
              destructive ? 'bg-red-600 hover:bg-red-700' : 'bg-accent hover:bg-accent/90'
            )}
          >
            {isLoading ? 'Working...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
