"""Worker job progress/completion/failure endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from creative_workflow.server.api.deps import bearer_token, get_settings, validate_worker_token
from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.session import get_db
from creative_workflow.server.services.job_queue import JobQueueService, QueueConflict
from creative_workflow.shared.contracts.api import AcceptedResponse
from creative_workflow.shared.contracts.jobs import (
    JobCompleteRequest,
    JobCompleteResponse,
    JobFailRequest,
    JobFailResponse,
    JobProgressRequest,
)

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.post("/{job_id}/progress", response_model=AcceptedResponse)
def progress(
    job_id: str,
    payload: JobProgressRequest,
    token: str = Depends(bearer_token),
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    validate_worker_token(payload.worker_id, token, db, settings)
    try:
        JobQueueService(db, settings).progress(job_id, payload)
    except QueueConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "conflict", "message": str(exc)}) from exc
    return AcceptedResponse()


@router.post("/{job_id}/complete", response_model=JobCompleteResponse)
def complete(
    job_id: str,
    payload: JobCompleteRequest,
    token: str = Depends(bearer_token),
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    validate_worker_token(payload.worker_id, token, db, settings)
    try:
        state = JobQueueService(db, settings).complete(job_id, payload)
    except (QueueConflict, ValueError) as exc:
        raise HTTPException(status_code=409, detail={"code": "conflict", "message": str(exc)}) from exc
    return JobCompleteResponse(server_workflow_state=state.value)


@router.post("/{job_id}/fail", response_model=JobFailResponse)
def fail(
    job_id: str,
    payload: JobFailRequest,
    token: str = Depends(bearer_token),
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    validate_worker_token(payload.worker_id, token, db, settings)
    try:
        state = JobQueueService(db, settings).fail(job_id, payload)
    except QueueConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "conflict", "message": str(exc)}) from exc
    return JobFailResponse(next_state=state.value)

