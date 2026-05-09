"""Read-side helpers for Streamlit, API summaries, and MCP context."""

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from creative_workflow.server.db.models import Asset, Job, Prompt, Review, Run, Task, WorkflowEvent
from creative_workflow.shared.enums import AssetClass


def task_summary(db: Session, task: Task) -> dict:
    latest_run = db.scalars(select(Run).where(Run.task_id == task.task_id).order_by(desc(Run.attempt_number))).first()
    refs = db.scalars(
        select(Asset).where(Asset.task_id == task.task_id, Asset.asset_class == AssetClass.REFERENCE.value)
    ).all()
    generated = db.scalars(
        select(Asset).where(Asset.task_id == task.task_id, Asset.asset_class == AssetClass.GENERATED.value).order_by(desc(Asset.created_at))
    ).all()
    return {
        "task_id": task.task_id,
        "title": task.title,
        "brief_text": task.brief_text,
        "workflow_state": task.workflow_state,
        "latest_run_id": latest_run.run_id if latest_run else None,
        "reference_asset_ids": [asset.asset_id for asset in refs],
        "latest_generated_asset_ids": [asset.asset_id for asset in generated],
    }


def task_history(db: Session, task_id: str) -> dict:
    def rows(model):
        return [to_dict(row) for row in db.scalars(select(model).where(model.task_id == task_id)).all()]

    return {
        "task_id": task_id,
        "runs": rows(Run),
        "jobs": rows(Job),
        "prompts": rows(Prompt),
        "assets": rows(Asset),
        "reviews": rows(Review),
        "workflow_events": rows(WorkflowEvent),
    }


def to_dict(row) -> dict:
    data = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        data[column.name] = value.isoformat() if hasattr(value, "isoformat") else value
    return data

