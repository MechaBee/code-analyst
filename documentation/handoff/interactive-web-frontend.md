# Handoff: Interactive Web Frontend Implementation

## Project Snapshot

**Code Analyst** — local-first code analysis SaaS platform.
- **Backend**: Python 3.11, FastAPI, Docker Compose, MinIO
- **Frontend Service Layer**: Node 24 LTS, Express
- **Frontend UI**: Next.js 15 (App Router), React 19, TypeScript
- **Current state**: 11 tests passing. Backend (Phases 0–5) is functionally complete.
- **Current frontend**: `apps/web/index.html` — static HTML landing page served by nginx
- **Goal**: Replace placeholder with an interactive chat UI backed by a Next.js static-export frontend and an Express service layer

## Current Frontend State

### Files
```
apps/web/
├── index.html          # Static placeholder (106 lines)
└── Dockerfile          # nginx:1.27-alpine, copies index.html
```

The `index.html` is a styled landing page with four cards. It has no JavaScript, no API calls, no chat interface.

### Docker Compose Wiring
```yaml
web:
  build:
    context: .
    dockerfile: apps/web/Dockerfile
  ports:
    - "3000:80"
  depends_on:
    - control-plane
```

The web container serves on **port 3000** and proxies nothing. The control-plane API is on **port 8080**.

**CORS situation**: The web app runs on `http://localhost:3000`. The FastAPI control-plane runs on `http://localhost:8080`. FastAPI does not have CORS middleware configured. The Express service layer will act as a reverse proxy so the browser calls same-origin `/api/...` paths. This avoids CORS entirely and is cleaner for production.

## API Surface for the Frontend

All endpoints the frontend needs to consume (proxied through Express):

### 1. Health Check
```
GET /api/health
→ {"name": "control-plane", "status": "ok", "timestamp": "..."}
```

### 2. Import Workspace
```
POST /api/v1/workspaces/imports/github
Body: {
  "tenant_id": "tenant_local",
  "repo_url": "https://github.com/...",
  "ref": "main",
  "github_credential_ref": "public"
}
→ {
  "workspace_id": "ws_...",
  "snapshot_id": "snap_...",
  "source_commit": "abc123...",
  "status": "READY",
  ...
}
```

### 3. Create Conversation
```
POST /api/v1/conversations
Body: {
  "tenant_id": "tenant_local",
  "workspace_id": "ws_...",
  "title": "My Analysis"
}
→ {"conversation_id": "conv_...", "status": "OPEN"}
```

### 4. Ask Question
```
POST /api/v1/conversations/{conversation_id}/questions
Body: {
  "message": "What does this codebase do?",
  "workspace_snapshot_id": null,      // optional
  "resume_sandbox": true,             // keep sandbox alive between questions
  "approval_policy": "auto"           // "auto" | "required"
}
→ {
  "run_id": "run_...",
  "status": "STARTED" | "COMPLETED" | "PENDING_APPROVAL",
  "events_url": "/v1/runs/{run_id}/events"
}
```

### 5. Stream Run Events (SSE)
```
GET /api/v1/runs/{run_id}/events
→ text/event-stream

event: run.started
data: {"run_id":"run_...","type":"run.started","payload":{"conversation_id":"conv_..."}}

event: run.progress
data: {"run_id":"run_...","type":"run.progress","payload":{"message":"Created sandbox session","sandbox_id":"sb_..."}}

event: citation.created
data: {"run_id":"run_...","type":"citation.created","payload":{"snapshot_id":"...","path":"README.md","start_line":1,"end_line":2,"excerpt_hash":"sha256:..."}}

event: approval.required
data: {"run_id":"run_...","type":"approval.required","payload":{"approval_id":"apr_...","message":"...","snapshot_id":"..."}}

event: run.completed
data: {"run_id":"run_...","type":"run.completed","payload":{"answer_markdown":"...","citations":[...],"followups":[...]}}

event: run.failed
data: {"run_id":"run_...","type":"run.failed","payload":{"message":"..."}}
```

### 6. Resolve Approval
```
POST /api/v1/runs/{run_id}/approvals/{approval_id}
Body: {"decision": "approve", "reason": "Looks good"}
→ {"run_id": "run_...", "approval_id": "apr_...", "status": "COMPLETED" | "FAILED"}
```

