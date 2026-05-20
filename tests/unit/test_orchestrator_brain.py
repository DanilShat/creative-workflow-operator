"""Phase 3: orchestrator routing through the local-LLM brain.

These tests inject a deterministic fake brain so the LLM-driven paths are
exercised in isolation from a real Ollama. The end-to-end API tests in
test_conversations_api.py cover the surrounding HTTP layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from creative_workflow.server.db.models import Asset, Review, Run, Task
from creative_workflow.server.services.orchestrator import ConversationOrchestrator
from creative_workflow.shared.contracts.llm import ChatIntent


@dataclass
class FakeLLM:
    """Drop-in replacement for LocalLLMService used by the orchestrator tests."""

    title: str | None = None
    intent: ChatIntent | None = None
    chat_response: str = "mocked chat reply"
    calls: dict[str, int] = field(default_factory=lambda: {
        "auto_title": 0, "classify_chat_intent": 0, "chat_text": 0
    })

    def auto_title(self, message: str) -> str | None:
        self.calls["auto_title"] += 1
        return self.title

    def classify_chat_intent(self, message: str, context_line: str) -> ChatIntent | None:
        self.calls["classify_chat_intent"] += 1
        return self.intent

    def chat_text(self, message: str, context: dict | None = None) -> str:
        self.calls["chat_text"] += 1
        return self.chat_response


def _orch(db_session, server_settings, fake: FakeLLM) -> ConversationOrchestrator:
    return ConversationOrchestrator(db_session, server_settings, llm=fake)


# ---------- auto-title ----------


def test_auto_title_sets_on_first_user_message(db_session, server_settings):
    fake = FakeLLM(title="Spring hero kickoff", intent=ChatIntent(type="chat"))
    orch = _orch(db_session, server_settings, fake)
    conv = orch.create()

    orch.post_message(conv.conversation_id, "make me a hero image", None, [])

    db_session.refresh(conv)
    assert conv.title == "Spring hero kickoff"
    assert fake.calls["auto_title"] == 1


def test_auto_title_does_not_run_on_subsequent_messages(db_session, server_settings):
    fake = FakeLLM(title="First title", intent=ChatIntent(type="chat"))
    orch = _orch(db_session, server_settings, fake)
    conv = orch.create()

    orch.post_message(conv.conversation_id, "first", None, [])
    fake.title = "Second title (should NOT apply)"
    orch.post_message(conv.conversation_id, "second", None, [])

    db_session.refresh(conv)
    assert conv.title == "First title"
    assert fake.calls["auto_title"] == 1


def test_auto_title_skipped_when_conversation_was_renamed(db_session, server_settings):
    fake = FakeLLM(title="LLM suggested", intent=ChatIntent(type="chat"))
    orch = _orch(db_session, server_settings, fake)
    conv = orch.create("Designer named it")  # explicit non-default title

    orch.post_message(conv.conversation_id, "hello", None, [])

    db_session.refresh(conv)
    assert conv.title == "Designer named it"
    assert fake.calls["auto_title"] == 0


def test_auto_title_falls_back_to_first_words_when_llm_returns_none(
    db_session, server_settings
):
    """If the small local model can't produce a title, we still avoid 'Untitled'."""

    fake = FakeLLM(title=None, intent=ChatIntent(type="chat"))
    orch = _orch(db_session, server_settings, fake)
    conv = orch.create()
    orch.post_message(
        conv.conversation_id, "I want a Christmas card with snow", None, []
    )
    db_session.refresh(conv)
    assert conv.title == "I want a Christmas card"


# ---------- chat intent ----------


def test_chat_intent_routes_to_chat_text(db_session, server_settings):
    fake = FakeLLM(intent=ChatIntent(type="chat"), chat_response="Sure, I can help.")
    orch = _orch(db_session, server_settings, fake)
    conv = orch.create("c")

    _, agent_msg = orch.post_message(conv.conversation_id, "What can you do?", None, [])

    assert agent_msg is not None
    assert agent_msg.content == "Sure, I can help."
    assert fake.calls["classify_chat_intent"] == 1
    assert fake.calls["chat_text"] == 1


def test_intent_classify_failure_falls_through_to_chat_text(
    db_session, server_settings
):
    """When the classifier can't parse, we still try a plain chat reply.

    chat_text has its own fallback string when Ollama itself is unreachable,
    so the chat never stalls regardless of which layer fails.
    """

    fake = FakeLLM(intent=None, chat_response="Sure, I can help with that.")
    orch = _orch(db_session, server_settings, fake)
    conv = orch.create("c")

    _, agent_msg = orch.post_message(conv.conversation_id, "anything", None, [])

    assert agent_msg is not None
    assert agent_msg.content == "Sure, I can help with that."
    assert fake.calls["chat_text"] == 1


