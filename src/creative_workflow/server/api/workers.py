"""Worker protocol endpoints: register, heartbeat, and claim-next."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from creative_workflow.server.api.deps import bearer_token, get_settings, validate_worker_token
from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.models import Worker
from creative_workflow.server.db.session import get_db
from creative_workflow.server.services.job_queue import JobQueueService
from creative_workflow.shared.contracts.workers import (
    ClaimNextRequest,
    ClaimNextResponse,
    WorkerHeartbeatRequest,
    WorkerHeartbeatResponse,
    WorkerRegisterRequest,
    WorkerRegisterResponse,
)
from creative_workflow.shared.time import iso_now, utc_now

router = APIRouter(prefix="/api/v1/workers", tags=["workers"])


@router.post("/register", response_model=WorkerRegisterResponse)
def register_worker(
    payload: WorkerRegisterRequest,
    token: str = Depends(bearer_token),
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    validate_worker_token(payload.worker_id, token, db, settings)
    worker = db.get(Worker, payload.worker_id)
    if worker is None:
        worker = Worker(worker_id=payload.worker_id)
        db.add(worker)
    worker.display_name = payload.display_name
    worker.version = payload.version
    worker.capabilities = payload.capabilities
    worker.host_apps = payload.host_apps
    worker.profile_status = payload.profiles
    worker.machine_info = payload.machine_info
    worker.status = "idle"
    worker.last_heartbeat_at = utc_now()
    db.commit()
    return WorkerRegisterResponse(
        worker_id=payload.worker_id,
        registered=True,
        server_time=iso_now(),
        heartbeat_interval_s=settings.heartbeat_interval_s,
        claim_poll_interval_s=settings.claim_poll_interval_s,
        active_job=worker.active_job_id,
    )


@router.post("/heartbeat", response_model=WorkerHeartbeatResponse)
def heartbeat(
    payload: WorkerHeartbeatRequest,
    token: str = Depends(bearer_token),
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    validate_worker_token(payload.worker_id, token, db, settings)
    worker = db.get(Worker, payload.worker_id)
    if worker is None:
        worker = Worker(worker_id=payload.worker_id)
        db.add(worker)
    # Heartbeats report worker observations, but they do not own server state.
    # The server sets/clears active_job_id only through claim/complete/fail.
    worker.status = "running" if worker.active_job_id else payload.status.value
    worker.capabilities = payload.capabilities
    worker.profile_status = payload.profile_status
    worker.host_apps = payload.host_app_status
    worker.last_heartbeat_at = utc_now()
    lease = JobQueueService(db, settings).heartbeat_lease(payload.worker_id, payload.active_job_id)
    db.commit()
    return WorkerHeartbeatResponse(server_time=iso_now(), active_job_lease_expires_at=lease)


@router.post("/claim-next", response_model=ClaimNextResponse)
def claim_next(
    payload: ClaimNextRequest,
    token: str = Depends(bearer_token),
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    validate_worker_token(payload.worker_id, token, db, settings)
    job = JobQueueService(db, settings).claim_next(payload.worker_id, payload.capabilities, payload.active_job_id)
    return ClaimNextResponse(job=job, poll_after_s=settings.claim_poll_interval_s)
