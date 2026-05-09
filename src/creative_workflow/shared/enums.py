"""Canonical enums for protocol and state-machine boundaries.

Keeping these values centralized prevents the common failure mode where the
server and worker silently drift into different state names.
"""

from enum import StrEnum


class WorkerStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class WorkerRuntimeState(StrEnum):
    STARTING = "starting"
    REGISTERING = "registering"
    IDLE = "idle"
    CLAIMING = "claiming"
    PREPARING_INPUTS = "preparing_inputs"
    RUNNING = "running"
    UPLOADING_OUTPUTS = "uploading_outputs"
    ERROR = "error"
    STOPPING = "stopping"


class JobState(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    UPLOADING_ARTIFACTS = "uploading_artifacts"
    COMPLETED = "completed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FATAL = "failed_fatal"
    CANCELLED = "cancelled"
    ORPHANED = "orphaned"


class JobExecutionState(StrEnum):
    PREPARING_INPUTS = "preparing_inputs"
    EXECUTING = "executing"
    COLLECTING_OUTPUTS = "collecting_outputs"
    UPLOADING_ARTIFACTS = "uploading_artifacts"


class WorkflowState(StrEnum):
    DRAFT = "draft"
    WAITING_WORKER = "waiting_worker"
    RUNNING_WORKER_JOB = "running_worker_job"
    WAITING_HUMAN_REVIEW = "waiting_human_review"
    HUMAN_APPROVED = "human_approved"
    HUMAN_REJECTED = "human_rejected"
    RETRY_REQUESTED = "retry_requested"
    FAILED = "failed"


class JobType(StrEnum):
    BROWSER_FLOW = "browser_flow"
    PHOTOSHOP_ACTION = "photoshop_action"
    AFTEREFFECTS_ACTION = "aftereffects_action"
    ASSET_PREPARE = "asset_prepare"
    CLAUDE_MCP_REQUESTED_ACTION = "claude_mcp_requested_action"


class AssetClass(StrEnum):
    REFERENCE = "reference"
    GENERATED = "generated"
    DEBUG = "debug"
    EXPORT = "export"
    INTERMEDIATE = "intermediate"


class RetentionClass(StrEnum):
    KEEP = "keep"
    TTL_30D = "ttl_30d"
    TTL_7D = "ttl_7d"
    DEBUG_TTL_7D = "debug_ttl_7d"


class FailureType(StrEnum):
    NEEDS_REAUTH = "needs_reauth"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    SELECTOR_BROKEN = "selector_broken"
    UPLOAD_FAILED = "upload_failed"
    DOWNLOAD_FAILED = "download_failed"
    NETWORK_TEMPORARY = "network_temporary"
    PROVIDER_QUOTA_OR_PAYWALL = "provider_quota_or_paywall"
    BROWSER_PROFILE_BROKEN = "browser_profile_broken"
    TRANSIENT_BROWSER_START_FAILURE = "transient_browser_start_failure"
    PHOTOSHOP_NOT_CONNECTED = "photoshop_not_connected"
    AFTEREFFECTS_NOT_CONNECTED = "aftereffects_not_connected"
    INVALID_JOB_PAYLOAD = "invalid_job_payload"
    UNSUPPORTED_ACTION_NAME = "unsupported_action_name"
    FATAL_UNEXPECTED = "fatal_unexpected"


class ProfileStatus(StrEnum):
    UNKNOWN = "unknown"
    NEEDS_SETUP = "needs_setup"
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"
    BROKEN = "broken"


class SourceService(StrEnum):
    GEMINI = "gemini"
    FREEPIK = "freepik"
    KLING = "kling"
    PHOTOSHOP = "photoshop"
    AFTEREFFECTS = "aftereffects"
    CLAUDE = "claude"
    MANUAL = "manual"


class DebugKind(StrEnum):
    SCREENSHOT = "screenshot"
    TRACE = "trace"
    HTML_SNAPSHOT = "html_snapshot"
    STEP_LOG = "step_log"
    RAW_TEXT = "raw_text"


TERMINAL_JOB_STATES = {
    JobState.COMPLETED,
    JobState.FAILED_RETRYABLE,
    JobState.FAILED_FATAL,
    JobState.CANCELLED,
    JobState.ORPHANED,
}

