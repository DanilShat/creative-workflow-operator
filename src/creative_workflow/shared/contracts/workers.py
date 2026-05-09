"""Worker registration and polling protocol contracts."""

from typing import Any

from pydantic import BaseModel, Field

from creative_workflow.shared.contracts.assets import JobInputAsset
from creative_workflow.shared.enums import JobType, WorkerStatus


class WorkerRegisterRequest(BaseModel):
    worker_id: str
    display_name: str | None = None
    version: str
    capabilities: list[str]
    host_apps: dict[str, Any] = Field(default_factory=dict)
    profiles: dict[str, Any] = Field(default_factory=dict)
    machine_info: dict[str, Any] = Field(default_factory=dict)


class WorkerRegisterResponse(BaseModel):
    worker_id: str
    registered: bool
    server_time: str
    heartbeat_interval_s: int
    claim_poll_interval_s: int
    active_job: str | None = None


class WorkerHeartbeatRequest(BaseModel):
    worker_id: str
    status: WorkerStatus
    active_job_id: str | None = None
    capabilities: list[str]
    profile_status: dict[str, str] = Field(default_factory=dict)
    host_app_status: dict[str, str] = Field(default_factory=dict)
    health: dict[str, Any] = Field(default_factory=dict)


class WorkerHeartbeatResponse(BaseModel):
    accepted: bool = True
    server_time: str
    active_job_lease_expires_at: str | None = None
    commands: list[dict[str, Any]] = Field(default_factory=list)


class ClaimNextRequest(BaseModel):
    worker_id: str
    capabilities: list[str]
    active_job_id: str | None = None


class JobForWorker(BaseModel):
    job_id: str
    task_id: str
    run_id: str
    job_type: JobType
    required_capability: str
    action_name: str
    inputs: dict[str, Any]
    input_assets: list[JobInputAsset] = Field(default_factory=list)
    timeout_s: int
    lease_ttl_s: int
    lease_expires_at: str
    idempotency_key: str


class ClaimNextResponse(BaseModel):
    job: JobForWorker | None = None
    poll_after_s: int = 3

