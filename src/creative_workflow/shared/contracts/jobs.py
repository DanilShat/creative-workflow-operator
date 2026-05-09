"""Job lifecycle and browser-flow result contracts."""

from typing import Any

from pydantic import BaseModel, Field

from creative_workflow.shared.enums import FailureType, JobExecutionState, JobType, ProfileStatus, SourceService


class RetryPolicy(BaseModel):
    max_attempts: int = 2
    retryable_failure_types: list[FailureType] = Field(default_factory=list)


class JobEnvelope(BaseModel):
    job_id: str
    task_id: str
    run_id: str
    job_type: JobType
    required_capability: str
    action_name: str
    inputs: dict[str, Any]
    timeout_s: int = 1200
    lease_ttl_s: int = 90
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)


class JobProgressRequest(BaseModel):
    worker_id: str
    state: JobExecutionState
    step: str
    message: str
    percent: int | None = Field(default=None, ge=0, le=100)
    debug_asset_ids: list[str] = Field(default_factory=list)
    timestamp: str


class BrowserFlowResult(BaseModel):
    service: SourceService
    flow_name: str
    profile_status: ProfileStatus
    structured_output: dict[str, Any] = Field(default_factory=dict)
    artifact_ids: list[str] = Field(default_factory=list)
    debug_asset_ids: list[str] = Field(default_factory=list)
    external_urls: list[str] = Field(default_factory=list)
    failure_class: FailureType | None = None


class GeminiPromptOutput(BaseModel):
    prompt_text: str
    negative_prompt: str | None = None
    prompt_language: str = "en"
    extracted_from_response: bool = True
    raw_response_asset_id: str | None = None


class FreepikGenerationOutput(BaseModel):
    generated_asset_ids: list[str]
    selected_asset_id: str | None = None
    downloaded_files_count: int
    provider_visible_model: str | None = None
    credits_visible: str | None = None


class JobCompleteRequest(BaseModel):
    worker_id: str
    outputs: dict[str, Any]
    artifact_ids: list[str] = Field(default_factory=list)
    completed_at: str


class JobCompleteResponse(BaseModel):
    accepted: bool = True
    server_workflow_state: str


class JobFailRequest(BaseModel):
    worker_id: str
    failure_type: FailureType
    retryable: bool
    message: str
    debug_asset_ids: list[str] = Field(default_factory=list)
    failed_at: str


class JobFailResponse(BaseModel):
    accepted: bool = True
    next_state: str

