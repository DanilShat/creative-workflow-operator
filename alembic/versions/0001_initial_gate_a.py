"""initial Gate A metadata schema

Revision ID: 0001_initial_gate_a
Revises:
Create Date: 2026-05-04
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_gate_a"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workers",
        sa.Column("worker_id", sa.String(128), primary_key=True),
        sa.Column("display_name", sa.String(255)),
        sa.Column("version", sa.String(64)),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("host_apps", sa.JSON(), nullable=False),
        sa.Column("profile_status", sa.JSON(), nullable=False),
        sa.Column("machine_info", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("active_job_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "worker_tokens",
        sa.Column("worker_id", sa.String(128), sa.ForeignKey("workers.worker_id"), primary_key=True),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("brief_text", sa.Text(), nullable=False),
        sa.Column("requested_output_type", sa.String(64), nullable=False),
        sa.Column("workflow_state", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("tasks.task_id"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("source_review_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("tasks.task_id"), nullable=False),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.run_id"), nullable=False),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("required_capability", sa.String(128), nullable=False),
        sa.Column("action_name", sa.String(128), nullable=False),
        sa.Column("inputs_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("claimed_by_worker_id", sa.String(128), sa.ForeignKey("workers.worker_id")),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("retry_policy_json", sa.JSON(), nullable=False),
        sa.Column("failure_type", sa.String(128)),
        sa.Column("failure_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "prompts",
        sa.Column("prompt_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("tasks.task_id"), nullable=False),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.run_id"), nullable=False),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.job_id")),
        sa.Column("prompt_role", sa.String(64), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text()),
        sa.Column("prompt_language", sa.String(32)),
        sa.Column("source_service", sa.String(64), nullable=False),
        sa.Column("raw_response_asset_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "assets",
        sa.Column("asset_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("tasks.task_id"), nullable=False),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.run_id")),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.job_id")),
        sa.Column("asset_class", sa.String(64), nullable=False),
        sa.Column("retention_class", sa.String(64), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("stored_filename", sa.String(255), nullable=False),
        sa.Column("relative_path", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("source_service", sa.String(64), nullable=False),
        sa.Column("debug_kind", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "reviews",
        sa.Column("review_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("tasks.task_id"), nullable=False),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.run_id"), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("selected_asset_id", sa.String(64), sa.ForeignKey("assets.asset_id")),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workflow_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("tasks.task_id"), nullable=False),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.run_id")),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.job_id")),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in [
        "workflow_events",
        "reviews",
        "assets",
        "prompts",
        "jobs",
        "runs",
        "tasks",
        "worker_tokens",
        "workers",
    ]:
        op.drop_table(table)