## Frontend Architecture

### Stack Choice: Node 24 + Express Service Layer + Next.js 15 (App Router)

**Why an Express service layer?**
- Clean separation: the Express layer handles proxying, request transformation, and potential future concerns (authentication, session management, rate limiting, caching) without touching the Python backend.
- Same-origin API calls for the SPA: Express proxies `/api/*` to the control-plane, eliminating CORS issues.
- The Express server owns the HTTP port; Next.js is a static-exported build that Express serves.

**Why Next.js App Router with static export?**
- App Router provides first-class React Server Components, nested layouts, and file-based routing.
- `output: 'export'` generates a fully static site (`dist/` or `out/`) that Express can serve with zero Node.js runtime overhead per request.
- Familiar, modern React patterns without needing a separate Vite + vanilla-TS toolchain.
- Component composability via React is a big win over imperative DOM manipulation for a chat UI.

**Why Node 24?**
- Node 24 is the latest LTS line with performance improvements, modern V8 features, and long-term support.
- Ensures compatibility with Next.js 15 and React 19.

### Proposed Directory Structure

```
apps/web/
├── server/
│   ├── index.ts           # Express entry point, starts HTTP server
│   ├── app.ts             # Express app setup (middleware, routes)
│   └── routes/
│       └── proxy.ts       # /api proxy to control-plane
├── src/
│   ├── app/
│   │   ├── layout.tsx     # Root layout (fonts, providers, global shell)
│   │   ├── page.tsx       # Main page: chat view + import flow
│   │   ├── globals.css    # Global styles + design tokens
│   │   └── (chat)/
│   │       ├── layout.tsx # Chat-specific layout
│   │       └── page.tsx   # Chat route (optional if everything lives in root)
│   ├── components/
│   │   ├── ChatView.tsx        # Message list + input
│   │   ├── MessageBubble.tsx   # User / assistant message rendering
│   │   ├── CitationCard.tsx    # File / line citation chip
│   │   ├── ApprovalModal.tsx   # Approve / deny overlay
│   │   ├── WorkspaceImport.tsx # GitHub URL input + import button
│   │   └── EventLog.tsx        # Debug: raw SSE event stream viewer
│   ├── hooks/
│   │   ├── useApi.ts          # HTTP client wrappers (fetch)
│   │   ├── useEventSource.ts  # SSE subscription hook
│   │   └── useAppState.ts     # Lightweight global state (React Context)
│   ├── types/
│   │   └── api.ts             # Frontend type mirrors of API contracts
│   └── lib/
│       └── utils.ts           # Helpers (cn, formatters, etc.)
├── public/
│   └── (static assets)
├── next.config.ts         # Next.js config: output: 'export', distDir: 'dist'
├── tsconfig.json
├── package.json
└── Dockerfile             # Multi-stage: build Next.js, then run Express
```

> **Next.js `output: 'export'` note**: Because we export statically, Next.js cannot use Server Components that fetch data at request time. All data fetching (API calls, SSE) happens in Client Components (`'use client'`). This is correct for our architecture — Express handles the runtime; Next.js provides the UI build.

### Key Implementation Details

#### 1. Express Reverse Proxy (REQUIRED for CORS)

The Express server runs on port 3000. It serves the built Next.js static assets and proxies `/api/*` to the control-plane.

**`server/app.ts`**
```typescript
import express from 'express';
import { createProxyMiddleware } from 'http-proxy-middleware';
import path from 'path';

const app = express();

// Proxy API calls to the control-plane
app.use(
  '/api',
  createProxyMiddleware({
    target: process.env.CONTROL_PLANE_URL || 'http://control-plane:8080',
    changeOrigin: true,
    pathRewrite: { '^/api': '' },
    onProxyReq: (proxyReq, req) => {
      proxyReq.setHeader('host', req.headers.host || 'localhost');
    },
  })
);

// Serve static files from Next.js build output
app.use(express.static(path.join(__dirname, '../dist')));

// SPA fallback: send index.html for any non-API route
app.get('*', (_req, res) => {
  res.sendFile(path.join(__dirname, '../dist/index.html'));
});

export default app;
```

