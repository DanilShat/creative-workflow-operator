# Environment examples

## Operator `.env.server`
```env
## Find the operator LAN IP on Windows with:
##   ipconfig | findstr IPv4
DATABASE_URL=postgresql+psycopg://creative:creative@localhost:5432/creative_workflow
SERVER_PUBLIC_BASE_URL=http://192.168.1.10:8000
ARTIFACT_ROOT=./runtime_data/artifacts
SERVER_SECRET=change-me-long-random-secret-at-least-32-chars
ALLOW_WORKER_REGISTRATION=false
TRUSTED_WORKER_IDS=designer-laptop-01
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=gemma3n:e2b
```

## Optional Claude MCP `.env`
```env
CLAUDE_MCP_SERVER_NAME=creative-workflow-tools
SERVER_BASE_URL=http://192.168.1.10:8000
WORKER_ID=designer-laptop-01
WORKER_TOKEN=paste-generated-token-here
MCP_ALLOWED_ACTIONS=get_current_task_context,list_available_actions,submit_review_note,request_photoshop_action_job,request_aftereffects_action_job
```
