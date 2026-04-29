import { useEffect, useRef, useCallback } from 'react';
import type { RunEvent } from '@/types/api';

export interface EventHandlers {
  onStarted?: (event: RunEvent) => void;
  onProgress?: (event: RunEvent) => void;
  onCitation?: (event: RunEvent) => void;
  onApproval?: (event: RunEvent) => void;
  onCompleted?: (event: RunEvent) => void;
  onFailed?: (event: RunEvent) => void;
  onError?: (error: Event) => void;
  onOpen?: () => void;
}

export function useRunEvents() {
  const activeSourceRef = useRef<EventSource | null>(null);

  const subscribe = useCallback((runId: string, handlers: EventHandlers) => {
    // Close any existing connection
    if (activeSourceRef.current) {
      activeSourceRef.current.close();
      activeSourceRef.current = null;
    }

    const es = new EventSource(`/api/v1/runs/${runId}/events`);
    activeSourceRef.current = es;

    es.addEventListener('open', () => {
      handlers.onOpen?.();
    });

    es.addEventListener('run.started', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as RunEvent;
        handlers.onStarted?.(data);
      } catch {
        // ignore parse errors
      }
    });

    es.addEventListener('run.progress', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as RunEvent;
        handlers.onProgress?.(data);
      } catch {
        // ignore
      }
    });

    es.addEventListener('citation.created', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as RunEvent;
        handlers.onCitation?.(data);
      } catch {
        // ignore
      }
    });

    es.addEventListener('approval.required', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as RunEvent;
        handlers.onApproval?.(data);
      } catch {
        // ignore
      }
    });

    es.addEventListener('run.completed', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as RunEvent;
        handlers.onCompleted?.(data);
        es.close();
        activeSourceRef.current = null;
      } catch {
        // ignore
      }
    });

    es.addEventListener('run.failed', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as RunEvent;
        handlers.onFailed?.(data);
        es.close();
        activeSourceRef.current = null;
      } catch {
        // ignore
      }
    });

    es.addEventListener('error', (e: Event) => {
      handlers.onError?.(e);
      // If the connection errors after being open, close it.
      // The backend replays stored events and then ends the stream,
      // which can trigger an error when the connection closes.
      es.close();
      activeSourceRef.current = null;
    });

    return () => {
      es.close();
      if (activeSourceRef.current === es) {
        activeSourceRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    return () => {
      if (activeSourceRef.current) {
        activeSourceRef.current.close();
        activeSourceRef.current = null;
      }
    };
  }, []);

  return { subscribe };
}
