"""FastAPI dependencies for DB sessions, settings, and worker auth."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.session import get_db
from creative_workflow.server.services.worker_auth import AuthError, WorkerAuthService


def get_settings(request: Request) -> ServerSettings:
    return request.app.state.settings


def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": "invalid_token", "message": "Missing bearer token."})
    return authorization.removeprefix("Bearer ").strip()


def validate_worker_token(worker_id: str, token: str, db: Session, settings: ServerSettings) -> None:
    try:
        WorkerAuthService(db, settings).validate(worker_id, token)
    except AuthError as exc:
        status = 403 if exc.code == "registration_disabled" else 401
        raise HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message}) from exc


def validate_any_worker_token(token: str, db: Session, settings: ServerSettings) -> str:
    try:
        return WorkerAuthService(db, settings).validate_any_active_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail={"code": exc.code, "message": exc.message}) from exc