**`server/index.ts`**
```typescript
import app from './app';

const PORT = process.env.PORT || 3000;

app.listen(PORT, () => {
  console.log(`Web service listening on port ${PORT}`);
});
```

The frontend then calls `/api/health`, `/api/v1/conversations`, etc. — same-origin, no CORS needed.

#### 2. SSE Stream Handler (Client Component)

Use `EventSource` inside a React effect for SSE. The backend emits `event: {type}` lines. Listen for specific event types:

```typescript
'use client';
import { useEffect } from 'react';

export function useRunEvents(runId: string, handlers: EventHandlers) {
  useEffect(() => {
    const es = new EventSource(`/api/v1/runs/${runId}/events`);
    es.addEventListener('run.progress', (e) => handlers.onProgress?.(JSON.parse(e.data)));
    es.addEventListener('citation.created', (e) => handlers.onCitation?.(JSON.parse(e.data)));
    es.addEventListener('approval.required', (e) => handlers.onApproval?.(JSON.parse(e.data)));
    es.addEventListener('run.completed', (e) => { handlers.onCompleted?.(JSON.parse(e.data)); es.close(); });
    es.addEventListener('run.failed', (e) => { handlers.onFailed?.(JSON.parse(e.data)); es.close(); });
    return () => es.close();
  }, [runId]);
}
```

#### 3. Approval Flow UI
When `approval.required` event arrives:
1. Pause the chat input.
2. Show a modal: "This question requires approval before execution".
3. Buttons: **Approve** → `POST /api/v1/runs/{run_id}/approvals/{approval_id}` → then re-subscribe to SSE for resumed run.
4. Buttons: **Deny** → same POST with `{"decision": "deny"}` → show failure message.

#### 4. State Management
A lightweight reactive store using React Context (no Redux / Zustatand needed for MVP):

```typescript
type AppState = {
  currentView: 'import' | 'chat';
  workspaceId: string | null;
  snapshotId: string | null;
  conversationId: string | null;
  messages: Array<{ role: 'user' | 'assistant'; content: string; citations?: any[] }>;
  pendingApproval: { runId: string; approvalId: string; message: string } | null;
  isLoading: boolean;
};
```

Wrap the app in a `AppStateProvider` in `layout.tsx`. Components consume via a custom `useAppState()` hook.

#### 5. Chat View Layout
```
+----------------------------------+
|  Code Analyst          [Import]  |  ← Header
+----------------------------------+
|                                  |
|  User: What does this repo do?   |  ← Message bubbles
|                                  |
|  Assistant: This is a...         |
|  [README.md L1-2] [service.py]   |  ← Citation chips
|                                  |
|  [Thinking...]                   |  ← Loading state
|                                  |
+----------------------------------+
|  [Type a question...] [Send]     |  ← Input bar
+----------------------------------+
```

#### 6. Citation Rendering
Each citation should be a clickable chip:
- Label: `README.md L1-2`
- On click: expand inline to show excerpt (the backend does not return excerpt text in the citation, only hash — consider fetching from backend or just show path/line)
- For MVP, linking to a file viewer is out of scope. Just show path + line numbers.

## Step-by-Step Implementation Plan

### Phase 0: Express Service Layer (1–2 hours)
1. Initialize the Node project in `apps/web/` with `npm init -y`.
2. Add dependencies: `express`, `http-proxy-middleware`, `typescript`, `tsx`, `@types/express`, `@types/node`.
3. Create `tsconfig.server.json` (or a composite setup) targeting the `server/` directory.
4. Create `server/app.ts` and `server/index.ts` as shown above.
5. Add a `start` script to `package.json`: `"start": "tsx server/index.ts"`.
6. Verify: `npm start` runs on port 3000 and returns a health message.

### Phase 1: Next.js Tooling & Proxy (1–2 hours)
1. Initialize Next.js project inside `apps/web/`: `npx create-next-app@latest . --typescript --tailwind --eslint --app --src-dir --import-alias "@/*"`.
2. Update `next.config.ts` to static export:
   ```typescript
   import type { NextConfig } from 'next';
   const nextConfig: NextConfig = {
     output: 'export',
     distDir: 'dist',
   };
   export default nextConfig;
   ```
