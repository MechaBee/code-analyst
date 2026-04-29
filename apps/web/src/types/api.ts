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
  workspace_id: string;
  title?: string;
}

export interface ConversationCreateResponse {
  conversation_id: string;
  status: string;
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
