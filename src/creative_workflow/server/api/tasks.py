"""Task and human review API used by Streamlit and optional MCP tools."""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from creative_workflow.server.api.deps import get_settings
from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.models import Task
from creative_workflow.server.db.session import get_db
from creative_workflow.server.services.artifacts import ArtifactService
from creative_workflow.server.services.summaries import task_history, task_summary
from creative_workflow.server.services.workflow import WorkflowService
from creative_workflow.shared.contracts.assets import ReferenceUploadMetadata, ReferenceUploadResponse
from creative_workflow.shared.enums import AssetClass, RetentionClass
from creative_workflow.shared.contracts.tasks import (
    ReviewRequest,
    ReviewResponse,
    RetryRequest,
    RetryResponse,
    StartGateARequest,
    StartGateAResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskHistoryResponse,
    TaskSummaryResponse,
)
from creative_workflow.shared.time import utc_now

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.post("", response_model=TaskCreateResponse)
def create_task(
    payload: TaskCreateRequest,
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    task = WorkflowService(db, settings).create_task(
        payload.title, payload.brief_text, payload.requested_output_type, payload.created_by
    )
    return TaskCreateResponse(task_id=task.task_id, workflow_state=task.workflow_state, created_at=task.created_at.isoformat())


@router.post("/{task_id}/references", response_model=ReferenceUploadResponse)
async def upload_reference(
    task_id: str,
    file: UploadFile = File(...),
    metadata: str = Form(...),
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    if db.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    try:
        parsed = ReferenceUploadMetadata.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail={"code": "validation_error", "message": str(exc)}) from exc
    asset = ArtifactService(db, settings).store_reference(task_id, parsed, await file.read())
    return ReferenceUploadResponse(
        task_id=task_id,
        asset_id=asset.asset_id,
        asset_class=AssetClass(asset.asset_class),
        retention_class=RetentionClass(asset.retention_class),
        stored=True,
    )


@router.post("/{task_id}/start-gate-a", response_model=StartGateAResponse)
def start_gate_a(
    task_id: str,
    payload: StartGateARequest,
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    try:
        run, jobs = WorkflowService(db, settings).start_gate_a(task_id, payload.operator_note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "conflict", "message": str(exc)}) from exc
    return StartGateAResponse(
        task_id=task_id,
        run_id=run.run_id,
        workflow_state="waiting_worker",
        created_job_ids=[job.job_id for job in jobs],
    )


@router.get("/{task_id}", response_model=TaskSummaryResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    return TaskSummaryResponse.model_validate(task_summary(db, task))


@router.get("/{task_id}/history", response_model=TaskHistoryResponse)
def get_history(task_id: str, db: Session = Depends(get_db)):
    if db.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    return TaskHistoryResponse.model_validate(task_history(db, task_id))


@router.post("/{task_id}/reviews", response_model=ReviewResponse)
def review(
    task_id: str,
    payload: ReviewRequest,
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    try:
        review = WorkflowService(db, settings).record_review(
            task_id, payload.run_id, payload.decision, payload.selected_asset_id, payload.reason
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "conflict", "message": str(exc)}) from exc
    task = db.get(Task, task_id)
    return ReviewResponse(review_id=review.review_id, task_id=task_id, workflow_state=task.workflow_state)


@router.post("/{task_id}/retry", response_model=RetryResponse)
def retry(
    task_id: str,
    payload: RetryRequest,
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    try:
        run, jobs = WorkflowService(db, settings).retry_after_rejection(
            task_id, payload.source_run_id, payload.review_id, payload.repair_instruction
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": "conflict", "message": str(exc)}) from exc
    return RetryResponse(
        task_id=task_id,
        run_id=run.run_id,
        workflow_state="waiting_worker",
        created_job_ids=[job.job_id for job in jobs],
    )
