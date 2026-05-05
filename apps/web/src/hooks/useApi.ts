import { useMemo } from 'react';

import type {
  BootstrapAdminInvitationRequest,
  ApprovalDecisionRequest,
  ApprovalDecisionResponse,
  AdminTeamListResponse,
  CitationPreviewResponse,
  LogoutResponse,
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
  RegistrationConsumeRequest,
  RegistrationInviteCreateRequest,
  RegistrationInviteCreateResponse,
  RegistrationInvitePreviewResponse,
  RepositoryDefinition,
  RepositoryDefinitionCreateRequest,
  RepositoryDefinitionCreateResponse,
  RepositoryDefinitionListResponse,
  RepositoryDefinitionUpdateRequest,
  RepositoryDefinitionUpdateTeamsRequest,
  RepositoryDefinitionUpdateTeamsResponse,
  SignInConsumeRequest,
  SignInLinkCreateRequest,
  SignInLinkCreateResponse,
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
  const tenantId = process.env.NEXT_PUBLIC_TENANT_ID || 'tenant_local';
  return {
    'Content-Type': 'application/json',
    'X-Tenant-Id': tenantId,
  };
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: getAuthHeaders(),
    credentials: 'same-origin',
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
      getCitationPreview: (
        conversationId: string,
        params: {
          snapshotId: string;
          path: string;
          startLine: number;
          endLine: number;
        }
      ) =>
        apiFetch<CitationPreviewResponse>(
          `/v1/conversations/${conversationId}/citations/preview?${new URLSearchParams({
            snapshot_id: params.snapshotId,
            path: params.path,
            start_line: String(params.startLine),
            end_line: String(params.endLine),
          }).toString()}`
        ),
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

      // Auth
      createBootstrapAdminInvitation: (req: BootstrapAdminInvitationRequest) =>
        apiFetch<RegistrationInviteCreateResponse>('/v1/auth/bootstrap/invitations', {
          method: 'POST',
          body: JSON.stringify(req),
        }),
      createRegistrationInvite: (req: RegistrationInviteCreateRequest) =>
        apiFetch<RegistrationInviteCreateResponse>('/v1/auth/invitations', {
          method: 'POST',
          body: JSON.stringify(req),
        }),
      previewRegistrationInvite: (token: string) =>
        apiFetch<RegistrationInvitePreviewResponse>(
          `/v1/auth/registration/preview?token=${encodeURIComponent(token)}`
        ),
      consumeRegistrationInvite: (req: RegistrationConsumeRequest) =>
        apiFetch<UserMeResponse>('/v1/auth/register/consume', {
          method: 'POST',
          body: JSON.stringify(req),
        }),
      createSignInLink: (req: SignInLinkCreateRequest) =>
        apiFetch<SignInLinkCreateResponse>('/v1/auth/sign-in-links', {
          method: 'POST',
          body: JSON.stringify(req),
        }),
      consumeSignInLink: (req: SignInConsumeRequest) =>
        apiFetch<UserMeResponse>('/v1/auth/sign-in/consume', {
          method: 'POST',
          body: JSON.stringify(req),
        }),
      logout: () =>
        apiFetch<LogoutResponse>('/v1/auth/logout', {
          method: 'POST',
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
      listAdminRepoDefinitions: (includeArchived: boolean = false) =>
        apiFetch<RepositoryDefinitionListResponse>(
          `/v1/admin/repos${includeArchived ? '?include_archived=true' : ''}`
        ),
      listRepoDefinitions: () =>
        apiFetch<RepositoryDefinitionListResponse>('/v1/repos'),
      getRepoDefinition: (repoDefId: string) =>
        apiFetch<RepositoryDefinition>(`/v1/repos/${repoDefId}`),
      updateRepoDefinition: (repoDefId: string, req: RepositoryDefinitionUpdateRequest) =>
        apiFetch<RepositoryDefinition>(`/v1/repos/${repoDefId}`, {
          method: 'PATCH',
          body: JSON.stringify(req),
        }),
      updateRepoDefinitionTeams: (repoDefId: string, req: RepositoryDefinitionUpdateTeamsRequest) =>
        apiFetch<RepositoryDefinitionUpdateTeamsResponse>(`/v1/repos/${repoDefId}/teams`, {
          method: 'PATCH',
          body: JSON.stringify(req),
        }),
      archiveRepoDefinition: (repoDefId: string) =>
        apiFetch<RepositoryDefinition>(`/v1/repos/${repoDefId}`, {
          method: 'DELETE',
        }),
      restoreRepoDefinition: (repoDefId: string) =>
        apiFetch<RepositoryDefinition>(`/v1/repos/${repoDefId}/restore`, {
          method: 'POST',
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
