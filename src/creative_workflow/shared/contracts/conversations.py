"""Conversation / message contracts for the chat-driven operator console.

Phase 2 keeps the shape minimal: the orchestrator routes deterministically.
Phase 3 plugs the local LLM in without breaking these contracts.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ConversationSummary(BaseModel):
    conversation_id: str
    title: str
    created_at: str
    updated_at: str
    hidden_at: str | None = None
    message_count: int = 0
    last_message_preview: str | None = None
    last_message_at: str | None = None
    gallery_count: int = 0
    thumbnail_asset_id: str | None = None


class MessageItem(BaseModel):
    message_id: str
    role: Literal["user", "agent", "system"]
    content: str
    attachments: list[str] = Field(default_factory=list)
    related_task_id: str | None = None
    related_run_id: str | None = None
    created_at: str


class ConversationDetailResponse(BaseModel):
    conversation: ConversationSummary
    messages: list[MessageItem]
    gallery: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)


class CreateConversationRequest(BaseModel):
    title: str | None = None


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class PostMessageResponse(BaseModel):
    user_message: MessageItem
    agent_message: MessageItem | None = None
