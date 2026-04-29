# V1 Broader Vision — Implementation Roadmap

## Context

The MVP (captured in `documentation/plan-roadmap/local-first-mvp/local-first-implementation-roadmap.md`) has validated four core subsystems:

1. **Workspace Store** — immutable snapshots from GitHub
2. **Conversation Store** — append-only event log with materialized head
3. **Agent Orchestrator** — FastAPI service driving sandbox sessions
4. **Sandbox Pool** — Docker-based worker provisioning and execution

This document defines the next implementation phase to align the MVP with the broader vision described in `documentation/envisioned-operations.md`.

The vision introduces:

- **Multi-entity tenancy** where every object lives under a `tenant_id`
- **Teams and admin users** with membership management
- **Repository definitions** as first-class, reusable entities associated with teams
- **Conversations** scoped to both a user (`principal_email`) and a repository definition
- **Checkouts** that bind a repository definition to a branch, commit, and timestamp
- **Shared sandboxes** born from checkouts, reused across conversations, and treated as immutable

---

## Architecture Decisions

### 1. App State: In-Memory Relational DB Persisted to S3

The new entities (`User`, `Team`, `RepositoryDefinition`, `TeamMembership`, `Checkout`) are relational and low-volume. Rather than introducing a separate database server or DynamoDB in this local-first phase, the system will use a **single JSON state file per tenant** stored in S3.

**Pattern:**

- On control-plane startup, load `tenants/{tenant_id}/db/app_state.json` into an in-memory `AppStateDB` object.
- All reads for relational app state (team lookup, membership check, repo definition list) hit this in-memory structure.
- On any mutation (create team, add member, import repo definition, create checkout), update the in-memory structure and immediately write the JSON blob back to S3.

**Why:**

- Keeps the local stack single-dependency (only MinIO/S3).
- Avoids adding DynamoDB or PostgreSQL to the Docker Compose topology.
- Volume is expected to be small (teams, dozens of repos, hundreds of users).
- The S3 upload/download round-trip is acceptable for the mutation frequency of these entities.

**Concurrency note:**

The local-first stack runs a single `control-plane` replica. A simple file-level optimistic-locking checksum (ETag-based) on the S3 writeback is sufficient to prevent accidental overwrites if the deployment model ever changes.

### 2. Scope: Full-Stack Implementation

Every phase described below includes both backend and frontend deliverables:

- **Backend:** New Pydantic contracts, state store adapters, API endpoints, orchestrator updates, and sandbox supervisor changes.
- **Frontend:** New Next.js pages, React components, hooks, and API type updates.

### 3. Sandbox Immutability Baseline

The vision states sandboxes are not mutated by conversations. The baseline implementation will enforce this through the runtime contract rather than heavy filesystem isolation:

- The `sandbox-supervisor` materializes a checkout snapshot into a directory and mounts it as **read-only** inside the sandbox worker container.
- The analysis adapter contract receives a `workspace_root` (read-only) and an `artifacts_dir` (writable). Any generated files, temp data, or session state must be written to `artifacts_dir`.
- Sandbox sessions are keyed by `checkout_id`. Multiple conversations can reference the same active `sandbox_id` for that checkout, sharing the warm materialized state.
- If the sandbox worker needs to write cache or index data, it writes to `artifacts_dir`; the `workspace_root` remains untouched.

This satisfies the vision constraint without requiring copy-on-write filesystems in the first iteration.

---

## Entity Model

### `User` (principal)

```python
class User(BaseModel):
    tenant_id: str
    email: str  # globally unique within tenant, acts as user id
    name: str | None = None
    is_admin: bool = False
    created_at: datetime
```

### `Team`

```python
class Team(BaseModel):
    tenant_id: str
    team_id: str
    name: str
    created_at: datetime
```

### `TeamMembership`

```python
class TeamMembership(BaseModel):
    tenant_id: str
    team_id: str
    user_email: str
    joined_at: datetime
```

### `RepositoryDefinition` (replaces raw `repo_url` string)

