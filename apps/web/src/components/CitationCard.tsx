'use client';

import React from 'react';
import type { EvidenceRef } from '@/types/api';

interface CitationCardProps {
  citation: EvidenceRef;
}

export default function CitationCard({ citation }: CitationCardProps) {
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1.5 rounded-md border border-line bg-cream px-2.5 py-1 text-xs font-medium text-accent transition hover:border-accent/30 hover:bg-accent/5"
      title={`${citation.path} lines ${citation.start_line}-${citation.end_line}`}
      onClick={() => {
        // MVP: no file viewer, just show path in console
        // eslint-disable-next-line no-console
        console.log('Citation:', citation);
      }}
    >
      <span className="max-w-[200px] truncate">{citation.path}</span>
      <span className="text-muted">L{citation.start_line}-{citation.end_line}</span>
    </button>
  );
}
