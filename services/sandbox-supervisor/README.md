# Sandbox Supervisor

FastAPI service responsible for sandbox session lifecycle and execution in the
local-first platform.

The supervisor now supports two execution backends:

- `deterministic`: local lexical code inspection over the materialized workspace
- `openai`: an OpenAI Agents SDK-based analysis adapter that uses local tools to
  list files, search text, and read file excerpts before returning a grounded
  answer

The backend is selected through `ANALYSIS_BACKEND` and defaults to
`deterministic`.