```python
class RepositoryAdapter(BaseModel):
    kind: str  # "github" | "gitlab" (future)
    credential_ref: str  # "public" | "env:VAR_NAME"

class RepositoryDefinition(BaseModel):
    tenant_id: str
    repo_def_id: str
    name: str | None = None
    endpoint: str  # e.g. https://github.com/acme/example.git
    adapter: RepositoryAdapter
    team_ids: list[str] = Field(default_factory=list)
    created_at: datetime
```

### `Checkout`

```python
class Checkout(BaseModel):
    tenant_id: str
    checkout_id: str
    repo_def_id: str
    branch: str
    commit_sha: str
    run_timestamp: datetime  # when the checkout was created
    workspace_id: str
    snapshot_id: str
    archived: bool = False
```

### Updated `ConversationHead`

```python
class ConversationHead(BaseModel):
    conversation_id: str
    tenant_id: str
    workspace_id: str
    principal_email: str          # NEW
    repo_def_id: str | None = None  # NEW - reference to repository definition
    checkout_id: str | None = None  # NEW - reference to checkout used
    title: str | None = None
    status: str = "OPEN"
    created_at: datetime
    updated_at: datetime
    last_event_sequence: int = 0
    latest_run_id: str | None = None
    active_sandbox_id: str | None = None
    latest_snapshot_id: str | None = None
```

### Updated `SandboxSessionRef`

```python
class SandboxSessionRef(BaseModel):
    sandbox_id: str
    provider: str = "docker"
    runtime_image: str
    status: Status = Status.RUNNING
    checkout_id: str        # NEW - replaces raw workspace_id coupling
    session_state_key: str
```

---

## S3 Object Model Update

The existing layout under `tenants/{tenant_id}/` is extended:

```text
tenants/{tenant_id}/
  db/
    app_state.json              # NEW - in-memory relational DB snapshot
  workspaces/{workspace_id}/
    snapshots/{snapshot_id}/
      repo.tar.zst
      manifest.json
      metadata.json
  checkouts/{checkout_id}/      # NEW - checkout metadata
    checkout.json
  sandboxes/{sandbox_id}/
    session_state.json
    artifacts/{artifact_id}/...
    logs/{run_id}.jsonl
  conversations/{user_email}/{repo_def_id}/{conversation_id}/   # scoped for observability
    head.json
    events/{sequence}.json
  runs/{run_id}/
    state.json
    events/{sequence}.json
    final-answer.json
  repos/{repo_def_id}/          # NEW - repo definition metadata
    repo_def.json
  teams/{team_id}/              # NEW - team data
    team.json
```

`app_state.json` structure (per tenant):

```json
{
  "tenant_id": "tenant_local",
  "users": {
    "user@example.com": { ... }
  },
  "teams": {
    "team_01": { ... }
  },
  "memberships": [
    { "team_id": "team_01", "user_email": "user@example.com", ... }
  ],
  "repo_definitions": {
    "repo_01": { ... }
  },
  "checkouts": {
    "chk_01": { ... }
  },
  "metadata": {
    "version": 1,
    "updated_at": "2026-04-29T10:00:00Z"
  }
}
```

---

## API Surface

### Admin & Identity Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/teams` | Create a team |
| `GET`  | `/v1/teams` | List teams for tenant |
| `POST` | `/v1/teams/{team_id}/members` | Add member by email |
| `DELETE` | `/v1/teams/{team_id}/members/{email}` | Remove member |
| `GET`  | `/v1/users/me` | Get current user profile |
| `POST` | `/v1/users` | Create or upsert a user (admin) |

### Repository Definition Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/repos` | Create a repository definition |
| `GET`  | `/v1/repos` | List repo defs accessible to principal |
| `GET`  | `/v1/repos/{repo_def_id}` | Get a repo def |
| `PATCH`| `/v1/repos/{repo_def_id}/teams` | Update team associations |

### Checkout Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/repos/{repo_def_id}/checkouts` | Trigger a new checkout (import) |
| `GET`  | `/v1/repos/{repo_def_id}/checkouts` | List checkouts for a repo |
| `GET`  | `/v1/checkouts/{checkout_id}` | Get checkout details |

### Updated Conversation Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/conversations` | Create conversation (body now includes `repo_def_id` and optional `checkout_id`) |
| `GET`  | `/v1/conversations` | List conversations scoped to `principal_email` |
| `GET`  | `/v1/conversations/{conversation_id}` | Get conversation head |

