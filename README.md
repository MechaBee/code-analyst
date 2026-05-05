# Code Analyst

Code Analyst is a self-hosted GitHub repository analysis app. It lets teams register repositories, create immutable checkouts for a branch or ref, start conversations against a workspace snapshot, and get grounded answers with citations back to the code.

The current implementation is focused on GitHub repositories. The repository model is designed to expand to additional providers over time, including GitLab.

## What It Does

- Register repositories for analysis
- Support public GitHub repositories and token-based access to private ones
- Create checkouts tied to a branch, tag, or ref
- Start conversations against a specific workspace snapshot
- Return grounded answers with citations from the analyzed codebase
- Manage onboarding and repository access through admin and team workflows

## Current Scope

- Repository provider support is currently GitHub-only
- Public repositories work without credentials
- Private repositories currently use token-based authentication
- The default deployment path is local-first and Docker Compose-based
- Future repository-provider support is planned, including GitLab

## How It Works

1. An admin adds a repository and chooses its access mode.
2. A user creates a checkout for a branch or ref.
3. The control plane clones the repository and records a workspace snapshot.
4. The sandbox supervisor materializes that snapshot in an isolated workspace.
5. The user asks questions and receives cited answers grounded in the checked-out code.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- For local development: Python `3.11.11`, Poetry, Node.js `v24.12.0`, and pnpm

### 1. Create `.env`

Use deterministic analysis for a zero-API-key local evaluation, or switch to an LLM-backed backend when you are ready.

```env
AUTH_BOOTSTRAP_SECRET=replace-with-a-random-secret
ANALYSIS_BACKEND=deterministic

# Optional: OpenAI-backed analysis
# ANALYSIS_BACKEND=openai
# OPENAI_API_KEY=your-openai-api-key
# OPENAI_MODEL=gpt-5.4-mini
# OPENAI_REASONING_EFFORT=low

# Optional: Claude-backed analysis
# ANALYSIS_BACKEND=claude
# ANTHROPIC_API_KEY=your-anthropic-api-key
```

### 2. Start the stack

```bash
docker compose --env-file .env up --build -d
```

### 3. Open the app

- Web UI: `http://localhost:3000`
- Control plane health: `http://localhost:8080/health`
- Sandbox supervisor health: `http://localhost:8090/health`
- MinIO console: `http://localhost:9001`

## First-Time Setup

Generate a bootstrap secret if you do not already have one:

```bash
openssl rand -hex 32
```

Create the first admin invitation:

```bash
curl -sS -X POST http://localhost:8080/v1/auth/bootstrap/invitations \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: tenant_local' \
  -d '{
    "email": "you@example.com",
    "name": "First Admin",
    "bootstrap_secret": "replace-with-your-bootstrap-secret"
  }'
```

Use the returned `invite_url` to:

1. open the registration page
2. create the first admin account
3. sign in and open `/admin`

## Using the App

### Admin flow

1. Sign in through the bootstrap or admin-issued link.
2. Open `/admin` to create teams and invite users.
3. Open `/repos` to add a repository.
4. Choose `public` for a public repository or `token` for a private repository.

### Analyst flow

1. Open the repository and create a checkout for a branch or ref.
2. Go to the dashboard and start a conversation for that checkout.
3. Ask questions about the codebase and review the returned citations.

## Key Configuration

- `AUTH_BOOTSTRAP_SECRET`: required for first-admin bootstrap
- `ANALYSIS_BACKEND`: `deterministic`, `openai`, or `claude`
- `OPENAI_API_KEY`: required when `ANALYSIS_BACKEND=openai`
- `OPENAI_MODEL`: OpenAI model name for the sandbox analysis backend
- `OPENAI_REASONING_EFFORT`: OpenAI reasoning effort level
- `ANTHROPIC_API_KEY`: required when `ANALYSIS_BACKEND=claude`
- `NEXT_PUBLIC_TENANT_ID`: optional frontend tenant override, defaults to `tenant_local`

## Project Layout

- `apps/web`: Next.js web application
- `services/control-plane`: FastAPI API for auth, repositories, checkouts, and conversations
- `services/sandbox-supervisor`: FastAPI service for sandbox materialization and analysis
- `packages/contracts/python`: shared Pydantic contracts
- `docs`: planning, architecture, and handoff notes

## Development

Install development dependencies:

```bash
poetry install
pnpm --dir apps/web install
```

Useful commands:

```bash
poetry run pytest
pnpm --dir apps/web typecheck
pnpm --dir apps/web build
pnpm --dir apps/web test:e2e
```

For most local work, Docker Compose is the supported way to run the full stack.

## Limitations

- Only GitHub repositories are supported today
- Private repository access is token-based rather than provider app installation-based
- The default deployment target is local-first, not production-hardened
- The quick start is intended for local evaluation and development

## Roadmap Direction

- Add repository-provider support beyond GitHub, including GitLab
- Introduce stronger provider-native authentication flows
- Expand repository, checkout, and conversation workflows
- Improve operational visibility and production readiness

## Contributing

Contributions are welcome. For larger changes, start with an issue or design note describing the problem, the proposed approach, and any expected API or UX impact.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
