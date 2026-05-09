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