# ---------- implicit actions ----------


def _seed_task_waiting_review(db_session, conversation_id):
    db_session.add_all([
        Task(
            task_id="t_wait",
            conversation_id=conversation_id,
            title="x",
            brief_text="b",
            requested_output_type="static_image",
            workflow_state="waiting_human_review",
            created_by="chat",
        ),
        Run(run_id="r_wait", task_id="t_wait", attempt_number=1, status="waiting_human_review"),
        Asset(
            asset_id="a_wait",
            task_id="t_wait",
            run_id="r_wait",
            asset_class="generated",
            retention_class="ttl_30d",
            original_filename="hero.png",
            stored_filename="a_wait.png",
            relative_path="tasks/t_wait/generated/a_wait.png",
            content_type="image/png",
            size_bytes=10,
            sha256="x" * 64,
            source_service="freepik",
        ),
    ])
    db_session.commit()


def test_approve_last_intent_records_review_and_picks_latest_asset(
    db_session, server_settings
):
    fake = FakeLLM(intent=ChatIntent(type="approve_last"))
    orch = _orch(db_session, server_settings, fake)
    conv = orch.create("approve")
    _seed_task_waiting_review(db_session, conv.conversation_id)

    _, agent_msg = orch.post_message(conv.conversation_id, "love it, ship it", None, [])

    assert agent_msg is not None
    assert agent_msg.content.lower().startswith("approved")
    task = db_session.get(Task, "t_wait")
    assert task.workflow_state == "human_approved"


def test_reject_last_intent_records_rejection_with_user_text_as_reason(
    db_session, server_settings
):
    fake = FakeLLM(intent=ChatIntent(type="reject_last"))
    orch = _orch(db_session, server_settings, fake)
    conv = orch.create("reject")
    _seed_task_waiting_review(db_session, conv.conversation_id)

    _, agent_msg = orch.post_message(
        conv.conversation_id, "too dark — lighten it up", None, []
    )

    assert agent_msg is not None
    task = db_session.get(Task, "t_wait")
    assert task.workflow_state == "human_rejected"


def test_approve_last_with_nothing_to_review_explains_calmly(db_session, server_settings):
    fake = FakeLLM(intent=ChatIntent(type="approve_last"))
    orch = _orch(db_session, server_settings, fake)
    conv = orch.create("approve")

    _, agent_msg = orch.post_message(conv.conversation_id, "looks good", None, [])

    assert agent_msg is not None
    assert "nothing waiting for review" in agent_msg.content.lower()


def test_retry_last_intent_with_prior_rejection_kicks_off_a_new_run(
    db_session, server_settings
):
    fake = FakeLLM(intent=ChatIntent(type="retry_last"))
    orch = _orch(db_session, server_settings, fake)
    conv = orch.create("retry")
    # Need a task with a prior rejection so retry_after_rejection works.
    db_session.add_all([
        Task(
            task_id="t_retry",
            conversation_id=conv.conversation_id,
            title="x",
            brief_text="b",
            requested_output_type="static_image",
            workflow_state="human_rejected",
            created_by="chat",
        ),
        Run(run_id="r_retry", task_id="t_retry", attempt_number=1, status="rejected"),
        Review(
            review_id="rv_retry",
            task_id="t_retry",
            run_id="r_retry",
            decision="rejected",
            reason="too dark",
        ),
    ])
    db_session.commit()

    _, agent_msg = orch.post_message(
        conv.conversation_id, "try again with brighter lighting", None, []
    )

    assert agent_msg is not None
    assert agent_msg.content.lower().startswith("running another attempt")
    # A new run was created (attempt_number > 1)
    new_runs = (
        db_session.query(Run)
        .filter(Run.task_id == "t_retry", Run.attempt_number > 1)
        .all()
    )
    assert len(new_runs) == 1


def test_gate_a_intent_without_attachments_asks_for_an_image(db_session, server_settings):
    fake = FakeLLM(intent=ChatIntent(type="gate_a", title="x", brief="y"))
    orch = _orch(db_session, server_settings, fake)
    conv = orch.create("c")

    _, agent_msg = orch.post_message(conv.conversation_id, "make me a hero", None, [])

    assert agent_msg is not None
    assert "reference image" in agent_msg.content.lower()
