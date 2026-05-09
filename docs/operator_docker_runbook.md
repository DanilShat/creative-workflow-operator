# Operator Docker Runbook

Docker is the preferred operator-side runtime for the server stack:

- PostgreSQL
- FastAPI API
- Streamlit UI
- database migration job
- artifact storage volume

The designer worker remains a native Windows process because it needs headed
browser sessions, future Claude Desktop control, and Adobe host-app access.
Only the `api` service builds the shared operator image; `migrate` and `ui`
reuse that image so rebuilds stay reasonably fast during development.
Inside Docker, Streamlit calls FastAPI through `API_INTERNAL_BASE_URL=http://api:8000`;
the browser and worker still use `SERVER_PUBLIC_BASE_URL`.

## Prerequisites

- Docker Desktop is installed and running.
- Ollama is running on the Windows host if local LLM checks/workflows are used.
- The model in `.env.docker` exists in Ollama, default `gemma3n:e2b`.
- Docker publishes PostgreSQL on host port `55432` by default so it does not
  conflict with a native Windows PostgreSQL on `5432`.

Check Docker:

```powershell
docker --version
docker compose version
```

## First Start

For local-only testing:

```powershell
cd D:\design_agent_pet_project\creative_workflow_operator
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_up.ps1 -Build
```

For a real designer laptop on the LAN, use the operator laptop LAN IP:

```powershell
cd D:\design_agent_pet_project\creative_workflow_operator
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_up.ps1 `
  -ServerPublicBaseUrl http://192.168.1.124:8000 `
  -Build
```

Open:

```text
http://127.0.0.1:8501
```

or from the designer laptop:

```text
http://192.168.1.124:8501
```

## Status And Logs

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_status.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_logs.ps1
```

Follow one service:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_logs.ps1 -Service api
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_logs.ps1 -Service ui
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_logs.ps1 -Service postgres
```

## Worker Token

Create a token for the native designer worker:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_worker_token.ps1 `
  -WorkerId designer-laptop-01
```

Put the token in the designer laptop `.env.worker`:

```text
SERVER_BASE_URL=http://192.168.1.124:8000
WORKER_ID=designer-laptop-01
WORKER_TOKEN=<token>
```

## Stop

Stop containers but keep database/artifacts:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_down.ps1
```

Stop and delete Docker volumes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\docker_operator_down.ps1 -Volumes
```

Use `-Volumes` only when you intentionally want to reset the Docker database
and artifact store.

## Native Versus Docker

Native scripts still exist for debugging on Windows. Docker should be used for
operator-side reproducibility. The worker should stay native.
