from creative_workflow.server.db.models import Asset
from creative_workflow.server.services.workflow import WorkflowService
from creative_workflow.shared.enums import AssetClass, RetentionClass, SourceService


def test_rejected_review_creates_new_retry_run_and_keeps_history(db_session, server_settings):
    workflow = WorkflowService(db_session, server_settings)
    task = workflow.create_task("Hero", "Make a hero image.", "static_image", "operator")
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
    db_session.commit()
    run, _jobs = workflow.start_gate_a(task.task_id, None)
    review = workflow.record_review(task.task_id, run.run_id, "rejected", None, "Make it brighter.")

    retry_run, retry_jobs = workflow.retry_after_rejection(task.task_id, run.run_id, review.review_id, "Make it brighter.")

    assert retry_run.attempt_number == 2
    assert retry_run.source_review_id == review.review_id
    assert retry_jobs[0].inputs_json["operator_note"] == "Make it brighter."