### Existing Endpoints Retained

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/workspaces/imports/github` | **Deprecated** — replaced by checkout flow, but kept until Phase 2 completion |
| `POST` | `/v1/conversations/{conversation_id}/questions` | Unchanged surface, internally resolves via `repo_def_id` / `checkout_id` |
| `GET`  | `/v1/runs/{run_id}/events` | Unchanged |
| `POST` | `/v1/runs/{run_id}/approvals/{approval_id}` | Unchanged |

### Authentication (Local-First Baseline)

The local-first stack will use a simple header-based auth for now:

- `X-Tenant-Id`: required on all requests.
- `X-User-Email`: required on all requests. Represents the Cognito principal. The control plane upserts this user into the light DB if not present.

Cognito integration is explicitly out of scope for this roadmap but the data model and middleware are designed to accept Cognito claims in a future phase.

---

## Frontend Scope

### New Pages / Views

1. **Admin Dashboard** (`/admin`)
   - List teams, create team
   - Add/remove team members by email
   - List all users

2. **Repository Management** (`/repos`)
   - List repository definitions accessible to the user
   - Create new repository definition (name, endpoint, credential ref, team grants)
   - View repo details and checkout history

3. **User Dashboard** (`/dashboard`) — replaces the single-page import flow
   - Header: profile (drawer or dropdown), logout (clears local state)
   - Left sidebar:
     - Actions: "Import repository" (redirects to `/repos`)
     - Recent conversations grouped by repository definition
   - Main content:
     - Chat view scoped to a selected conversation (reuses existing `ChatView`)

4. **Import / Checkout Flow** (`/repos/{repo_def_id}/checkout`)
   - Select branch/ref
   - Trigger checkout
   - On success, optionally start a new conversation about this checkout

### Updated Components

- `useAppState` — adds `repoDefId`, `checkoutId`, `principalEmail`
- `useApi` — adds wrappers for all new endpoints
- `WorkspaceImport` — becomes a wrapper around repo selection + checkout trigger
- `ChatView` — shows repo name and branch in header; links back to dashboard

### Auth State

A new `AuthProvider` will wrap the app:

- Reads `X-User-Email` and `X-Tenant-Id` from environment/config for the local build.
- Provides `principalEmail`, `tenantId`, `isAdmin` to the React tree.
- In a future AWS phase, this provider will integrate with Cognito session cookies or tokens.

---

## Implementation Phases

### Phase 1: Light DB, Identity, and Repository Definitions

**Goal:** Enable team-based repository management before replacing the import flow.

**Backend Deliverables:**

1. `packages/contracts-python/src/code_analyst_contracts/contracts.py`
    - Add `User`, `Team`, `TeamMembership`, `RepositoryDefinition`, `RepositoryAdapter` models.
   - Add request/response models for admin and repo endpoints.

2. `services/control-plane/control_plane_app/state_store.py`
   - Add `TenantAppStateDB` dataclass representing the in-memory JSON structure.
   - Add `AppStateStore` with methods: `load_tenant_db(tenant_id)`, `save_tenant_db(tenant_id)`, optimistic etag check.
   - Add `UserStateStore`, `TeamStateStore`, `RepositoryDefinitionStateStore` — these operate on the in-memory `TenantAppStateDB` and delegate persistence to `AppStateStore`.

3. `services/control-plane/control_plane_app/main.py`
   - Wire `app_state_store` into `AppState`.
   - Add middleware: extract `X-Tenant-Id` and `X-User-Email` headers, upsert user, attach to request state.
   - Implement admin endpoints (`POST /v1/teams`, `GET /v1/teams`, etc.).
   - Implement repo definition endpoints (`POST /v1/repos`, `GET /v1/repos`, etc.).
   - Enforce team-based access: `GET /v1/repos` returns only repos whose `team_ids` intersect with the principal's teams.

**Frontend Deliverables:**

1. `apps/web/src/types/api.ts`
   - Extend types for `User`, `Team`, `RepositoryDefinition`, checkout models, and admin DTOs.

2. `apps/web/src/hooks/useApi.ts`
   - Add API wrappers for new endpoints.

3. `apps/web/src/hooks/useAuth.tsx`
   - Simple context provider with `principalEmail`, `tenantId`, `isAdmin`.
   - In local mode, reads from a static config or env vars.

4. `apps/web/src/components/AdminDashboard.tsx`
   - Teams list, create team form, member add/remove UI.

5. `apps/web/src/components/RepoManager.tsx`
   - List repos, create repo form, assign teams.

6. `apps/web/src/app/admin/page.tsx`
   - Page shell for the admin dashboard.

7. `apps/web/src/app/repos/page.tsx`
   - Page shell for repository management.

**Exit Criteria:**

- An admin user can create a team and add members.
- A user can create a repository definition and associate it with a team.
- `GET /v1/repos` correctly filters by principal team membership.
- `app_state.json` is created in S3 and survives control-plane restart.

---

### Phase 2: Checkout Refactor — Replace Raw Imports

**Goal:** Introduce the `Checkout` entity so that workspace imports become versioned, traceable checkouts bound to a repository definition.

**Backend Deliverables:**

1. `packages/contracts-python/src/code_analyst_contracts/contracts.py`
   - Add `Checkout`, `CheckoutCreateRequest`, `CheckoutCreateResponse`, `CheckoutListResponse`.
   - Update `WorkspaceImportRequest` to optionally accept `repo_def_id` instead of raw `repo_url`.

2. `services/control-plane/control_plane_app/state_store.py`
   - Add `CheckoutStateStore` operating on `TenantAppStateDB`.

3. `services/control-plane/control_plane_app/workspace_imports.py`
   - Refactor `WorkspaceImportService.import_github_repo`:
     - Accept a `repo_def_id`.
     - Resolve the `RepositoryDefinition` from the light DB.
     - Validate the principal has team access to the repo.
     - Perform the clone using the repo def's `adapter`.
     - After successful snapshot creation, write a `Checkout` record.
   - Keep backward compatibility: if `repo_url` is provided directly (legacy), allow it but do not create a `Checkout`.

4. `services/control-plane/control_plane_app/main.py`
   - Add `POST /v1/repos/{repo_def_id}/checkouts`.
   - The endpoint clones, snapshots, creates checkout record, and returns checkout info.
   - Add `GET /v1/repos/{repo_def_id}/checkouts` and `GET /v1/checkouts/{checkout_id}`.

**Frontend Deliverables:**

1. `apps/web/src/components/RepoManager.tsx`
   - Add per-repo "Checkout" button that opens a branch/ref selector.
   - Poll or redirect to a checkout detail page.

2. `apps/web/src/app/repos/[repoDefId]/checkout/page.tsx`
   - New page: select branch, trigger checkout, show workspace/snapshot IDs on completion.
   - Button to "Start conversation about this checkout".

3. `apps/web/src/components/CheckoutList.tsx`
   - Small component listing checkouts per repo with branch, commit, timestamp.

**Exit Criteria:**

- A user selects a repository definition, chooses a branch, and triggers a checkout.
- The checkout result contains `checkout_id`, `workspace_id`, `snapshot_id`, `commit_sha`, and `run_timestamp`.
- The checkout is listed under the repository definition.
- Raw `repo_url` workspace import is deprecated but still functional.

---

### Phase 3: Conversation Scoping — User + Repository Binding

**Goal:** Conversations are explicitly scoped to a `principal_email` and a `repository_definition_id`.

**Backend Deliverables:**

1. `packages/contracts-python/src/code_analyst_contracts/contracts.py`
   - Update `ConversationCreateRequest` to include `repo_def_id` and optional `checkout_id`.
   - Update `ConversationHead` model (see Entity Model).

2. `services/control-plane/control_plane_app/state_store.py`
   - Update `ConversationHead` and `ConversationStateStore.create_conversation`.
   - Update index entry to include `principal_email` for efficient listing.
   - Update conversation S3 key structure to `conversations/{user_email}/{repo_def_id}/{conversation_id}/` for head and events.
   - Update conversation S3 key structure to `conversations/{user_email}/{repo_def_id}/{conversation_id}/` for head and events.

3. `services/control-plane/control_plane_app/main.py`
   - Update `POST /v1/conversations` to accept and validate `repo_def_id`.
   - Add `GET /v1/conversations` query endpoint filtered by `principal_email` (from auth middleware) and optional `repo_def_id`.
   - Update `POST /v1/conversations/{conversation_id}/questions`:
     - Internally resolve the checkout/workspace via the conversation's `checkout_id` or `repo_def_id`.
     - If `workspace_snapshot_id` is not provided in the `QuestionRequest`, resolve via the conversation's `latest_snapshot_id` or the checkout's snapshot.

4. `services/control-plane/control_plane_app/question_orchestrator.py`
   - Update `_setup_run` to read `repo_def_id` and `checkout_id` from the conversation head.
   - Pass `checkout_id` into sandbox session creation (Phase 4).

**Frontend Deliverables:**

1. `apps/web/src/app/dashboard/page.tsx`
   - New user dashboard with left sidebar.
   - Group conversations by repository definition.
   - Show recent conversations with title and last message preview.

2. `apps/web/src/hooks/useAppState.tsx`
   - Add `repoDefId`, `checkoutId`, `principalEmail` fields.
   - Update `setWorkspace` equivalent to handle checkout context.

3. `apps/web/src/components/ConversationList.tsx`
   - List conversations grouped by repo.
   - Clicking a conversation loads it into `ChatView`.

4. `apps/web/src/app/page.tsx`
   - Redirect to `/dashboard`.

**Exit Criteria:**

- Creating a conversation requires selecting a repository definition (and optionally a checkout).
- `GET /v1/conversations` returns only conversations belonging to the authenticated principal.
- The chat UI shows the repository name and branch associated with the conversation.

---

### Phase 4: Shared Sandboxes & Immutability Baseline

**Goal:** Sandboxes are shared across conversations for the same checkout and are treated as immutable.

**Backend Deliverables:**

1. `packages/contracts-python/src/code_analyst_contracts/contracts.py`
   - Update `SandboxSessionCreateRequest` to accept `checkout_id` instead of just `workspace` (or include both).
   - Add `SandboxSession` model to track sandbox-to-checkout mapping.

2. `services/control-plane/control_plane_app/state_store.py`
   - Add `SandboxStateStore`:
     - Track active sandbox sessions keyed by `checkout_id`.
     - Store `SandboxSession` records in the tenant's light DB (`app_state.json`).

3. `services/control-plane/control_plane_app/question_orchestrator.py`
   - In `execute_question`, look up the active sandbox for the conversation's `checkout_id`.
   - If `resume_sandbox=True` and an active sandbox exists, reuse it.
   - If no sandbox exists, create one via the `SandboxSupervisorClient` keyed by `checkout_id`.
   - On conversation switching, the sandbox remains active for the checkout.

4. `services/sandbox-supervisor/sandbox_supervisor_app/main.py`
   - Update session creation to accept `checkout_id` in the request.
   - Ensure the materialized workspace directory is mounted as read-only when running in Docker.
   - Pass `ARTIFACTS_DIR` environment variable to the sandbox worker.

5. `services/sandbox-supervisor/sandbox_supervisor_app/workspace_materializer.py`
   - Ensure extracted workspace is placed in a path that can be mounted read-only.
   - Create a separate writable `artifacts` directory per session.

6. `services/sandbox-supervisor/sandbox_supervisor_app/analysis_adapter.py`
   - Update `analyze` signature to accept `artifacts_dir: str`.
   - Ensure adapters write any temp files to `artifacts_dir`.

**Frontend Deliverables:**

1. Minor UI updates:
   - Show a "shared sandbox" indicator in the chat header when the conversation reuses an existing sandbox.
   - Show checkout info (branch, commit, timestamp) in the chat header.

**Exit Criteria:**

- Two separate conversations about the same checkout reuse the same sandbox session (when `resume_sandbox=True`).
- The sandbox worker cannot write into the materialized workspace root.
- Analysis adapters write artifacts to a designated `artifacts_dir`.

---

### Phase 5: Frontend Polish & Hardening

**Goal:** Make the full-stack experience cohesive and stable.

**Backend Deliverables:**

1. Deprecate and remove `POST /v1/workspaces/imports/github` raw import endpoint.
2. Add pagination to `GET /v1/conversations` and `GET /v1/repos`.
3. Add data validation on `RepositoryDefinition` endpoints (e.g. valid endpoint URLs).
4. Improve `AppStateStore` optimistic locking — retry on ETag mismatch.
5. Add admin-only guards to admin endpoints.

**Frontend Deliverables:**

1. **User Dashboard refinements:**
   - Add search/filter for conversations.
   - Add repo-level action to refresh/checkout latest branch state.

2. **Admin Dashboard refinements:**
   - Add user directory table.
   - Add team detail view.

3. **Global layout:**
   - Add navigation sidebar on all authenticated pages.
   - Add tenant badge and user profile dropdown.

4. **Error handling & loading states:**
   - Skeleton loaders for conversation list.
   - Toast notifications for checkout success/failure.

**Exit Criteria:**

- The full import → checkout → chat flow is navigable without knowing IDs.
- Admin and user dashboards are distinct.
- The local Docker Compose stack runs end-to-end with the new flows.

---

## Testing Strategy

### Backend Integration Tests

For each phase, add tests under `tests/integration/`:

1. **Phase 1:** `test_identity_and_repos.py`
   - Create team, add member, create repo def, list repos with access control.
   - Verify `app_state.json` round-trip.

2. **Phase 2:** `test_checkout_flow.py`
   - Create repo def, trigger checkout, verify checkout record and snapshot.
   - Verify raw import still works (backward compatibility).

3. **Phase 3:** `test_conversation_scoping.py`
   - Create conversation scoped to repo + checkout.
   - Ask question, verify run resolves correct snapshot.
   - List conversations filtered by principal.

4. **Phase 4:** `test_shared_sandbox.py`
   - Two conversations, same checkout, same sandbox reused.
   - Verify sandbox session record exists in `app_state.json`.

### Frontend E2E Tests

Use the existing Playwright setup in `apps/web/`:

- `admin.spec.ts` — team creation, member management.
- `repo-checkout.spec.ts` — create repo def, checkout branch, verify navigation to chat.
- `conversation.spec.ts` — create conversation, ask question, verify citation rendering.

---

## Docker Compose Topology (No Change Required)

The existing `docker-compose.yml` topology is sufficient:

- `web`
- `control-plane`
- `sandbox-supervisor`
- `minio`

No new infrastructure services are introduced in this roadmap. The relational state lives in `app_state.json` inside MinIO.

---

## Risks & Mitigations

### Risk: Light DB becomes a bottleneck

**Mitigation:** The expected data volume (teams, repos, checkouts) is small. If it grows, the `app_state.json` can be sharded (e.g. `users.json`, `teams.json`, `repos.json`) or migrated to DynamoDB without changing the state store interface.

### Risk: Concurrent writes to `app_state.json`

**Mitigation:** Use S3 conditional writes (If-Match / ETag) on put. On conflict, re-read and retry. Acceptable for the local-first single-instance model.

### Risk: Read-only workspace mount complicates local dev without Docker

**Mitigation:** The read-only enforcement is primarily a Docker container mount flag. When running tests with ASGI transport (no Docker), the analysis adapter's `artifacts_dir` contract alone provides the isolation boundary.

### Risk: Frontend routing complexity increases

**Mitigation:** Use Next.js App Router conventions. Keep the existing `ChatView` as a reusable component that accepts `conversationId` as a prop, regardless of which page renders it.

---

## Decision Summary

This roadmap keeps the local-first stack intact while introducing the full entity model from the broader vision:

- **In-memory relational DB** backed by an S3 JSON blob (`app_state.json`) for `User`, `Team`, `RepositoryDefinition`, and `Checkout`.
- **Full-stack** implementation with backend contracts, state stores, APIs, and frontend pages/components for each phase.
- **Sandbox immutability baseline** achieved through read-only workspace mounts in Docker and an `artifacts_dir` contract for the analysis adapter.

The phases are ordered to minimize disruption:

1. **Phase 1** introduces new entities without touching the existing chat flow.
2. **Phase 2** adds checkouts alongside the existing import endpoint.
3. **Phase 3** binds conversations to users/repos, deprecating anonymous conversations.
4. **Phase 4** optimizes sandbox sharing without changing the chat UX.
5. **Phase 5** cleans up and polishes.

This validates the hardest conceptual boundaries first — identity, repository scoping, and checkout versioning — while keeping the existing conversation and run event-store architecture stable.
