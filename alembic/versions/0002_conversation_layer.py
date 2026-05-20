"""conversation and message tables for the chat-driven console

Adds the data backbone for the new chat UI:

* `conversations` — one designer chat (left-rail row), with a soft-delete via
  `hidden_at` so the designer can hide rows without losing history.
* `messages` — turns inside a conversation. `related_task_id` / `related_run_id`
  let an agent bubble point at the Gate A run it is reporting on.
* `tasks.conversation_id` — nullable; pre-existing tasks keep NULL and still
  work, new chat-driven tasks get attached to a conversation.

Revision ID: 0002_conversation_layer
Revises: 0001_initial_gate_a
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_conversation_layer"
down_revision = "0001_initial_gate_a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("conversation_id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hidden_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "messages",
        sa.Column("message_id", sa.String(64), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(64),
            sa.ForeignKey("conversations.conversation_id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("attachments_json", sa.JSON(), nullable=False),
        sa.Column("related_task_id", sa.String(64), sa.ForeignKey("tasks.task_id")),
        sa.Column("related_run_id", sa.String(64), sa.ForeignKey("runs.run_id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "conversation_id",
            sa.String(64),
            sa.ForeignKey("conversations.conversation_id"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tasks", "conversation_id")
    op.drop_table("messages")
    op.drop_table("conversations")
