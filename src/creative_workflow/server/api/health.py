"""Health endpoints used by operator scripts and smoke tests."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from creative_workflow.server.api.deps import get_settings
from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.session import get_db

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db), settings: ServerSettings = Depends(get_settings)):
    db.execute(text("select 1"))
    return {
        "ok": True,
        "database": "reachable",
        "artifact_root": str(settings.artifact_root),
        "server_public_base_url": settings.server_public_base_url,
    }

