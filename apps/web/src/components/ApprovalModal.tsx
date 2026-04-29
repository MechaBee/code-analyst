'use client';

import React from 'react';
import type { EvidenceRef, RunEvent } from '@/types/api';

interface ApprovalModalProps {
  runId: string;
  approvalId: string;
  message: string;
  onDecision: (decision: 'approve' | 'deny') => void;
  onClose: () => void;
}

export default function ApprovalModal({ runId, approvalId, message, onDecision, onClose }: ApprovalModalProps) {
  const handleDecision = (decision: 'approve' | 'deny') => {
    onDecision(decision);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-line bg-panel p-6 shadow-lg">
        <h2 className="mb-2 text-lg font-semibold text-ink">Approval Required</h2>
        <p className="mb-4 text-sm text-muted">
          This question requires approval before execution.
        </p>
        <div className="mb-6 rounded-lg bg-cream p-3 text-sm text-ink">
          {message}
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => handleDecision('deny')}
            className="flex-1 rounded-lg border border-line bg-cream px-4 py-2.5 text-sm font-medium text-ink transition hover:bg-line/50"
          >
            Deny
          </button>
          <button
            onClick={() => handleDecision('approve')}
            className="flex-1 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-accent/90 active:scale-[0.98]"
          >
            Approve
          </button>
        </div>
      </div>
    </div>
  );
}
