"""Small UI view models for the Streamlit chat surface.

Streamlit reruns the whole script on every interaction, so keeping formatting
logic in pure functions makes the chat state easier to test and avoids hiding
workflow behavior inside widget callbacks.
"""

from __future__ import annotations

from typing import Any, Iterable


TERMINAL_JOB_STATES = {"completed", "failed_fatal", "failed_retryable", "cancelled", "orphaned"}


def reference_summaries(uploaded_files: Iterable[Any]) -> list[dict[str, str]]:
    """Return stable display metadata for every reference in the current turn."""

    summaries: list[dict[str, str]] = []
    for upload in uploaded_files:
        size = int(getattr(upload, "size", 0) or 0)
        summaries.append(
            {
                "name": str(getattr(upload, "name", "reference")),
                "size_label": _size_label(size),
                "content_type": str(getattr(upload, "type", "") or "application/octet-stream"),
            }
        )
    return summaries


def format_user_message(prompt: str, references: list[dict[str, str]]) -> str:
    """Render the designer's turn as a chat message with visible attachments."""

    prompt = prompt.strip()
    if not references:
        return prompt
    lines = [prompt, "", "**Attached references**"]
    for item in references:
        lines.append(f"- `{item['name']}` ({item['size_label']}, {item['content_type']})")
    return "\n".join(lines)


def active_worker_job(history: dict[str, Any]) -> dict[str, Any] | None:
    """Return the latest non-terminal worker job, if the task is still moving."""

    for job in reversed(history.get("jobs", [])):
        if job.get("state") not in TERMINAL_JOB_STATES:
            return job
    return None


def progress_lines(history: dict[str, Any]) -> list[str]:
    """Summarize recent worker events for compact chat progress rendering."""

    lines: list[str] = []
    for event in history.get("workflow_events", [])[-8:]:
        event_type = event.get("event_type")
        payload = event.get("payload_json") or {}
        if event_type == "job_claimed":
            lines.append(f"Worker claimed `{event.get('job_id')}`.")
        elif event_type == "job_progress":
            step = payload.get("step") or "step"
            message = payload.get("message") or payload.get("state") or ""
            lines.append(f"`{step}`: {message}")
        elif event_type == "job_failed":
            lines.append(f"Failed: `{payload.get('failure_type')}` {payload.get('message') or ''}".strip())
        elif event_type in {"freepik_job_created", "waiting_human_review", "job_completed"}:
            lines.append(event_type.replace("_", " ").capitalize())
    return lines


def _size_label(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"
