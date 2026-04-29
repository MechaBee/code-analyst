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
docker compose up --build
```

Available endpoints:

- `http://localhost:3000`: interactive chat UI (import repo, ask questions, view citations)
- `http://localhost:8080/health`: control-plane health
- `http://localhost:8090/health`: sandbox-supervisor health
- `http://localhost:9001`: MinIO console

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
