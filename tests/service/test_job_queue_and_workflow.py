import pytest
from datetime import timedelta
from sqlalchemy import select

from creative_workflow.server.db.models import Asset, Job, Worker
from creative_workflow.server.services.job_queue import JobQueueService, QueueConflict
from creative_workflow.server.services.workflow import WorkflowService
from creative_workflow.shared.contracts.jobs import JobCompleteRequest, JobFailRequest
from creative_workflow.shared.enums import AssetClass, FailureType, JobState, RetentionClass, SourceService, WorkflowState
from creative_workflow.shared.time import iso_now
from creative_workflow.shared.time import utc_now


def test_gate_a_creates_gemini_then_freepik_then_human_review(db_session, server_settings):
    workflow = WorkflowService(db_session, server_settings)
    task = workflow.create_task("Hero", "Create a square hero image.", "static_image", "operator")
    db_session.add(
        Asset(
            asset_id="asset_ref_1",
            task_id=task.task_id,
            asset_class=AssetClass.REFERENCE.value,
            retention_class=RetentionClass.KEEP.value,
            original_filename="ref.png",
            stored_filename="asset_ref_1.png",
            relative_path="tasks/task_1/reference/asset_ref_1.png",
            content_type="image/png",
            size_bytes=1,
            sha256="a" * 64,
            source_service=SourceService.MANUAL.value,
        )
    )
    db_session.add(Worker(worker_id="designer-laptop-01", capabilities=["browser.gemini", "browser.freepik"], status="idle"))
    db_session.commit()

    run, jobs = workflow.start_gate_a(task.task_id, "Use the reference.")
    assert jobs[0].required_capability == "browser.gemini"

    queue = JobQueueService(db_session, server_settings)
    gemini = queue.claim_next("designer-laptop-01", ["browser.gemini", "browser.freepik"], None)
    assert gemini is not None
    state = queue.complete(
        gemini.job_id,
        JobCompleteRequest(
            worker_id="designer-laptop-01",
            outputs={
                "flow_result": {
                    "structured_output": {
                        "prompt_text": "A polished product hero image on a clean studio background.",
                        "prompt_language": "en",
                    }
                }
            },
            artifact_ids=[],
            completed_at=iso_now(),
        ),
    )
    assert state == WorkflowState.WAITING_WORKER

    freepik = queue.claim_next("designer-laptop-01", ["browser.freepik"], None)
    assert freepik is not None
    assert freepik.action_name == "freepik_generate_image_from_prompt"
    db_session.add(
        Asset(
            asset_id="asset_generated_1",
            task_id=task.task_id,
            run_id=run.run_id,
            job_id=freepik.job_id,
            asset_class=AssetClass.GENERATED.value,
            retention_class=RetentionClass.TTL_30D.value,
            original_filename="generated.png",
            stored_filename="asset_generated_1.png",
            relative_path=f"tasks/{task.task_id}/generated/asset_generated_1.png",
            content_type="image/png",
            size_bytes=10,
            sha256="b" * 64,
            source_service=SourceService.FREEPIK.value,
        )
    )
    db_session.commit()
    state = queue.complete(
        freepik.job_id,
        JobCompleteRequest(
            worker_id="designer-laptop-01",
            outputs={"flow_result": {"structured_output": {"generated_asset_ids": ["asset_generated_1"]}}},
            artifact_ids=["asset_generated_1"],
            completed_at=iso_now(),
        ),
    )
    assert state == WorkflowState.WAITING_HUMAN_REVIEW
    assert db_session.get(Worker, "designer-laptop-01").active_job_id is None


def test_complete_rejects_missing_artifact_ids(db_session, server_settings):
    workflow = WorkflowService(db_session, server_settings)
    task = workflow.create_task("Hero", "Create a square hero image.", "static_image", "operator")
    db_session.add(
        Asset(
            asset_id="asset_ref_1",
            task_id=task.task_id,
            asset_class=AssetClass.REFERENCE.value,
            retention_class=RetentionClass.KEEP.value,
            original_filename="ref.png",
            stored_filename="asset_ref_1.png",
            relative_path="tasks/task_1/reference/asset_ref_1.png",
            content_type="image/png",
            size_bytes=1,
            sha256="a" * 64,
            source_service=SourceService.MANUAL.value,
        )
    )
    db_session.add(Worker(worker_id="designer-laptop-01", capabilities=["browser.gemini"], status="idle"))
    db_session.commit()
    workflow.start_gate_a(task.task_id, None)
    queue = JobQueueService(db_session, server_settings)
    gemini = queue.claim_next("designer-laptop-01", ["browser.gemini"], None)

    with pytest.raises(QueueConflict, match="missing artifact"):
        queue.complete(
            gemini.job_id,
            JobCompleteRequest(
                worker_id="designer-laptop-01",
                outputs={
                    "flow_result": {
                        "structured_output": {
                            "prompt_text": "A polished product hero image.",
                            "prompt_language": "en",
                        }
                    }
                },
                artifact_ids=["asset_not_uploaded"],
                completed_at=iso_now(),
            ),
        )


