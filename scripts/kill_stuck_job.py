"""Manually transition a stranded job → failed_fatal and narrate the chat.

Mirrors ``JobQueueService.fail()`` for the case where no worker is alive to
call the API (e.g. the worker process died after the orphan sweep took the
job, leaving the task stuck in ``waiting_worker`` and the chat silent).

Usage::

    python scripts/kill_stuck_job.py <job_id> [--message "..."]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Operator package lives under src/; PYTHONPATH may or may not be set when
# this script is invoked manually, so guarantee importability.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from creative_workflow.server.config import ServerSettings  # noqa: E402
from creative_workflow.server.db.session import make_session_factory  # noqa: E402
from creative_workflow.server.db.models import Job, Run, Task, Worker, WorkflowEvent  # noqa: E402
from creative_workflow.server.services.workflow import post_chat_progress  # noqa: E402
from creative_workflow.shared.enums import FailureType, JobState, WorkflowState  # noqa: E402
from creative_workflow.shared.ids import new_id  # noqa: E402
from creative_workflow.shared.time import utc_now  # noqa: E402


def kill(job_id: str, message: str) -> None:
    settings = ServerSettings.load()
    factory = make_session_factory(settings.database_url)
    db = factory()
    try:
        job = db.get(Job, job_id)
        if job is None:
            raise SystemExit(f"job not found: {job_id}")
        print(f"before  state={job.state} worker={job.claimed_by_worker_id} "
              f"lease_expires_at={job.lease_expires_at}")

        job.state = JobState.FAILED_FATAL.value
        job.failure_type = FailureType.FATAL_UNEXPECTED.value
        job.failure_message = message
        job.completed_at = utc_now()
        prior_worker_id = job.claimed_by_worker_id
        job.claimed_by_worker_id = None
        job.claimed_at = None
        job.lease_expires_at = None

        # Run + task move forward so the chat stops pretending we're working.
        run = db.get(Run, job.run_id)
        if run and run.status == "running":
            run.status = "failed"
            run.completed_at = utc_now()

        task = db.get(Task, job.task_id)
        if task:
            task.workflow_state = WorkflowState.FAILED.value

        if prior_worker_id:
            worker = db.get(Worker, prior_worker_id)
            if worker and worker.active_job_id == job.job_id:
                worker.active_job_id = None
                worker.status = "idle"

        db.add(
            WorkflowEvent(
                event_id=new_id("event"),
                task_id=job.task_id,
                run_id=job.run_id,
                job_id=job.job_id,
                event_type="job_failed",
                payload_json={
                    "source": "manual_kill",
                    "failure_type": FailureType.FATAL_UNEXPECTED.value,
                    "message": message,
                    "prior_worker_id": prior_worker_id,
                },
            )
        )

        if task:
            post_chat_progress(
                db,
                task,
                f"That run failed: {FailureType.FATAL_UNEXPECTED.value} — {message[:200]}"
                ". Tell me what to change and I'll try again.",
                run_id=job.run_id,
            )

        db.commit()
        print(f"after   state={job.state} worker={job.claimed_by_worker_id} "
              f"task.workflow_state={task.workflow_state if task else None}")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument(
        "--message",
        default=(
            "Worker process died after the operator orphan-sweep released the "
            "job; no worker fail() was ever posted, so the chat sat silent. "
            "Manually marked failed."
        ),
    )
    args = parser.parse_args()
    kill(args.job_id, args.message)
