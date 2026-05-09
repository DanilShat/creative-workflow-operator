"""Post-Gate-A host action contracts.

These contracts are implemented now so server/worker boundaries are explicit,
but live Photoshop/After Effects execution remains a later gate.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class HostAction(BaseModel):
    host: Literal["photoshop", "after_effects"]
    action_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    requires_confirmation: bool = False
    request_id: str
    task_id: str | None = None
    scene_id: str | None = None


class HostActionPlan(BaseModel):
    plan_id: str
    host: Literal["photoshop", "after_effects"]
    user_intent: str
    actions: list[HostAction]
    summary: str
    warnings: list[str] = Field(default_factory=list)


class HostExecutionResult(BaseModel):
    success: bool
    host: str
    action_name: str
    request_id: str
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_message: str | None = None
    debug_artifacts: list[str] = Field(default_factory=list)

