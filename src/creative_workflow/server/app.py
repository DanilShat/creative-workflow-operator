"""FastAPI server application factory.

The API is the stable boundary for the worker protocol, task state, artifact
handling, and orchestration services. Streamlit talks to these server services;
the worker never talks to Streamlit.
"""

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from creative_workflow.server.api import assets, health, jobs, tasks, workers
from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.session import make_session_factory
from creative_workflow.server.services.job_queue import JobQueueService
from creative_workflow.shared.contracts.api import ApiError, ErrorEnvelope


async def _orphan_sweep_loop(settings: ServerSettings) -> None:
    """Periodically release expired job leases so stranded jobs self-heal.

    Without this, a worker that crashes (or loses the server) mid-job leaves
    the job CLAIMED and the worker locked out of claiming anything new until
    someone runs the `server mark-orphans` CLI by hand. The sweep makes that
    recovery automatic once the lease expires.
    """

    factory = make_session_factory(settings.database_url)

    def _sweep_once() -> int:
        db = factory()
        try:
            return JobQueueService(db, settings).mark_orphaned_expired_leases()
        finally:
            db.close()

    while True:
        await asyncio.sleep(settings.orphan_sweep_interval_s)
        try:
            # The DB session is synchronous; keep it off the event loop.
            count = await asyncio.to_thread(_sweep_once)
            if count:
                print(f"[orphan-sweep] released {count} expired job lease(s)", flush=True)
        except Exception as exc:  # noqa: BLE001 - the sweep must keep running
            print(f"[orphan-sweep] error: {exc}", flush=True)


def create_app(settings: ServerSettings | None = None) -> FastAPI:
    resolved_settings = settings or ServerSettings.load()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        sweep = asyncio.create_task(_orphan_sweep_loop(resolved_settings))
        try:
            yield
        finally:
            sweep.cancel()
            with suppress(asyncio.CancelledError):
                await sweep

    app = FastAPI(
        title="Creative Workflow Gate A Server",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.include_router(health.router)
    app.include_router(workers.router)
    app.include_router(jobs.router)
    app.include_router(assets.router)
    app.include_router(tasks.router)

    # The operator console is a single-page app served same-origin, so its
    # fetch() calls to /api/v1/* need no CORS handling. Mounted after the API
    # routers so it can never shadow them.
    console_dir = Path(__file__).parent / "ui" / "app"

    @app.get("/", include_in_schema=False)
    def _console_root():
        return RedirectResponse(url="/app/")

    app.mount("/app", StaticFiles(directory=str(console_dir), html=True), name="console")

    @app.exception_handler(Exception)
    async def unhandled_exception(_request: Request, exc: Exception):
        # The API returns a consistent envelope so worker failures are visible
        # and machine-readable instead of being hidden behind HTML tracebacks.
        return JSONResponse(
            status_code=500,
            content=ErrorEnvelope(
                error=ApiError(code="internal_error", message=str(exc), details={})
            ).model_dump(),
        )

    return app


app = create_app()
