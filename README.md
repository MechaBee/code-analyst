# Code Analyst

Local-first scaffold for a code-analysis SaaS platform built around:

- Workspace Store
- Conversation Store
- Agent Orchestrator
- Sandbox Pool

## Layout

- `apps/web`: placeholder web frontend
- `packages/contracts-python`: shared Pydantic contracts
- `services/control-plane`: public API and orchestration stubs
- `services/sandbox-supervisor`: sandbox lifecycle API stubs
- `documentation/plan-roadmap`: planning and architecture documents

## Python project setup

Each Python deliverable is scaffolded as a Poetry project:

- `packages/contracts-python`
- `services/control-plane`
- `services/sandbox-supervisor`

Each Poetry project is configured for:

- Python `3.11.11`
- in-project virtual environments via `.venv`

The repository also includes a top-level `.python-version` pinned to `3.11.11`.

The repository root also contains a Poetry-based development harness for shared
integration testing across services.

## Local stack

The first local stack is designed to run with Docker Compose and MinIO as the S3-compatible object store.

```bash
docker compose --env-file .env up --build -d
```

Available endpoints:

- `http://localhost:3000`: interactive chat UI (import repo, ask questions, view citations)
- `http://localhost:8080/health`: control-plane health
- `http://localhost:8090/health`: sandbox-supervisor health
- `http://localhost:9001`: MinIO console

## Maintenance procedures

This section assumes the local Docker Compose stack is used as-is, with MinIO
persisted to a local host directory and the control-plane auth database also
persisted to a local host directory.

### Local installation and persistent state

Create a local `.env` file for secrets and optional runtime overrides:

```env
AUTH_BOOTSTRAP_SECRET=replace-with-a-random-secret
ANALYSIS_BACKEND=deterministic
```

Generate `AUTH_BOOTSTRAP_SECRET` with a high-entropy value, for example:

```bash
openssl rand -hex 32
```

Start the local stack:

```bash
docker compose --env-file .env up --build -d
```

Persistent local state is stored on the host in:

- `./minio-data`: MinIO object storage backing workspace snapshots, conversations, runs, and tenant `app_state.json`
- `./control-plane-data`: control-plane local state, including the SQLite auth database at `auth/auth.db`

In the current Compose setup these are mounted from:

- [docker-compose.yml](/Users/molbal/Documents/src/mechabee/code-analyst/docker-compose.yml:37)
- [docker-compose.yml](/Users/molbal/Documents/src/mechabee/code-analyst/docker-compose.yml:81)

This means:

- `docker compose down` does **not** reset user state
- rebuilding containers does **not** reset user state
- removing `minio-data` or `control-plane-data` **does** destroy local persisted state

### Auth model in local runs

Local runs now use:

- `AUTH_BACKEND=session_cookie`
- `AUTH_STORE=sqlite`
- MinIO-backed app authorization state

There is no permanently installed root user. The first admin is created through
a bootstrap invite flow. Admin status itself does not expire once stored, but
session cookies and sign-in links do expire.

Relevant defaults are defined in [config.py](/Users/molbal/Documents/src/mechabee/code-analyst/services/control-plane/control_plane_app/config.py:26):

- session lifetime: 30 days
- registration invite lifetime: 72 hours
- sign-in link lifetime: 15 minutes

### Bootstrap the first admin

For a fresh tenant, or for a legacy tenant with no auth accounts yet, create
the first admin invite with:

```bash
curl -sS -X POST http://localhost:8080/v1/auth/bootstrap/invitations \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: tenant_local' \
  -d "{
    \"email\": \"you@example.com\",
    \"name\": \"First Admin\",
    \"bootstrap_secret\": \"$AUTH_BOOTSTRAP_SECRET\"
  }"
```

Notes:

- the request `bootstrap_secret` must exactly match `AUTH_BOOTSTRAP_SECRET`
- `tenant_local` matches the current frontend default tenant header
- the response contains an `invite_url`

Next steps:

1. copy the returned `invite_url`
2. open it in the browser
3. complete `/auth/register`
4. confirm you land on `/dashboard`
5. open `/admin`

If bootstrap returns `Bootstrap is no longer available for this tenant.`, that
means the tenant already has at least one auth account in SQLite. For legacy
tenants, existing admin users in `app_state.json` no longer block bootstrap by
themselves.

### User management

Once signed in as an admin, use the Admin UI at `http://localhost:3000/admin`.

Supported local workflows:

- invite a new or unclaimed user with a registration link
- assign initial teams during invite creation
- create a sign-in link for an already claimed user
- copy the link or open the local mail client with a prefilled `mailto:` link

Operational notes:

- invited but unclaimed users appear separately from registered users
- sign-in links are admin-issued only; there is no self-service magic-link request flow
- if an admin session expires, that admin needs a new sign-in link
- keep at least two admins in a local environment you care about

### Existing legacy tenants

If a tenant already has users in MinIO-backed `app_state.json` from older runs
but has no rows yet in `control-plane-data/auth/auth.db`, that tenant is in a
legacy pre-auth state.

The current recovery path is:

1. bootstrap a new first auth-backed admin for that tenant
2. sign in through the invite link
3. use `/admin` to send registration invites to legacy users that should be claimed

Legacy users remain visible in the admin interface as unclaimed until they
redeem a registration invite.

### Restart, rebuild, and upgrade workflow

Common local maintenance flow:

```bash
docker compose --env-file .env up --build -d
docker compose ps
curl -si http://localhost:8080/health
curl -si http://localhost:8090/health
```

