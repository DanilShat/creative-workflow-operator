# Agent Manifest - Operator Repo

Read this before implementing Claude, browser-assisted, Photoshop, or After
Effects features in this repo.

Canonical design source:

```text
../creative_workflow_docs_library/CLAUDE_CODE_COLLABORATION_MANIFEST.md
```

## Operator responsibilities

The operator repo owns authoritative state:

- task, run, job, asset, review records
- worker token authentication
- artifact storage
- Streamlit UI
- local LLM orchestration
- job creation and retry workflow

Claude must never bypass these boundaries. Claude-facing tools should call
operator API endpoints or create typed worker jobs.

## Planned operator additions

1. Keep `POST /api/v1/tasks/agent-chat` as the generic chat escalation path.
2. Add a `GET /api/v1/tasks/{task_id}/agent-handoff` endpoint if a future CLI needs a copyable packet.
3. Add job types or action names for:
   - `designer_agent_chat`
   - `photoshop_typed_action`
   - `aftereffects_typed_action`
4. Add read-side summaries for MCP tools.
5. Add review-note APIs that preserve who/what submitted the note.
6. Add audit events for Claude/Codex-requested actions.

## Handoff packet shape

The server-generated packet should be plain Markdown with a JSON block:

```json
{
  "task_id": "task_x",
  "workflow_state": "waiting_human_review",
  "brief": "designer brief",
  "latest_artifacts": [],
  "available_actions": [],
  "safety_rules": []
}
```

The packet is designed for Claude Desktop or Claude Code to read without
needing direct database access.

## Operator safety rules

- Keep the server as source of truth.
- Require worker auth for execution and artifact upload.
- Store Claude decisions as review notes or requested actions, not raw state
  mutations.
- Do not add server-side Claude or Codex API calls for this path. Claude Code
  and Codex are local subscription CLIs on the designer laptop.
- Do not mark Photoshop/After Effects live until a real local install executes
  the typed action.

## Handoff Log

### 2026-05-10 - Codex
- Context: Added operator-side manifest for future Claude/browser/DCC work.
- Decision: Implement Claude through handoff packets, MCP/read APIs, and typed
  jobs; do not let Claude mutate DB state directly.
- Files changed: `AGENT_MANIFEST.md`, README pointer.
- Tests run: documentation-only change; no tests required.
- Open questions: final endpoint names and whether MCP server lives in worker
  repo only or also gets a small operator client package.

### 2026-05-10 - Claude Code + Codex
- Context: Claude Code added `variant_count` to Gate A start so Claude/MCP can
  fan out multiple browser jobs from one chat request.
- Decision: Keep fan-out on the operator service; the worker still claims one
  queued job at a time through the existing protocol.
- Files changed: task contracts, task API, workflow service, README.
- Tests run: operator pytest suite.
- Open questions: dedicated Claude handoff endpoint and audit trail remain
  planned operator work.

### 2026-05-12 - Codex
- Context: Added chat-style agent jobs so Streamlit can queue work to local
  Ollama, Claude Code CLI, and Codex CLI through the worker protocol.
- Decision: Treat Claude/Codex as subscription CLIs logged in on the designer
  laptop, not as server-side API integrations.
- Files changed: task API/contracts, workflow service, Streamlit UI, README.
- Tests run: targeted operator API/service/contract tests.
- Open questions: exact non-interactive CLI flags may need adjustment per
  installed Claude Code/Codex versions during live laptop validation.
