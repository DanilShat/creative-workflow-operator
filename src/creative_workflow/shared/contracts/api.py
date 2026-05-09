"""Common API response contracts."""

from typing import Any

from pydantic import BaseModel, Field


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ApiError


class AcceptedResponse(BaseModel):
    accepted: bool = True