3. In local dev, run Next.js dev server (`npm run dev` on port 3000) **and** Express proxy on another port (e.g., 3001), or configure Next.js rewrites to proxy `/api` to Express.
   - **Recommended dev mode**: run Express on `3000` and proxy `/` to Next.js dev server via `http-proxy-middleware` so API + UI share one origin. Alternatively, run both and point the browser at Express.
4. Update `apps/web/Dockerfile` to a Node 24 multi-stage build:
   - Stage 1: `node:24-alpine` → install deps, build Next.js static export (`dist/`).
   - Stage 2: `node:24-alpine` → copy `dist/` and `server/`, install **production** deps only, run `tsx server/index.ts`.
5. Update `docker-compose.yml` if needed (ensure `web` depends on `control-plane`).
6. Test: `docker compose up --build` → open `http://localhost:3000` → should see the Next.js starter page.

### Phase 2: API Types & Client Hooks (1–2 hours)
1. Create `src/types/api.ts` — mirror the API request/response types.
2. Create `src/hooks/useApi.ts`:
   - `importWorkspace(repoUrl: string)`
   - `createConversation(workspaceId: string)`
   - `askQuestion(conversationId: string, message: string)`
   - `resolveApproval(runId: string, approvalId: string, decision: string)`
3. Create `src/hooks/useEventSource.ts` — React hook wrapping `EventSource` with run-id lifecycle.
4. Wire proxy in dev so frontend can call `/api/...`.

### Phase 3: Core UI Components (3–4 hours)
1. `WorkspaceImport` component: URL input + import button → on success, store workspace/snapshot IDs, switch to chat view.
2. `ChatView` component: message list + input form.
3. `MessageBubble` component: render markdown (use `react-markdown` or `marked` + `dangerouslySetInnerHTML`) + citation chips.
4. Wire submit flow: input → `askQuestion` → `useEventSource` → append events as messages.
5. Handle `run.completed`: render final answer with citations.
6. Handle `run.failed`: render error message.

### Phase 4: Approval Flow UI (1–2 hours)
1. `ApprovalModal` component: overlay with message context + approve/deny buttons.
2. On `approval.required` event: show modal, pause chat input.
3. On approve: call `resolveApproval` → re-subscribe to events → show "Resuming..."
4. On deny: call `resolveApproval` → show "Denied: {reason}"

### Phase 5: Polish (1–2 hours)
1. Add loading states / skeletons.
2. Add error handling (network errors, 404s, etc.).
3. Style with Tailwind (already included by `create-next-app`) mapped to the existing warm palette tokens.
4. Add a conversation sidebar (list of past conversations) — optional for MVP.
5. Make it responsive.

### Phase 6: Docker Integration & Testing (1 hour)
1. Ensure production build works: `npm run build` → outputs static files to `dist/`.
2. Ensure Dockerfile copies `dist/` and `server/` and starts the Express app with `tsx`.
3. Ensure docker-compose build succeeds.
4. Run end-to-end test: import repo → ask question → see answer with citations.
5. Run approval flow test: ask with `approval_policy=required` → approve → see answer.

## Environment Variables

```bash
# Express service layer
PORT=3000
CONTROL_PLANE_URL=http://control-plane:8080   # in Docker
CONTROL_PLANE_URL=http://localhost:8080       # local dev

# Next.js build (optional)
NEXT_PUBLIC_API_BASE_URL=/api   # dev + prod (always same-origin via Express)
```

## Testing Strategy

### Unit Tests
Next.js ships with Jest support. Add component tests for:
- `MessageBubble` rendering markdown + citations correctly.
- `ApprovalModal` fires correct callbacks on approve / deny.

### Integration / E2E Tests
Add Playwright to `apps/web/` with a single happy-path test that:
1. Opens `http://localhost:3000`
2. Enters a GitHub repo URL
3. Clicks Import
4. Waits for workspace creation
5. Types a question
6. Clicks Send
7. Asserts that an answer appears with citations

