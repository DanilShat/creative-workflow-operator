"""Conversation orchestrator — the chat layer's brain.

Phase 2 is deterministic:

* An explicit action (approve / reject / retry) is forwarded to the existing
  WorkflowService — same review and retry semantics as the old buttons.
* A message with image attachments is treated as a Gate A request: store
  the images as references, create the task, start the run.
* Plain text gets a placeholder agent reply; the local LLM lands in phase 3.

Every user turn writes a row in `messages`, every agent reply does too, so
the chat history is the source of truth for the UI.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.models import (
    Asset,
    Conversation,
    Message,
    Review,
    Run,
    Task,
    WorkflowEvent,
)
from creative_workflow.server.services.artifacts import ArtifactService, sha256_bytes
from creative_workflow.server.services.local_llm import LocalLLMService
from creative_workflow.server.services.workflow import WorkflowService
from creative_workflow.shared.contracts.assets import ReferenceUploadMetadata
from creative_workflow.shared.contracts.conversations import (
    ConversationDetailResponse,
    ConversationSummary,
    MessageItem,
)
from creative_workflow.shared.enums import AssetClass, SourceService
from creative_workflow.shared.ids import new_id
from creative_workflow.shared.time import utc_now


class OrchestratorError(Exception):
    """Raised when the orchestrator cannot process the request."""


_VARIANT_RE = re.compile(
    r"\b(?:make\s+)?(\d{1,2})\s*(?:variants?|versions?|options?|images?)\b",
    re.IGNORECASE,
)


def _parse_variant_count(text: str) -> int:
    """Heuristic: '3 variants' / 'make 4 options' / '2 images' → integer count."""
    match = _VARIANT_RE.search(text or "")
    if not match:
        return 1
    return max(1, min(20, int(match.group(1))))


def _derive_title_from_message(text: str) -> str:
    """Phase-2 title: first sentence or first 60 chars."""
    text = (text or "").strip()
    if not text:
        return "Untitled task"
    for end in ".!?\n":
        idx = text.find(end)
        if 5 < idx < 80:
            return text[:idx].strip()
    return text[:60].rstrip() + ("…" if len(text) > 60 else "")


def _infer_output_type(text: str) -> str:
    return "video" if "video" in (text or "").lower() else "static_image"


class ConversationOrchestrator:
    def __init__(
        self,
        db: Session,
        settings: ServerSettings,
        *,
        llm: LocalLLMService | None = None,
    ):
        self.db = db
        self.settings = settings
        self.workflow = WorkflowService(db, settings)
        self.artifacts = ArtifactService(db, settings)
        # Injectable so tests can swap a fake brain. In production each
        # request gets its own short-lived LocalLLMService — Ollama is
        # localhost-bound and cheap to construct.
        self.llm = llm if llm is not None else LocalLLMService(settings)

    # ---------- conversation CRUD ----------

    def create(self, title: str | None = None) -> Conversation:
        clean = (title or "").strip()[:255] or "Untitled"
        conv = Conversation(conversation_id=new_id("conv"), title=clean)
        self.db.add(conv)
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def list(self, include_hidden: bool = False) -> list[ConversationSummary]:
        q = select(Conversation)
        if not include_hidden:
            q = q.where(Conversation.hidden_at.is_(None))
        q = q.order_by(desc(Conversation.updated_at))
        return [self.summary(c) for c in self.db.scalars(q).all()]

    def get(self, conversation_id: str) -> ConversationDetailResponse:
        conv = self._require(conversation_id)
        msgs = self.db.scalars(
            select(Message)
            .where(Message.conversation_id == conv.conversation_id)
            .order_by(Message.created_at)
        ).all()
        return ConversationDetailResponse(
            conversation=self.summary(conv),
            messages=[self.message_item(m) for m in msgs],
            gallery=self._gallery(conv.conversation_id),
            tasks=self._tasks(conv.conversation_id),
        )

    def hide(self, conversation_id: str) -> None:
        conv = self._require(conversation_id)
        conv.hidden_at = utc_now()
        self.db.commit()

    def restore(self, conversation_id: str) -> None:
        conv = self._require(conversation_id)
        conv.hidden_at = None
        self.db.commit()

    def rename(self, conversation_id: str, title: str) -> Conversation:
        conv = self._require(conversation_id)
        conv.title = title.strip()[:255]
        self.db.commit()
        self.db.refresh(conv)
        return conv

    # ---------- the routing entry point ----------

    def post_message(
        self,
        conversation_id: str,
        text: str,
        action: dict[str, Any] | None,
        attachments: list[tuple[bytes, str, str]],
    ) -> tuple[Message, Message | None]:
        """Route a single user turn. Returns (user_message, agent_message).

        attachments is a list of (raw_bytes, original_filename, content_type).
        """

        conv = self._require(conversation_id, allow_hidden=False)
        if not (text or attachments or action):
            raise OrchestratorError("nothing to do — send text, an attachment, or an action")

        # Remember whether this is the conversation's very first user message,
        # so we can ask the local LLM for an auto-title after the turn lands.
        is_first_turn = (
            self.db.scalar(
                select(func.count(Message.message_id)).where(
                    Message.conversation_id == conv.conversation_id
                )
            )
            or 0
        ) == 0

        user_msg = Message(
            message_id=new_id("msg"),
            conversation_id=conv.conversation_id,
            role="user",
            content=text or "",
            attachments_json=[],
        )
        self.db.add(user_msg)

        try:
            if action is not None:
                agent_msg = self._handle_action(conv, action, user_msg)
            elif attachments:
                agent_msg = self._handle_gate_a(conv, user_msg, text or "", attachments)
            else:
                agent_msg = self._handle_text_intent(conv, user_msg, text or "")
        except OrchestratorError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface as a chat error, never lose the turn
            agent_msg = self._agent(conv, f"Something went wrong: {exc}")

        if is_first_turn and (text or "").strip() and conv.title.strip().lower() == "untitled":
            new_title = self.llm.auto_title(text or "")
            if not new_title:
                # Heuristic fallback so the sidebar never reads "Untitled"
                # after the designer has clearly described something.
                new_title = " ".join((text or "").split()[:5])[:60]
            if new_title:
                conv.title = new_title[:80]

        conv.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(user_msg)
        if agent_msg is not None:
            self.db.refresh(agent_msg)
        return user_msg, agent_msg

    # ---------- handlers ----------

    def _handle_action(
        self, conv: Conversation, action: dict[str, Any], user_msg: Message
    ) -> Message:
        kind = action.get("type")
        run_id = action.get("run_id")
        task = self._task_for_run(conv, run_id)
        user_msg.related_task_id = task.task_id
        user_msg.related_run_id = run_id

        if kind == "approve":
            self.workflow.record_review(
                task.task_id, run_id, "approved", action.get("selected_asset_id"), None
            )
            return self._agent(
                conv, "Approved.", related_task_id=task.task_id, related_run_id=run_id
            )

        if kind == "reject":
            reason = (action.get("reason") or "").strip()
            if not reason:
                raise OrchestratorError("reject needs a reason")
            self.workflow.record_review(task.task_id, run_id, "rejected", None, reason)
            return self._agent(
                conv,
                "Got it — rejected. Send a retry message when you want me to try again.",
                related_task_id=task.task_id,
                related_run_id=run_id,
            )

        if kind == "retry":
            review_id = action.get("review_id")
            instruction = (action.get("instruction") or "").strip()
            if not review_id or not instruction:
                raise OrchestratorError("retry needs review_id and instruction")
            run, _ = self.workflow.retry_after_rejection(
                task.task_id, run_id, review_id, instruction
            )
            return self._agent(
                conv,
                "Running another attempt.",
                related_task_id=task.task_id,
                related_run_id=run.run_id,
            )

        raise OrchestratorError(f"unknown action type: {kind!r}")

    def _handle_gate_a(
        self,
        conv: Conversation,
        user_msg: Message,
        text: str,
        attachments: list[tuple[bytes, str, str]],
    ) -> Message:
        # Default to the phase-2 heuristic. If the LLM is up and confidently
        # classifies this as a Gate A request, use its richer extraction.
        title = _derive_title_from_message(text)
        brief = text.strip() or "(image-only brief)"
        output_type = _infer_output_type(text)
        if text.strip():
            intent = self.llm.classify_chat_intent(
                text, context_line="image attached — likely Gate A"
            )
            if intent is not None and intent.type == "gate_a":
                if intent.title and intent.title.strip():
                    title = intent.title.strip()[:80]
                if intent.brief and intent.brief.strip():
                    brief = intent.brief.strip()
                if intent.output_type:
                    output_type = intent.output_type
        variant_count = _parse_variant_count(text)

        task = self.workflow.create_task(
            title=title,
            brief_text=brief,
            requested_output_type=output_type,
            created_by="chat",
            conversation_id=conv.conversation_id,
        )

        asset_ids: list[str] = []
        for data, filename, content_type in attachments:
            meta = ReferenceUploadMetadata(
                original_filename=filename or "reference",
                content_type=content_type or "application/octet-stream",
                size_bytes=len(data),
                sha256=sha256_bytes(data),
                source_service=SourceService.MANUAL,
            )
            asset = self.artifacts.store_reference(task.task_id, meta, data)
            asset_ids.append(asset.asset_id)
        user_msg.attachments_json = asset_ids

        run, _ = self.workflow.start_gate_a(
            task.task_id, operator_note=None, variant_count=variant_count
        )
        user_msg.related_task_id = task.task_id
        user_msg.related_run_id = run.run_id

        reply = (
            f"Got it — starting Gate A "
            f"({variant_count} variant{'s' if variant_count != 1 else ''}). "
            "I'll come back when the image is ready to review."
        )
        return self._agent(
            conv, reply, related_task_id=task.task_id, related_run_id=run.run_id
        )

    def _handle_text_intent(
        self, conv: Conversation, user_msg: Message, text: str
    ) -> Message:
        """Classify the turn via the local LLM and route accordingly.

        Falls back to a friendly deterministic reply when Ollama is down so
        the chat never stalls on a dead model.
        """

        context_line = self._context_line(conv)
        intent = self.llm.classify_chat_intent(text, context_line)
        if intent is None:
            # Best-effort: classification failed (Ollama down, or the small
            # model returned unparseable JSON). Try chat_text, which has its
            # own graceful fallback when Ollama itself is unreachable.
            reply = self.llm.chat_text(text)
            return self._agent(conv, reply)

        if intent.type == "approve_last":
            return self._handle_implicit_approve(conv, user_msg)
        if intent.type == "reject_last":
            return self._handle_implicit_reject(conv, user_msg, text)
        if intent.type == "retry_last":
            return self._handle_implicit_retry(conv, user_msg, text)
        if intent.type == "gate_a":
            return self._agent(
                conv,
                "Gate A needs at least one reference image. "
                "Drop one in and I'll start the run.",
            )

        reply = self.llm.chat_text(text)
        return self._agent(conv, reply)

    # ----- implicit action handlers (driven by LLM intent on plain text) -----

    def _handle_implicit_approve(
        self, conv: Conversation, user_msg: Message
    ) -> Message:
        pair = self._last_actionable_run(conv)
        if pair is None or pair[0].workflow_state != "waiting_human_review":
            return self._agent(conv, "There's nothing waiting for review.")
        task, run = pair
        latest_asset = self.db.scalars(
            select(Asset)
            .where(
                Asset.run_id == run.run_id,
                Asset.asset_class == AssetClass.GENERATED.value,
            )
            .order_by(desc(Asset.created_at))
            .limit(1)
        ).first()
        self.workflow.record_review(
            task.task_id,
            run.run_id,
            "approved",
            latest_asset.asset_id if latest_asset else None,
            None,
        )
        user_msg.related_task_id = task.task_id
        user_msg.related_run_id = run.run_id
        return self._agent(
            conv,
            "Approved.",
            related_task_id=task.task_id,
            related_run_id=run.run_id,
        )

    def _handle_implicit_reject(
        self, conv: Conversation, user_msg: Message, text: str
    ) -> Message:
        pair = self._last_actionable_run(conv)
        if pair is None or pair[0].workflow_state != "waiting_human_review":
            return self._agent(conv, "There's nothing waiting for review.")
        task, run = pair
        reason = text.strip() or "rejected"
        self.workflow.record_review(task.task_id, run.run_id, "rejected", None, reason)
        user_msg.related_task_id = task.task_id
        user_msg.related_run_id = run.run_id
        return self._agent(
            conv,
            "Got it — rejected. Tell me what to change and I'll retry.",
            related_task_id=task.task_id,
            related_run_id=run.run_id,
        )

    def _handle_implicit_retry(
        self, conv: Conversation, user_msg: Message, text: str
    ) -> Message:
        pair = self._last_actionable_run(conv)
        if pair is None:
            return self._agent(conv, "There's no prior result to retry.")
        task, run = pair
        review = self.db.scalars(
            select(Review)
            .where(Review.task_id == task.task_id, Review.decision == "rejected")
            .order_by(desc(Review.created_at))
            .limit(1)
        ).first()
        if review is None:
            # No prior rejection on this task: treat as conversation, not action.
            reply = self.llm.chat_text(text)
            return self._agent(conv, reply)
        new_run, _ = self.workflow.retry_after_rejection(
            task.task_id, review.run_id, review.review_id, text.strip() or "retry"
        )
        user_msg.related_task_id = task.task_id
        user_msg.related_run_id = new_run.run_id
        return self._agent(
            conv,
            "Running another attempt.",
            related_task_id=task.task_id,
            related_run_id=new_run.run_id,
        )

    # ----- conversation context helpers -----

    def _context_line(self, conv: Conversation) -> str:
        latest = self.db.scalars(
            select(Task)
            .where(Task.conversation_id == conv.conversation_id)
            .order_by(desc(Task.created_at))
            .limit(1)
        ).first()
        if latest is None:
            return "no prior result in this conversation"
        state = latest.workflow_state
        if state == "waiting_human_review":
            return "a result is waiting for the user's review"
        if state == "human_rejected":
            return "the previous result was rejected"
        if state == "human_approved":
            return "the previous result was approved"
        if state == "failed":
            return "the previous attempt failed"
        if state in ("waiting_worker", "running_worker_job", "retry_requested"):
            return "a result is currently being generated"
        return f"state: {state}"

    def _last_actionable_run(
        self, conv: Conversation
    ) -> tuple[Task, Run] | None:
        task = self.db.scalars(
            select(Task)
            .where(Task.conversation_id == conv.conversation_id)
            .order_by(desc(Task.created_at))
            .limit(1)
        ).first()
        if task is None:
            return None
        run = self.db.scalars(
            select(Run)
            .where(Run.task_id == task.task_id)
            .order_by(desc(Run.attempt_number))
            .limit(1)
        ).first()
        if run is None:
            return None
        return task, run

    # ---------- view-model helpers ----------

    def summary(self, conv: Conversation) -> ConversationSummary:
        last_msg = self.db.scalars(
            select(Message)
            .where(Message.conversation_id == conv.conversation_id)
            .order_by(desc(Message.created_at))
            .limit(1)
        ).first()
        msg_count = (
            self.db.scalar(
                select(func.count(Message.message_id)).where(
                    Message.conversation_id == conv.conversation_id
                )
            )
            or 0
        )
        gallery = self._gallery(conv.conversation_id, limit=1)
        gallery_count = (
            self.db.scalar(
                select(func.count(Asset.asset_id))
                .join(Task, Task.task_id == Asset.task_id)
                .where(
                    Task.conversation_id == conv.conversation_id,
                    Asset.asset_class == AssetClass.GENERATED.value,
                )
            )
            or 0
        )
        return ConversationSummary(
            conversation_id=conv.conversation_id,
            title=conv.title,
            created_at=conv.created_at.isoformat(),
            updated_at=(conv.updated_at or conv.created_at).isoformat(),
            hidden_at=conv.hidden_at.isoformat() if conv.hidden_at else None,
            message_count=msg_count,
            last_message_preview=(last_msg.content[:140] if last_msg else None),
            last_message_at=(last_msg.created_at.isoformat() if last_msg else None),
            gallery_count=gallery_count,
            thumbnail_asset_id=(gallery[0]["asset_id"] if gallery else None),
        )

    def message_item(self, m: Message) -> MessageItem:
        return MessageItem(
            message_id=m.message_id,
            role=m.role,
            content=m.content,
            attachments=list(m.attachments_json or []),
            related_task_id=m.related_task_id,
            related_run_id=m.related_run_id,
            created_at=m.created_at.isoformat(),
        )

    # ---------- internals ----------

    def _agent(self, conv: Conversation, content: str, **kwargs: Any) -> Message:
        msg = Message(
            message_id=new_id("msg"),
            conversation_id=conv.conversation_id,
            role="agent",
            content=content,
            **kwargs,
        )
        self.db.add(msg)
        return msg

    def _require(self, conversation_id: str, allow_hidden: bool = True) -> Conversation:
        conv = self.db.get(Conversation, conversation_id)
        if conv is None:
            raise OrchestratorError("conversation not found")
        if not allow_hidden and conv.hidden_at is not None:
            raise OrchestratorError("conversation is hidden — restore it first")
        return conv

    def _task_for_run(self, conv: Conversation, run_id: str | None) -> Task:
        if not run_id:
            raise OrchestratorError("run_id required")
        run = self.db.get(Run, run_id)
        if run is None:
            raise OrchestratorError("run not found")
        task = self.db.get(Task, run.task_id)
        if task is None or task.conversation_id != conv.conversation_id:
            raise OrchestratorError("run does not belong to this conversation")
        return task

    def _gallery(self, conversation_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        q = (
            select(Asset)
            .join(Task, Task.task_id == Asset.task_id)
            .where(
                Task.conversation_id == conversation_id,
                Asset.asset_class == AssetClass.GENERATED.value,
            )
            .order_by(desc(Asset.created_at))
        )
        if limit:
            q = q.limit(limit)
        return [
            {
                "asset_id": a.asset_id,
                "task_id": a.task_id,
                "run_id": a.run_id,
                "content_type": a.content_type,
                "created_at": a.created_at.isoformat(),
            }
            for a in self.db.scalars(q).all()
        ]

    def _tasks(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = self.db.scalars(
            select(Task)
            .where(Task.conversation_id == conversation_id)
            .order_by(desc(Task.created_at))
        ).all()
        result: list[dict[str, Any]] = []
        for t in rows:
            # Surface the most recent worker job_progress event per task so
            # the chat bubble can show what the worker is doing right now,
            # not just the coarse workflow_state.
            latest_progress_event = self.db.scalars(
                select(WorkflowEvent)
                .where(
                    WorkflowEvent.task_id == t.task_id,
                    WorkflowEvent.event_type == "job_progress",
                )
                .order_by(desc(WorkflowEvent.created_at))
                .limit(1)
            ).first()
            latest_progress: dict[str, Any] | None = None
            if latest_progress_event is not None:
                payload = latest_progress_event.payload_json or {}
                latest_progress = {
                    "step": payload.get("step"),
                    "message": payload.get("message"),
                    "state": payload.get("state"),
                    "at": latest_progress_event.created_at.isoformat(),
                    "job_id": latest_progress_event.job_id,
                }
            result.append(
                {
                    "task_id": t.task_id,
                    "workflow_state": t.workflow_state,
                    "title": t.title,
                    "requested_output_type": t.requested_output_type,
                    "created_at": t.created_at.isoformat(),
                    "latest_progress": latest_progress,
                }
            )
        return result
