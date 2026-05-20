"""HTTP API for the chat-driven operator console.

The console talks to exactly these endpoints. Image uploads come as multipart
attachments on `POST /messages` — the server hashes them itself, so the
browser doesn't have to do anything beyond drag-and-drop.
"""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from creative_workflow.server.api.deps import get_settings
from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.session import get_db
from creative_workflow.server.services.orchestrator import (
    ConversationOrchestrator,
    OrchestratorError,
)
from creative_workflow.shared.contracts.conversations import (
    ConversationDetailResponse,
    ConversationSummary,
    CreateConversationRequest,
    PostMessageResponse,
    RenameConversationRequest,
)

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


def _orch(db: Session, settings: ServerSettings) -> ConversationOrchestrator:
    return ConversationOrchestrator(db, settings)


@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    include_hidden: bool = False,
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    return _orch(db, settings).list(include_hidden=include_hidden)


@router.post("", response_model=ConversationSummary)
def create_conversation(
    payload: CreateConversationRequest,
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    orch = _orch(db, settings)
    return orch.summary(orch.create(payload.title))


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    try:
        return _orch(db, settings).get(conversation_id)
    except OrchestratorError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": str(exc)}
        ) from exc


@router.patch("/{conversation_id}", response_model=ConversationSummary)
def rename_conversation(
    conversation_id: str,
    payload: RenameConversationRequest,
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    orch = _orch(db, settings)
    try:
        return orch.summary(orch.rename(conversation_id, payload.title))
    except OrchestratorError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": str(exc)}
        ) from exc


@router.post("/{conversation_id}/hide")
def hide_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    try:
        _orch(db, settings).hide(conversation_id)
    except OrchestratorError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": str(exc)}
        ) from exc
    return {"accepted": True}


@router.post("/{conversation_id}/restore")
def restore_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    try:
        _orch(db, settings).restore(conversation_id)
    except OrchestratorError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": str(exc)}
        ) from exc
    return {"accepted": True}


@router.post("/{conversation_id}/messages", response_model=PostMessageResponse)
async def post_message(
    conversation_id: str,
    text: str = Form(default=""),
    action: str | None = Form(default=None),
    attachments: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    """Single send endpoint. Multipart so the same call carries text + files.

    `action` is an optional JSON string for button clicks
    ({"type": "approve" | "reject" | "retry", ...}). Without `action`, an
    attached image triggers a Gate A run; plain text gets a placeholder reply.
    """

    parsed_action: dict | None = None
    if action:
        try:
            parsed_action = json.loads(action)
            if not isinstance(parsed_action, dict):
                raise ValueError("action must be a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "validation_error", "message": f"invalid action: {exc}"},
            ) from exc

    files: list[tuple[bytes, str, str]] = []
    for f in attachments:
        files.append(
            (
                await f.read(),
                f.filename or "attachment",
                f.content_type or "application/octet-stream",
            )
        )

    orch = _orch(db, settings)
    try:
        user_msg, agent_msg = orch.post_message(
            conversation_id, text, parsed_action, files
        )
    except OrchestratorError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "conflict", "message": str(exc)}
        ) from exc
    return PostMessageResponse(
        user_message=orch.message_item(user_msg),
        agent_message=orch.message_item(agent_msg) if agent_msg else None,
    )