If only configuration changed, a targeted restart is usually enough:

```bash
docker compose --env-file .env up -d --build control-plane web
```

### Backup and reset procedures

Default minio credentials, you might want to change:
user: minioadmin
password: minioadmin

For a local backup, preserve both host directories:

- `minio-data`
- `control-plane-data`

For a full local reset of tenants, conversations, auth accounts, and snapshots:

1. stop the stack
2. remove `minio-data`
3. remove `control-plane-data`
4. start the stack again
5. bootstrap a new first admin

Example:

```bash
docker compose down
rm -rf minio-data control-plane-data
docker compose --env-file .env up --build -d
```

This is destructive and should only be used for disposable local environments.

### Useful inspections

Inspect current auth accounts:

```bash
docker compose exec -T control-plane \
  sqlite3 /var/lib/code-analyst/auth/auth.db \
  "select tenant_id, email, created_at, last_login_at from accounts order by tenant_id, email;"
```

Inspect pending registration invites:

```bash
docker compose exec -T control-plane \
  sqlite3 /var/lib/code-analyst/auth/auth.db \
  "select tenant_id, email, created_at, expires_at, used_at from registration_invites order by created_at desc;"
```

Inspect legacy app-state users for a tenant:

```bash
docker compose exec -T control-plane python -c "from control_plane_app.config import settings; from control_plane_app.object_store import ObjectStore; from control_plane_app.app_state_store import AppStateStore; db = AppStateStore(ObjectStore(settings)).load_tenant_db('tenant_local'); print([(u.email, u.is_admin, u.name) for u in db.users.values()])"
```

## Current backend slice

The control-plane now implements the first real backend slice for:

- `POST /v1/workspaces/imports/github`

The import flow currently:

1. clones the requested GitHub repository and ref
2. resolves the checked-out commit SHA
3. builds a snapshot manifest with file inventory and hashes
4. creates a `repo.tar.zst` workspace archive
5. uploads the archive, `manifest.json`, and `metadata.json` into MinIO

`github_credential_ref` currently supports:

- `public`
- `none`
- `env:VAR_NAME`

For token-based imports, use an `https` GitHub repository URL and provide the token through the named environment variable.

The sandbox-supervisor now implements the corresponding snapshot retrieval slice for:

- `POST /v1/sandboxes/sessions`

That flow currently:

1. downloads `manifest.json` from MinIO
2. downloads the snapshot archive referenced by the session request
3. expands the archive into a per-session local workspace directory
4. returns a sandbox session tied to the materialized snapshot

The control-plane now also wires the first real orchestration path for:

- `POST /v1/conversations/{conversation_id}/questions`
- `GET /v1/runs/{run_id}/events`

That flow currently:

1. resolves the workspace snapshot for the conversation
2. creates or resumes a sandbox session through the sandbox-supervisor
3. executes the question against that session
4. stores run events in the control-plane
5. replays those events through the run SSE endpoint

The control-plane now persists state into S3-compatible storage for:

- workspace snapshot heads and snapshot refs
- conversation heads and conversation events
- run state and run events

This means the control-plane can be reinitialized and still:

1. resolve the latest snapshot for a workspace
2. reload a conversation by ID
3. replay stored run events by run ID
4. continue a conversation using the persisted active sandbox reference

The sandbox execution step now performs grounded analysis over the
materialized workspace using the Claude agent adapter by default.

### Analysis backend configuration

The default analysis backend is **Claude** (`ANALYSIS_BACKEND=claude`).
To use it, you must provide an Anthropic API key:

**Option A — export on the host:**
```bash
export ANTHROPIC_API_KEY="sk-ant-api03-..."
docker compose up --build
```

**Option B — `.env` file in the repo root:**
```bash
echo "ANTHROPIC_API_KEY=sk-ant-api03-..." > .env
docker compose up --build
```

Docker Compose automatically reads `.env` and injects the key into the
`sandbox-supervisor` container.

> **Get a key:** https://console.anthropic.com/settings/keys

#### Fallback behavior

By default, `ANALYSIS_FALLBACK_TO_DETERMINISTIC=false`. If the Claude adapter
fails (e.g., missing key, rate limit), the request will return an error rather
than silently falling back to the deterministic inspector.

#### Switching to OpenAI (optional)

To use the OpenAI agent adapter instead:

```bash
export ANALYSIS_BACKEND=openai
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL=gpt-5.4-mini
docker compose up --build
```

#### Switching to deterministic (optional)

For local exploration without external APIs:

```bash
export ANALYSIS_BACKEND=deterministic
docker compose up --build
```

This runs a fast, rule-based inspector that scans text files and returns
grounded snippets. It requires no API keys but produces simpler answers.

## Integration test

The integration tests live at:

- [test_import_to_materialization.py](/Users/molbal/Documents/src/mechabee/code-analyst/tests/integration/test_import_to_materialization.py)
- [test_question_orchestration.py](/Users/molbal/Documents/src/mechabee/code-analyst/tests/integration/test_question_orchestration.py)

They validate these paths:

1. create a local git repository
2. import it through the control-plane workspace import service
3. upload the snapshot archive and manifest into S3-compatible storage
4. materialize that snapshot through the sandbox-supervisor workspace service
5. execute a question through the control-plane that calls the sandbox-supervisor
6. reload the control-plane state and continue using persisted conversation and run data

Run them from the repository root with:

```bash
poetry install --with dev
poetry run pytest tests/integration -v
```