### Manual Test Checklist
- [ ] Import a public GitHub repo
- [ ] Create a conversation
- [ ] Ask a question (auto mode)
- [ ] See SSE events stream in real-time
- [ ] See final answer with citations
- [ ] Ask follow-up question (resume sandbox)
- [ ] Ask question with `approval_policy=required`
- [ ] See approval modal
- [ ] Click Approve → see answer
- [ ] Click Deny → see error
- [ ] Refresh page → state is lost (acceptable for MVP; persistence is a future feature)

## Critical Decisions to Make

### 1. Frontend Framework
**Selected**: Next.js 15 App Router with static export.

**Why not plain Vite?** Next.js gives us file-based routing, built-in TypeScript + Tailwind scaffolding, and React Server Components (where applicable). For a chat UI with many small interactive pieces, React component model is significantly more productive than imperative DOM manipulation.

**Why static export instead of server-side Next.js?** The Express layer already owns the server. Running Next.js in standalone/server mode would duplicate that responsibility and complicate Docker orchestration. Static export keeps the boundary clean: Next.js = UI build; Express = runtime server.

**Avoid**: Next.js `output: 'standalone'` (unnecessary when Express serves the static build), heavy state-management libraries.

### 2. Styling Approach
**Default recommendation**: Tailwind CSS (already scaffolded by `create-next-app`).

Map Tailwind theme tokens to the existing warm palette:
```js
// tailwind.config.ts
colors: {
  cream: '#f3f0e8',
  panel: '#fffaf1',
  ink: '#1e241f',
  accent: '#135d66',
  muted: '#66706a',
  line: '#d9d1c4',
}
```

### 3. Markdown Rendering
The backend returns `answer_markdown` in the final answer. Recommended packages:
- `react-markdown` (React-first, extensible, works well with Tailwind via custom components)
- `remark-gfm` for GitHub-flavored tables, checkboxes, etc.

### 4. State Persistence
For MVP, state lives in React Context (in-memory). Refreshing the page loses the conversation.

**Future enhancement**: Store `conversation_id` in `localStorage` and hydrate on load. Add a `GET /v1/conversations/{id}` endpoint to fetch history (does not exist yet).

## Backend Changes Likely Needed

As you build the frontend, you may discover gaps. These are acceptable to add:

1. **CORS middleware** (if you skip the Express proxy approach):
   ```python
   from fastapi.middleware.cors import CORSMiddleware
   app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], ...)
   ```

2. **`GET /v1/conversations/{conversation_id}`** to fetch conversation history (for page reload persistence)

3. **`GET /v1/workspaces`** to list imported workspaces (for a workspace picker)

4. **`GET /v1/conversations`** to list conversations (for a sidebar)

## Docker Commands for Development

```bash
# Full stack rebuild
docker compose up --build

# Next.js dev server only (runs on localhost:3000 by default)
cd apps/web
npm install
npm run dev

# Express service only (in another terminal, if you want to run the proxy separately)
cd apps/web
npm start              # serves on localhost:3000, proxies /api to control-plane

# Production build test
cd apps/web
npm run build          # outputs static files to dist/
docker compose up --build web
```

## Existing Design Tokens

From `apps/web/index.html`, the current palette is:
```css
--bg: #f3f0e8;      /* warm cream background */
--panel: #fffaf1;   /* card background */
--ink: #1e241f;     /* primary text */
--accent: #135d66;  /* teal accent */
--muted: #66706a;   /* secondary text */
--line: #d9d1c4;    /* borders */
```

Keep these or evolve them. The existing aesthetic is warm, calm, and professional — appropriate for a developer tool.

## Reference: Backend File Map

| File | What it does |
|------|-------------|
| `services/control-plane/control_plane_app/main.py` | FastAPI routes |
| `services/control-plane/control_plane_app/question_orchestrator.py` | Run lifecycle (setup → approval → execute) |
| `services/control-plane/control_plane_app/state_store.py` | S3-backed persistence for conversations, runs, approvals |
| `packages/contracts-python/src/code_analyst_contracts/contracts.py` | All Pydantic models / API types |
| `tests/integration/test_question_orchestration.py` | Integration tests showing the full flow |

## One-Sentence Reminder

**Build a Node 24 / Express service in `apps/web/server` that proxies the FastAPI backend, and a Next.js 15 App Router static-export frontend that implements a real-time chat interface over SSE, including the approval flow with a modal dialog.**
