# Creative Workflow Operator

Operator-side backend and UI for the creative workflow automation system.

This repo owns:

- FastAPI control-plane API
- Streamlit operator UI
- PostgreSQL schema and migrations
- worker token issuance and worker protocol endpoints
- artifact storage metadata and Docker deployment
- local Ollama-compatible LLM orchestration

The designer laptop worker lives in a separate repo:

```text
https://github.com/DanilShat/creative-workflow-worker
```

## Quick Start

Install Docker Desktop, start it, then run:

```powershell
cd D:\design_agent_pet_project\creative_workflow_operator
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_up.ps1 -Build
```

Open:

```text
http://127.0.0.1:8501
```

For a designer laptop on the LAN:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_up.ps1 `
  -ServerPublicBaseUrl http://<operator-lan-ip>:8000 `
  -Build
```

Create a worker token:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_worker_token.ps1 `
  -WorkerId designer-laptop-01
```

## Checks

```powershell
python -m pip install -e ".[test]"
python -m pytest tests -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_status.ps1
```

## Runtime Notes

Real secrets stay in local `.env.*` files and are ignored by git. Commit only
`.env.*.example` files.
