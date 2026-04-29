import type {
  WorkspaceImportRequest,
  WorkspaceImportResponse,
  ConversationCreateRequest,
  ConversationCreateResponse,
  QuestionRequest,
  QuestionResponse,
  ApprovalDecisionRequest,
  ApprovalDecisionResponse,
  HealthResponse,
} from '@/types/api';

const API_BASE = '/api';

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => 'Unknown error');
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export function useApi() {
  return {
    health: () => apiFetch<HealthResponse>('/health'),
    importWorkspace: (req: WorkspaceImportRequest) =>
      apiFetch<WorkspaceImportResponse>('/v1/workspaces/imports/github', {
        method: 'POST',
        body: JSON.stringify(req),
      }),
    createConversation: (req: ConversationCreateRequest) =>
      apiFetch<ConversationCreateResponse>('/v1/conversations', {
        method: 'POST',
        body: JSON.stringify(req),
      }),
    askQuestion: (conversationId: string, req: QuestionRequest) =>
      apiFetch<QuestionResponse>(`/v1/conversations/${conversationId}/questions`, {
        method: 'POST',
        body: JSON.stringify(req),
      }),
    resolveApproval: (runId: string, approvalId: string, req: ApprovalDecisionRequest) =>
      apiFetch<ApprovalDecisionResponse>(`/v1/runs/${runId}/approvals/${approvalId}`, {
        method: 'POST',
        body: JSON.stringify(req),
      }),
  };
}
