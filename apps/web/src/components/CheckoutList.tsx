'use client';

import React from 'react';
import type { Checkout } from '@/types/api';

interface CheckoutListProps {
  checkouts: Checkout[];
}

export default function CheckoutList({ checkouts }: CheckoutListProps) {
  if (checkouts.length === 0) {
    return <p className="text-sm text-muted">No checkouts yet.</p>;
  }

  return (
    <div className="space-y-2">
      {checkouts.map((chk) => (
        <div
          key={chk.checkout_id}
          className="flex items-center justify-between rounded-lg border border-line bg-panel px-3 py-2"
        >
          <div className="text-xs text-ink">
            <span className="font-medium">{chk.branch}</span>{' '}
            <span className="text-muted">@ {chk.commit_sha.slice(0, 8)}</span>
          </div>
          <div className="text-xs text-muted">
            {new Date(chk.run_timestamp).toLocaleString()}
          </div>
        </div>
      ))}
    </div>
  );
}
