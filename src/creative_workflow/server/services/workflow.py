"""Gate A workflow service.

The service keeps server-side workflow transitions explicit: Gemini completion
creates the Freepik job, Freepik completion moves the task to human review, and
human rejection creates a fresh retry run instead of holding a worker lease.
"""

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.models import Asset, Job, Prompt, Review, Run, Task, WorkflowEvent
from creative_workflow.server.services.local_llm import LocalLLMService
from creative_workflow.shared.enums import AssetClass, JobState, JobType, RetentionClass, SourceService, WorkflowState
from creative_workflow.shared.ids import new_id
from creative_workflow.shared.time import utc_now


GEMINI_ACTION = "gemini_build_prompt_from_brief_and_refs"
FREEPIK_ACTION = "freepik_generate_image_from_prompt"
GEMINI_PHOTO_GEM_URL = "https://gemini.google.com/gem/5f69a5afc4b5"
GEMINI_VIDEO_GEM_URL = "https://gemini.google.com/gem/21d5be0eae0a"


class WorkflowService:
    def __init__(self, db: Session, settings: ServerSettings):
        self.db = db
        self.settings = settings
        self.llm = LocalLLMService(settings)

    def create_task(self, title: str, brief_text: str, requested_output_type: str, created_by: str) -> Task:
        task = Task(
            task_id=new_id("task"),
            title=title,
            brief_text=brief_text,
            requested_output_type=requested_output_type,
            workflow_state=WorkflowState.DRAFT.value,
            created_by=created_by,
        )
        self.db.add(task)
        self._event(task.task_id, None, None, "task_created", {"title": title})
        self.db.commit()
        self.db.refresh(task)
        return task

    def start_gate_a(self, task_id: str, operator_note: str | None) -> tuple[Run, list[Job]]:
        task = self._task(task_id)
        references = self._reference_assets(task_id)
        if not references:
            raise ValueError("Gate A requires at least one reference asset.")
        attempt = self._next_attempt(task_id)
        run = Run(run_id=new_id("run"), task_id=task_id, attempt_number=attempt, status="running")
        self.db.add(run)
        # Job rows have a database foreign key to runs. Flush the run before
        # constructing dependent jobs so PostgreSQL can enforce the contract
        # without relying on ORM relationship ordering.
        self.db.flush()
        normalized = self.llm.normalize_brief(task.brief_text)
        route = self.llm.route_for_gate_a(normalized)
        job = self._make_gemini_job(task, run, references, operator_note, route.reason)
        task.workflow_state = WorkflowState.WAITING_WORKER.value
        self._event(task_id, run.run_id, job.job_id, "gate_a_started", {
            "normalized_brief": normalized.model_dump(),
            "route": route.model_dump(),
        })
        self.db.commit()
        return run, [job]

    def handle_job_complete(self, job: Job, outputs: dict, artifact_ids: list[str]) -> WorkflowState:
        task = self._task(job.task_id)
        if job.action_name == GEMINI_ACTION:
            flow = outputs.get("flow_result", {})
            structured = flow.get("structured_output") or outputs.get("structured_output") or {}
            prompt_text = structured.get("prompt_text")
            if not prompt_text:
                raise ValueError("Gemini completion requires prompt_text.")
            prompt = Prompt(
                prompt_id=new_id("prompt"),
                task_id=job.task_id,
                run_id=job.run_id,
                job_id=job.job_id,
                prompt_role="generation",
                prompt_text=prompt_text,
                negative_prompt=structured.get("negative_prompt"),
                prompt_language=structured.get("prompt_language", "en"),
                source_service=SourceService.GEMINI.value,
                raw_response_asset_id=structured.get("raw_response_asset_id"),
            )
            self.db.add(prompt)
            refs = self._reference_assets(job.task_id)
            freepik_job = self._make_freepik_job(task, self.db.get(Run, job.run_id), refs, prompt_text)
            task.workflow_state = WorkflowState.WAITING_WORKER.value
            self._event(job.task_id, job.run_id, freepik_job.job_id, "freepik_job_created", {
                "source_prompt_id": prompt.prompt_id,
                "artifact_ids": artifact_ids,
            })
            return WorkflowState.WAITING_WORKER

        if job.action_name == FREEPIK_ACTION:
            task.workflow_state = WorkflowState.WAITING_HUMAN_REVIEW.value
            run = self.db.get(Run, job.run_id)
            if run:
                run.status = "waiting_human_review"
                run.completed_at = utc_now()
            self._event(job.task_id, job.run_id, job.job_id, "waiting_human_review", {"artifact_ids": artifact_ids})
            return WorkflowState.WAITING_HUMAN_REVIEW

        raise ValueError(f"Unsupported Gate A completion action {job.action_name}")

    def record_review(self, task_id: str, run_id: str, decision: str, selected_asset_id: str | None, reason: str | None) -> Review:
        task = self._task(task_id)
        review = Review(
            review_id=new_id("review"),
            task_id=task_id,
            run_id=run_id,
            decision=decision,
            selected_asset_id=selected_asset_id,
            reason=reason,
        )
        self.db.add(review)
        task.workflow_state = WorkflowState.HUMAN_APPROVED.value if decision == "approved" else WorkflowState.HUMAN_REJECTED.value
        self._event(task_id, run_id, None, f"human_{decision}", {"selected_asset_id": selected_asset_id, "reason": reason})
        self.db.commit()
        self.db.refresh(review)
        return review

    def retry_after_rejection(self, task_id: str, source_run_id: str, review_id: str, repair_instruction: str) -> tuple[Run, list[Job]]:
        task = self._task(task_id)
        review = self.db.get(Review, review_id)
        if review is None or review.decision != "rejected":
            raise ValueError("Retry requires a rejected review.")
        decision = self.llm.decide_retry(repair_instruction)
        attempt = self._next_attempt(task_id)
        run = Run(
            run_id=new_id("run"),
            task_id=task_id,
            attempt_number=attempt,
            status="running",
            source_review_id=review_id,
        )
        self.db.add(run)
        self.db.flush()
        refs = self._reference_assets(task_id)
        job = self._make_gemini_job(
            task,
            run,
            refs,
            operator_note=decision.repair_instruction or repair_instruction,
            route_reason=decision.reason,
        )
        task.workflow_state = WorkflowState.WAITING_WORKER.value
        self._event(task_id, run.run_id, job.job_id, "retry_requested", {
            "source_run_id": source_run_id,
            "review_id": review_id,
            "repair_instruction": repair_instruction,
        })
        self.db.commit()
        return run, [job]

    def _make_gemini_job(self, task: Task, run: Run, refs: list[Asset], operator_note: str | None, route_reason: str) -> Job:
        job = Job(
            job_id=new_id("job"),
            task_id=task.task_id,
            run_id=run.run_id,
            job_type=JobType.BROWSER_FLOW.value,
            required_capability="browser.gemini",
            action_name=GEMINI_ACTION,
            inputs_json={
                "brief_text": task.brief_text,
                "operator_note": operator_note,
                "requested_output_type": task.requested_output_type,
                "gemini_url": self._gemini_url_for_task(task),
                "reference_asset_ids": [asset.asset_id for asset in refs],
                "prompt_builder_instruction": "Create a production-ready Freepik image prompt from the brief and references.",
                "route_reason": route_reason,
            },
            state=JobState.QUEUED.value,
            attempt_number=run.attempt_number,
            retry_policy_json={"max_attempts": 2, "retryable_failure_types": ["network_temporary", "download_failed", "upload_failed"]},
        )
        # SQLAlchemy model keeps timeout in inputs/retry policy for this MVP schema.
        job.inputs_json["timeout_s"] = self.settings.default_browser_timeout_s
        self.db.add(job)
        return job

    def _make_freepik_job(self, task: Task, run: Run, refs: list[Asset], prompt_text: str) -> Job:
        job = Job(
            job_id=new_id("job"),
            task_id=task.task_id,
            run_id=run.run_id,
            job_type=JobType.BROWSER_FLOW.value,
            required_capability="browser.freepik",
            action_name=FREEPIK_ACTION,
            inputs_json={
                "prompt": prompt_text,
                "refs": [asset.asset_id for asset in refs],
                "settings": {"aspect_ratio": "1:1"},
                "timeout_s": self.settings.default_browser_timeout_s,
            },
            state=JobState.QUEUED.value,
            attempt_number=run.attempt_number,
            retry_policy_json={"max_attempts": 2, "retryable_failure_types": ["network_temporary", "upload_failed", "download_failed"]},
        )
        self.db.add(job)
        return job

    def _task(self, task_id: str) -> Task:
        task = self.db.get(Task, task_id)
        if task is None:
            raise ValueError("task not found")
        return task

    def _reference_assets(self, task_id: str) -> list[Asset]:
        return list(
            self.db.scalars(
                select(Asset).where(Asset.task_id == task_id, Asset.asset_class == AssetClass.REFERENCE.value)
            )
        )

    def _next_attempt(self, task_id: str) -> int:
        latest = self.db.scalars(
            select(Run).where(Run.task_id == task_id).order_by(desc(Run.attempt_number))
        ).first()
        return 1 if latest is None else latest.attempt_number + 1

    def _gemini_url_for_task(self, task: Task) -> str:
        return GEMINI_VIDEO_GEM_URL if "video" in task.requested_output_type.lower() else GEMINI_PHOTO_GEM_URL

    def _event(self, task_id: str, run_id: str | None, job_id: str | None, event_type: str, payload: dict) -> None:
        self.db.add(
            WorkflowEvent(
                event_id=new_id("event"),
                task_id=task_id,
                run_id=run_id,
                job_id=job_id,
                event_type=event_type,
                payload_json=payload,
            )
        )
