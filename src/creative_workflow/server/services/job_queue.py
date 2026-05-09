"""Worker queue, lease, progress, and completion service.

The worker pulls compatible jobs. Heartbeats renew the active lease, and human
review never keeps a worker job leased.
"""

from datetime import UTC, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.models import Asset, Job, Task, Worker, WorkflowEvent
from creative_workflow.server.services.workflow import WorkflowService
from creative_workflow.shared.contracts.assets import JobInputAsset
from creative_workflow.shared.contracts.jobs import JobCompleteRequest, JobFailRequest, JobProgressRequest
from creative_workflow.shared.contracts.workers import JobForWorker
from creative_workflow.shared.enums import AssetClass, JobExecutionState, JobState, TERMINAL_JOB_STATES, WorkflowState
from creative_workflow.shared.ids import new_id
from creative_workflow.shared.time import utc_now


class QueueConflict(Exception):
    """Raised when a worker attempts an invalid job state transition."""


class JobQueueService:
    def __init__(self, db: Session, settings: ServerSettings):
        self.db = db
        self.settings = settings

    def claim_next(self, worker_id: str, capabilities: list[str], active_job_id: str | None) -> JobForWorker | None:
        worker = self.db.get(Worker, worker_id)
        if worker is None:
            raise QueueConflict("worker is not registered")
        if active_job_id or worker.active_job_id:
            return None
        job = self.db.scalars(
            select(Job)
            .where(Job.state == JobState.QUEUED.value, Job.required_capability.in_(capabilities))
            .order_by(Job.created_at)
        ).first()
        if job is None:
            return None
        now = utc_now()
        job.state = JobState.CLAIMED.value
        job.claimed_by_worker_id = worker_id
        job.claimed_at = now
        job.started_at = now
        job.lease_expires_at = now + timedelta(seconds=self.settings.active_job_lease_ttl_s)
        worker.active_job_id = job.job_id
        worker.status = "running"
        self._event(job, "job_claimed", {"worker_id": worker_id})
        self.db.commit()
        return self._job_for_worker(job)

    def heartbeat_lease(self, worker_id: str, active_job_id: str | None) -> str | None:
        worker = self.db.get(Worker, worker_id)
        if worker is None:
            return None
        worker.last_heartbeat_at = utc_now()
        if active_job_id:
            job = self.db.get(Job, active_job_id)
            if job and job.claimed_by_worker_id == worker_id and job.state not in {
                JobState.COMPLETED.value,
                JobState.FAILED_FATAL.value,
                JobState.FAILED_RETRYABLE.value,
                JobState.CANCELLED.value,
                JobState.ORPHANED.value,
            }:
                job.lease_expires_at = utc_now() + timedelta(seconds=self.settings.active_job_lease_ttl_s)
                return job.lease_expires_at.isoformat()
        return None

    def mark_orphaned_expired_leases(self) -> int:
        jobs = self.db.scalars(
            select(Job).where(
                Job.lease_expires_at.is_not(None),
                Job.state.in_([JobState.CLAIMED.value, JobState.RUNNING.value, JobState.UPLOADING_ARTIFACTS.value]),
            )
        ).all()
        jobs = [job for job in jobs if self._is_expired(job.lease_expires_at)]
        for job in jobs:
            job.state = JobState.ORPHANED.value
            self._event(job, "job_orphaned", {"lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None})
            worker = self.db.get(Worker, job.claimed_by_worker_id) if job.claimed_by_worker_id else None
            if worker and worker.active_job_id == job.job_id:
                worker.active_job_id = None
                worker.status = "idle"
        self.db.commit()
        return len(jobs)

    def progress(self, job_id: str, payload: JobProgressRequest) -> None:
        job = self._owned_job(job_id, payload.worker_id)
        if payload.state == JobExecutionState.UPLOADING_ARTIFACTS:
            job.state = JobState.UPLOADING_ARTIFACTS.value
        else:
            job.state = JobState.RUNNING.value
        self._event(job, "job_progress", payload.model_dump())
        self.db.commit()

    def complete(self, job_id: str, payload: JobCompleteRequest) -> WorkflowState:
        job = self._owned_job(job_id, payload.worker_id)
        self._validate_completion_artifacts(job, payload)
        job.state = JobState.COMPLETED.value
        job.completed_at = utc_now()
        worker = self.db.get(Worker, payload.worker_id)
        if worker:
            worker.active_job_id = None
            worker.status = "idle"
        workflow_state = WorkflowService(self.db, self.settings).handle_job_complete(job, payload.outputs, payload.artifact_ids)
        self._event(job, "job_completed", {"artifact_ids": payload.artifact_ids, "workflow_state": workflow_state.value})
        self.db.commit()
        return workflow_state

    def fail(self, job_id: str, payload: JobFailRequest) -> JobState:
        job = self._owned_job(job_id, payload.worker_id)
        retry_job = None
        if payload.retryable and self._has_retry_attempt_remaining(job):
            job.state = JobState.FAILED_RETRYABLE.value
            retry_job = self._enqueue_retry_attempt(job)
        else:
            job.state = JobState.FAILED_FATAL.value
        job.failure_type = payload.failure_type.value
        job.failure_message = payload.message
        job.completed_at = utc_now()
        worker = self.db.get(Worker, payload.worker_id)
        if worker:
            worker.active_job_id = None
            worker.status = "idle"
        event_payload = payload.model_dump(mode="json")
        if retry_job:
            event_payload["retry_job_id"] = retry_job.job_id
            task = self.db.get(Task, job.task_id)
            if task:
                task.workflow_state = WorkflowState.WAITING_WORKER.value
        else:
            task = self.db.get(Task, job.task_id)
            if task:
                task.workflow_state = WorkflowState.FAILED.value
        self._event(job, "job_failed", event_payload)
        self.db.commit()
        return JobState(job.state)

    def _owned_job(self, job_id: str, worker_id: str) -> Job:
        job = self.db.get(Job, job_id)
        if job is None:
            raise QueueConflict("job not found")
        if JobState(job.state) in TERMINAL_JOB_STATES:
            raise QueueConflict(f"job is already terminal: {job.state}")
        if job.claimed_by_worker_id != worker_id:
            raise QueueConflict("job is not owned by this worker")
        if job.lease_expires_at and self._is_expired(job.lease_expires_at):
            job.state = JobState.ORPHANED.value
            self.db.commit()
            raise QueueConflict("job lease expired")
        return job

    def _validate_completion_artifacts(self, job: Job, payload: JobCompleteRequest) -> None:
        """Ensure completion cannot reference files that were never uploaded.

        Browser workers upload generated/debug files before calling complete.
        This check makes that protocol durable: a job can no longer move to
        human review by merely naming an artifact id in the completion payload.
        """

        if not payload.artifact_ids:
            if job.action_name == "freepik_generate_image_from_prompt":
                raise QueueConflict("Freepik completion requires at least one uploaded artifact.")
            return
        assets = self.db.scalars(select(Asset).where(Asset.asset_id.in_(payload.artifact_ids))).all()
        found_ids = {asset.asset_id for asset in assets}
        missing = sorted(set(payload.artifact_ids) - found_ids)
        if missing:
            raise QueueConflict(f"completion references missing artifact ids: {', '.join(missing)}")
        wrong_job = [asset.asset_id for asset in assets if asset.job_id != job.job_id]
        if wrong_job:
            raise QueueConflict(f"completion references artifacts from another job: {', '.join(wrong_job)}")
        if job.action_name == "freepik_generate_image_from_prompt":
            generated = [asset for asset in assets if asset.asset_class == AssetClass.GENERATED.value]
            if not generated:
                raise QueueConflict("Freepik completion requires a generated artifact.")

    def _has_retry_attempt_remaining(self, job: Job) -> bool:
        max_attempts = int(job.retry_policy_json.get("max_attempts", 1))
        return job.attempt_number < max_attempts

    def _enqueue_retry_attempt(self, failed_job: Job) -> Job:
        retry = Job(
            job_id=new_id("job"),
            task_id=failed_job.task_id,
            run_id=failed_job.run_id,
            job_type=failed_job.job_type,
            required_capability=failed_job.required_capability,
            action_name=failed_job.action_name,
            inputs_json=dict(failed_job.inputs_json),
            state=JobState.QUEUED.value,
            attempt_number=failed_job.attempt_number + 1,
            retry_policy_json=dict(failed_job.retry_policy_json),
        )
        self.db.add(retry)
        self._event(
            failed_job,
            "job_retry_enqueued",
            {"retry_job_id": retry.job_id, "attempt_number": retry.attempt_number},
        )
        return retry

    def _is_expired(self, value) -> bool:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value < utc_now()

    def _job_for_worker(self, job: Job) -> JobForWorker:
        assets = self._input_assets(job)
        timeout_s = int(job.inputs_json.get("timeout_s", self.settings.default_browser_timeout_s))
        return JobForWorker(
            job_id=job.job_id,
            task_id=job.task_id,
            run_id=job.run_id,
            job_type=job.job_type,
            required_capability=job.required_capability,
            action_name=job.action_name,
            inputs=job.inputs_json,
            input_assets=assets,
            timeout_s=timeout_s,
            lease_ttl_s=self.settings.active_job_lease_ttl_s,
            lease_expires_at=job.lease_expires_at.isoformat(),
            idempotency_key=f"{job.job_id}_attempt_{job.attempt_number}",
        )

    def _input_assets(self, job: Job) -> list[JobInputAsset]:
        ids = job.inputs_json.get("reference_asset_ids") or job.inputs_json.get("refs") or []
        if not ids:
            return []
        assets = self.db.scalars(select(Asset).where(Asset.asset_id.in_(ids))).all()
        return [
            JobInputAsset(
                asset_id=asset.asset_id,
                download_url=f"/api/v1/assets/{asset.asset_id}/download",
                sha256=asset.sha256,
                content_type=asset.content_type,
                filename=asset.original_filename,
            )
            for asset in assets
        ]

    def _event(self, job: Job, event_type: str, payload: dict) -> None:
        self.db.add(
            WorkflowEvent(
                event_id=new_id("event"),
                task_id=job.task_id,
                run_id=job.run_id,
                job_id=job.job_id,
                event_type=event_type,
                payload_json=payload,
            )
        )