def test_claim_next_respects_capabilities_and_single_active_job(db_session, server_settings):
    workflow = WorkflowService(db_session, server_settings)
    task = workflow.create_task("Hero", "Brief", "static_image", "operator")
    db_session.add(
        Asset(
            asset_id="asset_ref_1",
            task_id=task.task_id,
            asset_class=AssetClass.REFERENCE.value,
            retention_class=RetentionClass.KEEP.value,
            original_filename="ref.png",
            stored_filename="ref.png",
            relative_path="tasks/task_1/reference/ref.png",
            content_type="image/png",
            size_bytes=1,
            sha256="a" * 64,
            source_service=SourceService.MANUAL.value,
        )
    )
    db_session.add(Worker(worker_id="designer-laptop-01", capabilities=["browser.gemini"], status="idle"))
    db_session.commit()
    workflow.start_gate_a(task.task_id, None)

    queue = JobQueueService(db_session, server_settings)
    assert queue.claim_next("designer-laptop-01", ["browser.freepik"], None) is None
    claimed = queue.claim_next("designer-laptop-01", ["browser.gemini"], None)
    assert claimed is not None
    assert db_session.get(Worker, "designer-laptop-01").active_job_id == claimed.job_id
    assert queue.claim_next("designer-laptop-01", ["browser.gemini"], claimed.job_id) is None


def test_retryable_failure_enqueues_next_attempt_until_policy_limit(db_session, server_settings):
    workflow = WorkflowService(db_session, server_settings)
    task = workflow.create_task("Hero", "Brief", "static_image", "operator")
    db_session.add(
        Asset(
            asset_id="asset_ref_1",
            task_id=task.task_id,
            asset_class=AssetClass.REFERENCE.value,
            retention_class=RetentionClass.KEEP.value,
            original_filename="ref.png",
            stored_filename="ref.png",
            relative_path="tasks/task_1/reference/ref.png",
            content_type="image/png",
            size_bytes=1,
            sha256="a" * 64,
            source_service=SourceService.MANUAL.value,
        )
    )
    db_session.add(Worker(worker_id="designer-laptop-01", capabilities=["browser.gemini"], status="idle"))
    db_session.commit()
    workflow.start_gate_a(task.task_id, None)
    queue = JobQueueService(db_session, server_settings)

    first = queue.claim_next("designer-laptop-01", ["browser.gemini"], None)
    first_state = queue.fail(
        first.job_id,
        JobFailRequest(
            worker_id="designer-laptop-01",
            failure_type=FailureType.NETWORK_TEMPORARY,
            retryable=True,
            message="temporary network failure",
            failed_at=iso_now(),
        ),
    )
    assert first_state == JobState.FAILED_RETRYABLE
    queued = db_session.scalars(
        select(Job).where(
            Job.action_name == "gemini_build_prompt_from_brief_and_refs",
            Job.state == JobState.QUEUED.value,
        )
    ).all()
    assert len(queued) == 1
    assert queued[0].attempt_number == 2

    second = queue.claim_next("designer-laptop-01", ["browser.gemini"], None)
    second_state = queue.fail(
        second.job_id,
        JobFailRequest(
            worker_id="designer-laptop-01",
            failure_type=FailureType.NETWORK_TEMPORARY,
            retryable=True,
            message="temporary network failure again",
            failed_at=iso_now(),
        ),
    )
    assert second_state == JobState.FAILED_FATAL
    remaining = db_session.scalars(select(Job).where(Job.state == JobState.QUEUED.value)).all()
    assert remaining == []


def test_expired_lease_marks_job_orphaned_and_worker_idle(db_session, server_settings):
    workflow = WorkflowService(db_session, server_settings)
    task = workflow.create_task("Hero", "Brief", "static_image", "operator")
    db_session.add(
        Asset(
            asset_id="asset_ref_1",
            task_id=task.task_id,
            asset_class=AssetClass.REFERENCE.value,
            retention_class=RetentionClass.KEEP.value,
            original_filename="ref.png",
            stored_filename="ref.png",
            relative_path="tasks/task_1/reference/ref.png",
            content_type="image/png",
            size_bytes=1,
            sha256="a" * 64,
            source_service=SourceService.MANUAL.value,
        )
    )
    db_session.add(Worker(worker_id="designer-laptop-01", capabilities=["browser.gemini"], status="idle"))
    db_session.commit()
    workflow.start_gate_a(task.task_id, None)
    queue = JobQueueService(db_session, server_settings)
    claimed = queue.claim_next("designer-laptop-01", ["browser.gemini"], None)
    job = db_session.get(Job, claimed.job_id)
    job.lease_expires_at = utc_now() - timedelta(seconds=1)
    db_session.commit()

    assert queue.mark_orphaned_expired_leases() == 1
    assert db_session.get(Job, claimed.job_id).state == JobState.ORPHANED.value
    worker = db_session.get(Worker, "designer-laptop-01")
    assert worker.active_job_id is None
    assert worker.status == "idle"
