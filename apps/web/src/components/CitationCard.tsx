'use client';

import React from 'react';
import type { EvidenceRef } from '@/types/api';

interface CitationCardProps {
  citation: EvidenceRef;
  onClick?: (citation: EvidenceRef) => void;
  isLoading?: boolean;
}

export default function CitationCard({ citation, onClick, isLoading = false }: CitationCardProps) {
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1.5 rounded-xl border border-line bg-cream px-2.5 py-1.5 text-xs font-medium text-accent transition hover:border-accent/30 hover:bg-accent/5 disabled:cursor-wait disabled:opacity-70"
      title={`${citation.path} lines ${citation.start_line}-${citation.end_line}`}
      onClick={() => onClick?.(citation)}
      disabled={isLoading}
      data-testid="citation-card"
    >
      <span className="max-w-[200px] truncate">{citation.path}</span>
      <span className="text-muted">L{citation.start_line}-{citation.end_line}</span>
    </button>
  );
}
