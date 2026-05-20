"""Operator CLI for server setup, health, tokens, and development runs."""

from pathlib import Path
import os
import subprocess
import sys

from alembic import command
from alembic.config import Config
import httpx
import typer
import uvicorn

from creative_workflow.server.app import create_app
from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.session import make_session_factory
from creative_workflow.server.services.job_queue import JobQueueService
from creative_workflow.server.services.worker_auth import WorkerAuthService

app = typer.Typer(help="Server/control-plane commands.")
config_app = typer.Typer(help="Configuration commands.")
db_app = typer.Typer(help="Database commands.")
worker_token_app = typer.Typer(help="Worker token commands.")
cleanup_app = typer.Typer(help="Artifact cleanup commands.")
llm_app = typer.Typer(help="Local LLM health commands.")
app.add_typer(config_app, name="config")
app.add_typer(db_app, name="db")
app.add_typer(worker_token_app, name="worker-token")
app.add_typer(cleanup_app, name="cleanup")
app.add_typer(llm_app, name="llm")


def _settings() -> ServerSettings:
    return ServerSettings.load()


@config_app.command("check")
def config_check():
    settings = _settings()
    errors = settings.validate()
    if errors:
        for error in errors:
            typer.echo(f"FAIL: {error}")
        raise typer.Exit(1)
    typer.echo("OK: server configuration is valid.")
    typer.echo(f"Database: {settings.database_url}")
    typer.echo(f"Artifact root: {settings.artifact_root}")
    typer.echo(f"Trusted workers: {', '.join(sorted(settings.trusted_worker_ids))}")


@db_app.command("migrate")
def db_migrate():
    settings = _settings()
    os.environ["DATABASE_URL"] = settings.database_url
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    typer.echo("OK: database migrated to head.")


@worker_token_app.command("create")
def worker_token_create(worker_id: str = typer.Option("designer-laptop-01", "--worker-id")):
    settings = _settings()
    session_factory = make_session_factory(settings.database_url)
    with session_factory() as db:
        created = WorkerAuthService(db, settings).create_token(worker_id)
    typer.echo(f"Worker ID: {created.worker_id}")
    typer.echo(f"Worker token: {created.token}")
    typer.echo("Copy this token into WORKER_TOKEN on the designer laptop. It will not be shown again.")


@worker_token_app.command("revoke")
def worker_token_revoke(worker_id: str = typer.Option("designer-laptop-01", "--worker-id")):
    settings = _settings()
    session_factory = make_session_factory(settings.database_url)
    with session_factory() as db:
        revoked = WorkerAuthService(db, settings).revoke_token(worker_id)
    if not revoked:
        typer.echo("FAIL: token not found.")
        raise typer.Exit(1)
    typer.echo(f"OK: revoked token for {worker_id}.")


@app.command("dev")
def dev(host: str = "0.0.0.0", port: int = 8000):
    settings = _settings()
    errors = settings.validate()
    if errors:
        for error in errors:
            typer.echo(f"FAIL: {error}")
        raise typer.Exit(1)
    typer.echo(f"Operator console:  http://127.0.0.1:{port}/app/")
    typer.echo(f"API docs:          http://127.0.0.1:{port}/docs")
    uvicorn.run(create_app(settings), host=host, port=port)


@app.command("ui")
def ui(port: int = 8501):
    target = Path(__file__).parent / "ui" / "streamlit_app.py"
    env = os.environ.copy()
    env.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(target),
            "--server.port",
            str(port),
            "--server.address",
            "0.0.0.0",
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        check=True,
        env=env,
    )


@app.command("healthcheck")
def healthcheck():
    settings = _settings()
    try:
        response = httpx.get(f"{settings.server_public_base_url.rstrip('/')}/api/v1/health", timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        typer.echo(f"FAIL: server healthcheck failed: {exc}")
        raise typer.Exit(1) from exc
    typer.echo("OK: server API is healthy.")
    typer.echo(response.text)


@cleanup_app.command("dry-run")
def cleanup_dry_run():
    settings = _settings()
    root = settings.artifact_root
    count = len(list(root.rglob("*"))) if root.exists() else 0
    typer.echo(f"OK: dry run found {count} filesystem entries under {root}. No files were deleted.")


@cleanup_app.command("apply")
def cleanup_apply():
    typer.echo("Retention cleanup is intentionally conservative in Gate A. Use dry-run for inspection.")


@llm_app.command("healthcheck")
def llm_healthcheck():
    settings = _settings()
    try:
        response = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        typer.echo(f"FAIL: local LLM endpoint is not reachable: {exc}")
        raise typer.Exit(1) from exc

    payload = response.json()
    model_names = {model.get("name", "") for model in payload.get("models", [])}
    if settings.ollama_model not in model_names:
        typer.echo(f"FAIL: Ollama is reachable, but model '{settings.ollama_model}' is not installed.")
        typer.echo(f"Available models: {', '.join(sorted(model_names)) or '(none)'}")
        raise typer.Exit(1)
    typer.echo(f"OK: local LLM endpoint is reachable and model '{settings.ollama_model}' is installed.")


@app.command("mark-orphans")
def mark_orphans():
    settings = _settings()
    session_factory = make_session_factory(settings.database_url)
    with session_factory() as db:
        count = JobQueueService(db, settings).mark_orphaned_expired_leases()
    typer.echo(f"OK: marked {count} expired leased jobs as orphaned.")


@app.command("attach-orphans")
def attach_orphans():
    """Fold every pre-chat task into an 'Earlier work' conversation.

    Tasks created before the chat-driven console keep `conversation_id`
    NULL, which means they don't appear in the new left rail. This
    command creates a single 'Earlier work' conversation and links those
    tasks to it, seeding a synthetic agent message per task so the chat
    has something to render. Idempotent — running it again only attaches
    tasks that are still orphaned.
    """

    from sqlalchemy import func, select
    from creative_workflow.server.db.models import Conversation, Message, Run, Task
    from creative_workflow.shared.ids import new_id

    settings = _settings()
    factory = make_session_factory(settings.database_url)
    with factory() as db:
        orphan_count = db.scalar(
            select(func.count(Task.task_id)).where(Task.conversation_id.is_(None))
        ) or 0
        if not orphan_count:
            typer.echo("OK: no orphan tasks found.")
            return
        # Reuse a single 'Earlier work' conversation if it already exists.
        conv = db.scalars(
            select(Conversation).where(Conversation.title == "Earlier work")
        ).first()
        if conv is None:
            conv = Conversation(conversation_id=new_id("conv"), title="Earlier work")
            db.add(conv)
            db.flush()
        orphans = list(
            db.scalars(
                select(Task)
                .where(Task.conversation_id.is_(None))
                .order_by(Task.created_at)
            ).all()
        )
        attached = 0
        for task in orphans:
            task.conversation_id = conv.conversation_id
            latest_run = db.scalars(
                select(Run).where(Run.task_id == task.task_id).order_by(Run.attempt_number.desc())
            ).first()
            db.add(
                Message(
                    message_id=new_id("msg"),
                    conversation_id=conv.conversation_id,
                    role="agent",
                    content=(
                        f"Earlier task: \"{task.title}\" "
                        f"({task.workflow_state.replace('_', ' ')})."
                    ),
                    related_task_id=task.task_id,
                    related_run_id=latest_run.run_id if latest_run else None,
                )
            )
            attached += 1
        db.commit()
    typer.echo(
        f"OK: attached {attached} orphan task(s) to the 'Earlier work' conversation."
    )


if __name__ == "__main__":
    app()
