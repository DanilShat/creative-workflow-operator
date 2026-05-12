"""Task, history, and human-review API contracts used by Streamlit and MCP."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class TaskCreateRequest(BaseModel):
    title: str
    brief_text: str
    requested_output_type: str = "static_image"
    created_by: str = "operator"


class TaskCreateResponse(BaseModel):
    task_id: str
    workflow_state: str
    created_at: str


class StartGateARequest(BaseModel):
    task_id: str
    operator_note: str | None = None
    variant_count: int = Field(1, ge=1, le=20)


class StartGateAResponse(BaseModel):
    task_id: str
    run_id: str
    workflow_state: str
    created_job_ids: list[str]


class AgentChatCreateRequest(BaseModel):
    message: str
    task_id: str | None = None
    preferred_agent: Literal["local_ollama", "claude_cli", "codex_cli"] | None = None


class AgentChatCreateResponse(BaseModel):
    task_id: str
    run_id: str
    job_id: str
    workflow_state: str


class TaskSummaryResponse(BaseModel):
    task_id: str
    title: str
    brief_text: str
    workflow_state: str
    latest_run_id: str | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    latest_generated_asset_ids: list[str] = Field(default_factory=list)


class TaskHistoryResponse(BaseModel):
    task_id: str
    runs: list[dict[str, Any]]
    jobs: list[dict[str, Any]]
    prompts: list[dict[str, Any]]
    assets: list[dict[str, Any]]
    reviews: list[dict[str, Any]]
    workflow_events: list[dict[str, Any]]


class ReviewRequest(BaseModel):
    run_id: str
    decision: Literal["approved", "rejected"]
    selected_asset_id: str | None = None
    reason: str | None = None


class ReviewResponse(BaseModel):
    review_id: str
    task_id: str
    workflow_state: str


class RetryRequest(BaseModel):
    source_run_id: str
    review_id: str
    repair_instruction: str


class RetryResponse(BaseModel):
    task_id: str
    run_id: str
    workflow_state: str
    created_job_ids: list[str]

