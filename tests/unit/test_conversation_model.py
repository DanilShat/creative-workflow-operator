"""Phase 1: backbone for the chat-driven console.

Covers the new Conversation/Message tables and the optional task->conversation
link without exercising any UI or orchestrator behavior — that comes later.
"""

from sqlalchemy import select

from creative_workflow.server.db.models import Conversation, Message, Task
from creative_workflow.shared.ids import new_id
from creative_workflow.shared.time import utc_now


def test_new_conversation_gets_default_title_and_no_hidden_at(db_session):
    conv_id = new_id("conv")
    db_session.add(Conversation(conversation_id=conv_id))
    db_session.commit()

    saved = db_session.get(Conversation, conv_id)
    assert saved is not None
    assert saved.title == "Untitled"
    assert saved.hidden_at is None
    assert saved.created_at is not None


def test_messages_belong_to_conversation_and_persist_attachments(db_session):
    conv_id = new_id("conv")
    db_session.add(Conversation(conversation_id=conv_id, title="Spring hero"))
    db_session.flush()

    db_session.add_all([
        Message(
            message_id=new_id("msg"),
            conversation_id=conv_id,
            role="user",
            content="Make a hero image",
            attachments_json=["asset_1", "asset_2"],
        ),
        Message(
            message_id=new_id("msg"),
            conversation_id=conv_id,
            role="agent",
            content="Got it. Running Gate A.",
        ),
    ])
    db_session.commit()

    rows = list(
        db_session.scalars(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at)
        )
    )
    assert [m.role for m in rows] == ["user", "agent"]
    assert rows[0].attachments_json == ["asset_1", "asset_2"]
    assert rows[1].attachments_json == []
    assert rows[1].content == "Got it. Running Gate A."


def test_task_can_be_linked_to_a_conversation(db_session):
    conv_id = new_id("conv")
    db_session.add(Conversation(conversation_id=conv_id, title="Linked"))
    db_session.flush()

    task_id = new_id("task")
    db_session.add(
        Task(
            task_id=task_id,
            conversation_id=conv_id,
            title="t",
            brief_text="b",
            requested_output_type="static_image",
            workflow_state="draft",
            created_by="operator",
        )
    )
    db_session.commit()

    assert db_session.get(Task, task_id).conversation_id == conv_id


def test_pre_existing_tasks_keep_null_conversation_id(db_session):
    """Tasks created before the chat UI must keep working without a chat."""

    task_id = new_id("task")
    db_session.add(
        Task(
            task_id=task_id,
            title="solo",
            brief_text="brief",
            requested_output_type="static_image",
            workflow_state="draft",
            created_by="operator",
        )
    )
    db_session.commit()

    assert db_session.get(Task, task_id).conversation_id is None


def test_hidden_at_marks_conversation_soft_deleted(db_session):
    conv_id = new_id("conv")
    db_session.add(Conversation(conversation_id=conv_id, title="hide me"))
    db_session.commit()

    conv = db_session.get(Conversation, conv_id)
    conv.hidden_at = utc_now()
    db_session.commit()

    assert db_session.get(Conversation, conv_id).hidden_at is not None
