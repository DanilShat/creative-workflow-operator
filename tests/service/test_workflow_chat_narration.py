"""Phase 5: workflow service narrates pipeline transitions in chat threads.

Tasks bound to a conversation get an agent message on every state hop;
old-style tasks (conversation_id is NULL) keep working with zero new
messages so non-chat callers stay unaffected.
"""

from sqlalchemy import select

from creative_workflow.server.db.models import (
    Asset,
    Conversation,
    Job,
    Message,
    Prompt,
    Run,
    Task,
)
from creative_workflow.server.services.job_queue import JobQueueService
from creative_workflow.server.services.workflow import (
    FREEPIK_ACTION,
    GEMINI_ACTION,
    WorkflowService,
)
from creative_workflow.shared.contracts.jobs import JobFailRequest
from creative_workflow.shared.enums import (
    AssetClass,
    FailureType,
    JobState,
    JobType,
    RetentionClass,
    SourceService,
    WorkflowState,
)


def _seed_chat_task(db, *, conversation_id, action_name, run_id, job_id):
    """Create the minimal rows for a Gate A job belonging to a chat."""

    task = Task(
        task_id=f"task_{conversation_id}",
        conversation_id=conversation_id,
        title="t",
        brief_text="b",
        requested_output_type="static_image",
        workflow_state=WorkflowState.WAITING_WORKER.value,
        created_by="chat",
    )
    run = Run(run_id=run_id, task_id=task.task_id, attempt_number=1, status="running")
    job = Job(
        job_id=job_id,
        task_id=task.task_id,
        run_id=run_id,
        job_type=JobType.BROWSER_FLOW.value,
        required_capability="browser.gemini" if action_name == GEMINI_ACTION else "browser.freepik",
        action_name=action_name,
        inputs_json={"brief_text": "b"},
        state=JobState.CLAIMED.value,
        attempt_number=1,
        retry_policy_json={"max_attempts": 2},
    )
    db.add_all([task, run, job])
    db.flush()
    return task, run, job


def test_gemini_completion_posts_progress_message_when_task_has_conversation(
    db_session, server_settings
):
    conv = Conversation(conversation_id="conv_gem", title="g")
    db_session.add(conv)
    db_session.flush()
    task, run, job = _seed_chat_task(
        db_session,
        conversation_id="conv_gem",
        action_name=GEMINI_ACTION,
        run_id="run_gem",
        job_id="job_gem",
    )
    # Seed a reference asset so the new Freepik job creation finds one.
    db_session.add(
        Asset(
            asset_id="ref_gem",
            task_id=task.task_id,
            asset_class=AssetClass.REFERENCE.value,
            retention_class=RetentionClass.KEEP.value,
            original_filename="r.png",
            stored_filename="ref_gem.png",
            relative_path=f"tasks/{task.task_id}/reference/ref_gem.png",
            content_type="image/png",
            size_bytes=10,
            sha256="x" * 64,
            source_service=SourceService.MANUAL.value,
        )
    )
    db_session.commit()

    state = WorkflowService(db_session, server_settings).handle_job_complete(
        job,
        outputs={"structured_output": {"prompt_text": "a bright product"}},
        artifact_ids=[],
    )
    db_session.commit()

    assert state == WorkflowState.WAITING_WORKER
    messages = db_session.scalars(
        select(Message).where(Message.conversation_id == "conv_gem").order_by(Message.created_at)
    ).all()
    assert len(messages) == 1
    assert "generating the image" in messages[0].content.lower()
    assert messages[0].related_task_id == task.task_id
    assert messages[0].role == "agent"


def test_freepik_completion_posts_review_ready_message(db_session, server_settings):
    conv = Conversation(conversation_id="conv_fp", title="f")
    db_session.add(conv)
    db_session.flush()
    task, run, job = _seed_chat_task(
        db_session,
        conversation_id="conv_fp",
        action_name=FREEPIK_ACTION,
        run_id="run_fp",
        job_id="job_fp",
    )
    db_session.commit()

    state = WorkflowService(db_session, server_settings).handle_job_complete(
        job, outputs={}, artifact_ids=[]
    )
    db_session.commit()

    assert state == WorkflowState.WAITING_HUMAN_REVIEW
    messages = db_session.scalars(
        select(Message).where(Message.conversation_id == "conv_fp")
    ).all()
    assert len(messages) == 1
    assert "ready for your review" in messages[0].content.lower()


def test_non_chat_task_does_not_generate_messages(db_session, server_settings):
    """A task without a conversation_id must keep the old behavior."""

    # No conversation created; task.conversation_id = NULL
    task = Task(
        task_id="task_nochat",
        title="t",
        brief_text="b",
        requested_output_type="static_image",
        workflow_state=WorkflowState.WAITING_WORKER.value,
        created_by="operator",
    )
    run = Run(run_id="run_nochat", task_id=task.task_id, attempt_number=1, status="running")
    job = Job(
        job_id="job_nochat",
        task_id=task.task_id,
        run_id="run_nochat",
        job_type=JobType.BROWSER_FLOW.value,
        required_capability="browser.freepik",
        action_name=FREEPIK_ACTION,
        inputs_json={},
        state=JobState.CLAIMED.value,
        attempt_number=1,
        retry_policy_json={"max_attempts": 2},
    )
    db_session.add_all([task, run, job])
    db_session.commit()

    WorkflowService(db_session, server_settings).handle_job_complete(
        job, outputs={}, artifact_ids=[]
    )
    db_session.commit()

    assert db_session.scalars(select(Message)).all() == []


def test_fatal_job_failure_narrates_to_chat(db_session, server_settings):
    conv = Conversation(conversation_id="conv_fail", title="f")
    db_session.add(conv)
    db_session.flush()
    task, run, job = _seed_chat_task(
        db_session,
        conversation_id="conv_fail",
        action_name=FREEPIK_ACTION,
        run_id="run_fail",
        job_id="job_fail",
    )
    # The job_queue.fail path requires the job be claimed by the worker_id
    # in the payload and not lease-expired.
    from creative_workflow.server.db.models import Worker
    from creative_workflow.shared.time import utc_now
    from datetime import timedelta

    worker = db_session.get(Worker, "designer-laptop-01")
    if worker is None:
        worker = Worker(worker_id="designer-laptop-01")
        db_session.add(worker)
    job.claimed_by_worker_id = "designer-laptop-01"
    job.lease_expires_at = utc_now() + timedelta(seconds=60)
    # Exhaust retries so the failure is fatal.
    job.attempt_number = 2
    job.retry_policy_json = {"max_attempts": 2}
    db_session.commit()

    JobQueueService(db_session, server_settings).fail(
        job.job_id,
        JobFailRequest(
            worker_id="designer-laptop-01",
            failure_type=FailureType.FATAL_UNEXPECTED,
            retryable=False,
            message="something broke",
            debug_asset_ids=[],
            failed_at="2026-05-20T00:00:00+00:00",
        ),
    )

    messages = db_session.scalars(
        select(Message).where(Message.conversation_id == "conv_fail")
    ).all()
    assert len(messages) == 1
    assert "failed" in messages[0].content.lower()
    assert "something broke" in messages[0].content
