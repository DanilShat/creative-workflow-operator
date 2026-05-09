"""FastAPI server application factory.

The API is the stable boundary for the worker protocol, task state, artifact
handling, and orchestration services. Streamlit talks to these server services;
the worker never talks to Streamlit.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from creative_workflow.server.api import assets, health, jobs, tasks, workers
from creative_workflow.server.config import ServerSettings
from creative_workflow.shared.contracts.api import ApiError, ErrorEnvelope


def create_app(settings: ServerSettings | None = None) -> FastAPI:
    app = FastAPI(title="Creative Workflow Gate A Server", version="0.1.0")
    app.state.settings = settings or ServerSettings.load()
    app.include_router(health.router)
    app.include_router(workers.router)
    app.include_router(jobs.router)
    app.include_router(assets.router)
    app.include_router(tasks.router)

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

