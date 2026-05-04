import { useMemo } from 'react';

import type {
  ApprovalDecisionRequest,
  ApprovalDecisionResponse,
  AdminTeamListResponse,
  Checkout,
  CheckoutCreateRequest,
  CheckoutCreateResponse,
  CheckoutListResponse,
  ConversationCreateRequest,
  ConversationCreateResponse,
  ConversationEvent,
  ConversationHead,
  ConversationListResponse,
  ConversationUpdateRequest,
  HealthResponse,
  QuestionRequest,
  QuestionResponse,
  RepositoryDefinition,
  RepositoryDefinitionCreateRequest,
  RepositoryDefinitionCreateResponse,
  RepositoryDefinitionListResponse,
  RepositoryDefinitionUpdateTeamsRequest,
  RepositoryDefinitionUpdateTeamsResponse,
  TeamCreateRequest,
  TeamCreateResponse,
  TeamDetailResponse,
  TeamListResponse,
  TeamMemberAddRequest,
  TeamMemberAddResponse,
  TeamMemberRemoveResponse,
  UserCreateRequest,
  UserCreateResponse,
  UserListResponse,
  UserMeResponse,
  WorkspaceImportRequest,
  WorkspaceImportResponse,
} from '@/types/api';

const API_BASE = '/api';

function getAuthHeaders(): Record<string, string> {
  // In local mode, read from env or static config
  const tenantId = process.env.NEXT_PUBLIC_TENANT_ID || 'tenant_local';
  const userEmail = process.env.NEXT_PUBLIC_USER_EMAIL || 'user@tenant.local';
  return {
    'Content-Type': 'application/json',
    'X-Tenant-Id': tenantId,
    'X-User-Email': userEmail,
  };
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: getAuthHeaders(),
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => 'Unknown error');
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export function useApi() {
  return useMemo(
    () => ({
      // Health
      health: () => apiFetch<HealthResponse>('/health'),

      // Legacy workspace import
      importWorkspace: (req: WorkspaceImportRequest) =>
        apiFetch<WorkspaceImportResponse>('/v1/workspaces/imports/github', {
          method: 'POST',
          body: JSON.stringify(req),
        }),

      // Conversations
      createConversation: (req: ConversationCreateRequest) =>
        apiFetch<ConversationCreateResponse>('/v1/conversations', {
          method: 'POST',
          body: JSON.stringify(req),
        }),
      listConversations: (repoDefId?: string, checkoutId?: string) =>
        apiFetch<ConversationListResponse>(
          `/v1/conversations${buildConversationQuery(repoDefId, checkoutId)}`
        ),
      getConversation: (conversationId: string) =>
        apiFetch<ConversationHead>(`/v1/conversations/${conversationId}`),
      updateConversation: (conversationId: string, req: ConversationUpdateRequest) =>
        apiFetch<ConversationHead>(`/v1/conversations/${conversationId}`, {
          method: 'PATCH',
          body: JSON.stringify(req),
        }),
      deleteConversation: (conversationId: string) =>
        apiFetch<ConversationHead>(`/v1/conversations/${conversationId}`, {
          method: 'DELETE',
        }),
      listConversationEvents: (conversationId: string) =>
        apiFetch<ConversationEvent[]>(`/v1/conversations/${conversationId}/events`),
      askQuestion: (conversationId: string, req: QuestionRequest) =>
        apiFetch<QuestionResponse>(`/v1/conversations/${conversationId}/questions`, {
          method: 'POST',
          body: JSON.stringify(req),
        }),

      // Approvals
      resolveApproval: (runId: string, approvalId: string, req: ApprovalDecisionRequest) =>
        apiFetch<ApprovalDecisionResponse>(`/v1/runs/${runId}/approvals/${approvalId}`, {
          method: 'POST',
          body: JSON.stringify(req),
        }),

      // Phase 1: Identity
      me: () => apiFetch<UserMeResponse>('/v1/users/me'),
      listUsers: () => apiFetch<UserListResponse>('/v1/admin/users'),
      createUser: (req: UserCreateRequest) =>
        apiFetch<UserCreateResponse>('/v1/users', {
          method: 'POST',
          body: JSON.stringify(req),
        }),

      // Phase 1: Teams
      createTeam: (req: TeamCreateRequest) =>
        apiFetch<TeamCreateResponse>('/v1/teams', {
          method: 'POST',
          body: JSON.stringify(req),
        }),
      listTeams: () => apiFetch<TeamListResponse>('/v1/teams'),
      listAdminTeams: () => apiFetch<AdminTeamListResponse>('/v1/admin/teams'),
      getAdminTeamDetail: (teamId: string) =>
        apiFetch<TeamDetailResponse>(`/v1/admin/teams/${teamId}`),
      addTeamMember: (teamId: string, req: TeamMemberAddRequest) =>
        apiFetch<TeamMemberAddResponse>(`/v1/teams/${teamId}/members`, {
          method: 'POST',
          body: JSON.stringify(req),
        }),
      removeTeamMember: (teamId: string, userEmail: string) =>
        apiFetch<TeamMemberRemoveResponse>(`/v1/teams/${teamId}/members/${userEmail}`, {
          method: 'DELETE',
        }),

      // Phase 1: Repository Definitions
      createRepoDefinition: (req: RepositoryDefinitionCreateRequest) =>
        apiFetch<RepositoryDefinitionCreateResponse>('/v1/repos', {
          method: 'POST',
          body: JSON.stringify(req),
        }),
      listAdminRepoDefinitions: () =>
        apiFetch<RepositoryDefinitionListResponse>('/v1/admin/repos'),
      listRepoDefinitions: () =>
        apiFetch<RepositoryDefinitionListResponse>('/v1/repos'),
      getRepoDefinition: (repoDefId: string) =>
        apiFetch<RepositoryDefinition>(`/v1/repos/${repoDefId}`),
      updateRepoDefinitionTeams: (repoDefId: string, req: RepositoryDefinitionUpdateTeamsRequest) =>
        apiFetch<RepositoryDefinitionUpdateTeamsResponse>(`/v1/repos/${repoDefId}/teams`, {
          method: 'PATCH',
          body: JSON.stringify(req),
        }),

      // Phase 2: Checkouts
      createCheckout: (repoDefId: string, req: CheckoutCreateRequest) =>
        apiFetch<CheckoutCreateResponse>(`/v1/repos/${repoDefId}/checkouts`, {
          method: 'POST',
          body: JSON.stringify(req),
        }),
      listCheckoutsForRepo: (repoDefId: string) =>
        apiFetch<CheckoutListResponse>(`/v1/repos/${repoDefId}/checkouts`),
      getCheckout: (checkoutId: string) =>
        apiFetch<Checkout>(`/v1/checkouts/${checkoutId}`),
    }),
    []
  );
}

function buildConversationQuery(repoDefId?: string, checkoutId?: string): string {
  const params = new URLSearchParams();
  if (repoDefId) params.set('repo_def_id', repoDefId);
  if (checkoutId) params.set('checkout_id', checkoutId);
  const query = params.toString();
  return query ? `?${query}` : '';
}
