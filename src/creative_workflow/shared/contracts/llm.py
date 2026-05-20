"""Strict JSON schemas produced by the server-side local LLM."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class BriefNormalization(BaseModel):
    goal: str
    job_type: Literal["static", "video", "unknown"] = "unknown"
    style: str | None = None
    format: str | None = None
    must_have: list[str] = Field(default_factory=list)
    must_not_have: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class RouteDecision(BaseModel):
    next_step: Literal[
        "gemini_prompt_builder",
        "freepik_image_generation",
        "human_clarification",
        "wait_human_review",
    ]
    required_capability: str
    reason: str
    job_request: dict[str, Any] = Field(default_factory=dict)


class RetryRepairDecision(BaseModel):
    decision: Literal["retry_with_prompt_repair", "ask_human", "accept", "stop"]
    repair_instruction: str | None = None
    new_job_request: dict[str, Any] | None = None
    reason: str


class TitleResult(BaseModel):
    """A short conversation title produced by the local LLM."""

    title: str = Field(min_length=1, max_length=80)


class ChatIntent(BaseModel):
    """The chat orchestrator's read of what the user is asking for.

    ``type`` drives routing; the rest is filled when ``type == "gate_a"``
    so a Gate A run can be started without a second LLM call.
    """

    type: Literal["chat", "gate_a", "approve_last", "reject_last", "retry_last"]
    title: str | None = None
    brief: str | None = None
    output_type: Literal["static_image", "video"] | None = None

