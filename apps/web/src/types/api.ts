export interface HealthResponse {
  name: string;
  status: string;
  timestamp: string;
}

export interface WorkspaceImportRequest {
  tenant_id: string;
  repo_url: string;
  ref: string;
  github_credential_ref: string;
}

export interface WorkspaceImportResponse {
  workspace_id: string;
  snapshot_id: string;
  source_commit: string;
  status: string;
  archive_object_key?: string;
  manifest_object_key?: string;
  metadata_object_key?: string;
  file_count?: number;
  total_size_bytes?: number;
}

export interface ConversationCreateRequest {
  tenant_id: string;
  repo_def_id: string;
  checkout_id?: string | null;
  workspace_id?: string | null;
  title?: string;
}

export interface ConversationCreateResponse {
  conversation_id: string;
  status: string;
}

export interface ConversationUpdateRequest {
  title?: string | null;
  pinned?: boolean;
}

export interface ConversationHead {
  conversation_id: string;
  tenant_id: string;
  workspace_id: string;
  repo_def_id?: string | null;
  checkout_id?: string | null;
  principal_email: string;
  title?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  last_event_sequence: number;
  latest_run_id?: string | null;
  active_sandbox_id?: string | null;
  latest_snapshot_id?: string | null;
  pinned_at?: string | null;
  deleted_at?: string | null;
}

export interface ConversationListResponse {
  tenant_id: string;
  conversations: ConversationHead[];
}

export interface ConversationEvent {
  event_id: string;
  conversation_id: string;
  run_id?: string | null;
  sequence: number;
  type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export interface QuestionRequest {
  message: string;
  workspace_snapshot_id?: string | null;
  resume_sandbox: boolean;
  approval_policy: string;
}

export interface QuestionResponse {
  run_id: string;
  status: string;
  events_url: string;
}

export interface ApprovalDecisionRequest {
  decision: string;
  reason?: string;
}

export interface ApprovalDecisionResponse {
  run_id: string;
  approval_id: string;
  status: string;
}

export interface EvidenceRef {
  snapshot_id: string;
  path: string;
  start_line: number;
  end_line: number;
  excerpt_hash: string;
}

export interface AnswerEnvelope {
  answer_markdown: string;
  citations: EvidenceRef[];
  followups: string[];
}

export interface RunEventPayload {
  message?: string;
  snapshot_id?: string;
  workspace_id?: string;
  sandbox_id?: string;
  approval_id?: string;
  answer_markdown?: string;
  citations?: EvidenceRef[];
  followups?: string[];
}

export interface RunEvent {
  run_id: string;
  type: string;
  payload: RunEventPayload;
  timestamp?: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: EvidenceRef[];
  followups?: string[];
  isLoading?: boolean;
  error?: boolean;
}

// ---------------------------------------------------------------------------
// Phase 1: Identity, Team, and Repository Definition types
// ---------------------------------------------------------------------------

export interface RepositoryAdapter {
  kind: string; // "github" | "gitlab"
  auth_kind: string; // "public" | "token"
  access_secret_ref?: string | null;
  credential_ref?: string | null;
}

export interface RepositoryAdapterCreateRequest {
  kind: string;
  auth_kind: string;
  access_secret?: Record<string, unknown> | null;
  credential_ref?: string | null;
}

export interface RepositoryDefinition {
  tenant_id: string;
  repo_def_id: string;
  name?: string | null;
  endpoint: string;
  adapter: RepositoryAdapter;
  team_ids: string[];
  created_at: string;
}

export interface User {
  tenant_id: string;
  email: string;
  name?: string | null;
  is_admin: boolean;
  created_at: string;
}

export interface Team {
  tenant_id: string;
  team_id: string;
  name: string;
  created_at: string;
}

export interface TeamMembership {
  tenant_id: string;
  team_id: string;
  user_email: string;
  joined_at: string;
}

export interface TeamCreateRequest {
  name: string;
}

export interface TeamCreateResponse {
  team_id: string;
  tenant_id: string;
  name: string;
  created_at: string;
}

export interface TeamListResponse {
  tenant_id: string;
  teams: Team[];
}

export interface TeamSummary {
  tenant_id: string;
  team_id: string;
  name: string;
  created_at: string;
  member_count: number;
}

export interface AdminTeamListResponse {
  tenant_id: string;
  teams: TeamSummary[];
}

export interface TeamMemberRecord {
  tenant_id: string;
  team_id: string;
  user_email: string;
  name?: string | null;
  is_admin: boolean;
  joined_at: string;
}

export interface TeamDetailResponse {
  tenant_id: string;
  team: Team;
  members: TeamMemberRecord[];
  repositories: RepositoryDefinition[];
}

export interface TeamMemberAddRequest {
  user_email: string;
}

export interface TeamMemberAddResponse {
  team_id: string;
  user_email: string;
  joined_at: string;
}

export interface TeamMemberRemoveResponse {
  team_id: string;
  user_email: string;
}

export interface UserCreateRequest {
  email: string;
  name?: string | null;
  is_admin?: boolean;
}

export interface UserCreateResponse {
  tenant_id: string;
  email: string;
  name?: string | null;
  is_admin: boolean;
  created_at: string;
}

export interface UserMeResponse {
  tenant_id: string;
  email: string;
  name?: string | null;
  is_admin: boolean;
}

export interface UserListResponse {
  tenant_id: string;
  users: User[];
}

export interface RepositoryDefinitionCreateRequest {
  name?: string | null;
  endpoint: string;
  adapter: RepositoryAdapterCreateRequest;
  team_ids?: string[];
}

export interface RepositoryDefinitionCreateResponse {
  tenant_id: string;
  repo_def_id: string;
  name?: string | null;
  endpoint: string;
  adapter: RepositoryAdapter;
  team_ids: string[];
  created_at: string;
}

export interface RepositoryDefinitionListResponse {
  tenant_id: string;
  repo_definitions: RepositoryDefinition[];
}

export interface RepositoryDefinitionUpdateTeamsRequest {
  team_ids: string[];
}

export interface RepositoryDefinitionUpdateTeamsResponse {
  tenant_id: string;
  repo_def_id: string;
  team_ids: string[];
}

// ---------------------------------------------------------------------------
// Phase 2: Checkout types
// ---------------------------------------------------------------------------

export interface Checkout {
  tenant_id: string;
  checkout_id: string;
  repo_def_id: string;
  branch: string;
  commit_sha: string;
  run_timestamp: string;
  workspace_id: string;
  snapshot_id: string;
  archived: boolean;
}

export interface CheckoutCreateRequest {
  repo_def_id: string;
  ref: string;
}

export interface CheckoutCreateResponse {
  tenant_id: string;
  checkout_id: string;
  repo_def_id: string;
  branch: string;
  commit_sha: string;
  run_timestamp: string;
  workspace_id: string;
  snapshot_id: string;
}

export interface CheckoutListResponse {
  tenant_id: string;
  checkouts: Checkout[];
}
