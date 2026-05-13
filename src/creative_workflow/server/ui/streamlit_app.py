"""Chat-first Streamlit operator UI.

The UI behaves like a small agent console: the designer types into one chat box,
the operator server stores state, and the worker executes local Ollama/Claude
Code/Codex CLI or browser jobs through the same polling protocol.
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import time
from typing import Any

import httpx
import streamlit as st

from creative_workflow.server.ui.view_models import (
    active_worker_job,
    format_user_message,
    progress_lines,
    reference_summaries,
)


PUBLIC_API_BASE = os.getenv("SERVER_PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
INTERNAL_API_BASE = os.getenv("API_INTERNAL_BASE_URL", PUBLIC_API_BASE).rstrip("/")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _client() -> httpx.Client:
    # In Docker, Streamlit talks to the API service over the compose network.
    # Browser-visible artifact URLs still use PUBLIC_API_BASE.
    return httpx.Client(base_url=INTERNAL_API_BASE, timeout=120)


def _title_from_brief(brief: str) -> str:
    first = next((line.strip() for line in brief.splitlines() if line.strip()), "Creative task")
    return first[:80]


def _create_and_start_task(brief: str, references: list[Any], output_type: str) -> dict[str, Any]:
    with _client() as client:
        task_resp = client.post(
            "/api/v1/tasks",
            json={
                "title": _title_from_brief(brief),
                "brief_text": brief,
                "requested_output_type": output_type,
                "created_by": "operator",
            },
        )
        task_resp.raise_for_status()
        task = task_resp.json()

        for reference in references:
            data = reference.getvalue()
            metadata = {
                "original_filename": Path(reference.name).name,
                "content_type": reference.type or "application/octet-stream",
                "size_bytes": len(data),
                "sha256": _sha256(data),
                "source_service": "manual",
            }
            ref_resp = client.post(
                f"/api/v1/tasks/{task['task_id']}/references",
                files={"file": (reference.name, data, reference.type)},
                data={"metadata": json.dumps(metadata)},
            )
            ref_resp.raise_for_status()

        start_resp = client.post(
            f"/api/v1/tasks/{task['task_id']}/start-gate-a",
            json={"task_id": task["task_id"], "operator_note": "Started from chat brief."},
        )
        start_resp.raise_for_status()
        return start_resp.json()


def _create_agent_chat(message: str, task_id: str | None, preferred_agent: str | None) -> dict[str, Any]:
    with _client() as client:
        response = client.post(
            "/api/v1/tasks/agent-chat",
            json={"message": message, "task_id": task_id or None, "preferred_agent": preferred_agent},
        )
        response.raise_for_status()
        return response.json()


def _task_snapshot(task_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    with _client() as client:
        summary_resp = client.get(f"/api/v1/tasks/{task_id}")
        if summary_resp.status_code != 200:
            return None, None
        history_resp = client.get(f"/api/v1/tasks/{task_id}/history")
        history_resp.raise_for_status()
        return summary_resp.json(), history_resp.json()


def _latest_job_line(history: dict[str, Any]) -> str:
    jobs = history.get("jobs", [])
    if not jobs:
        return "No worker job has been created yet."
    latest = jobs[-1]
    state = latest.get("state")
    action = latest.get("action_name")
    worker = latest.get("claimed_by_worker_id") or "unclaimed"
    return f"Latest job: `{action}` is `{state}` on `{worker}`."


def _agent_completion(history: dict[str, Any], job_id: str) -> str | None:
    for event in history.get("workflow_events", []):
        if event.get("job_id") != job_id:
            continue
        if event.get("event_type") == "agent_chat_completed":
            output = (event.get("payload_json") or {}).get("outputs", {}).get("agent_chat", {})
            agent = output.get("routed_to") or output.get("agent") or "agent"
            text = output.get("text") or ""
            return f"**{agent}**\n\n{text}"
        if event.get("event_type") == "job_failed":
            payload = event.get("payload_json") or {}
            return f"Worker failed: `{payload.get('failure_type')}`\n\n{payload.get('message') or ''}"
    return None


def _sync_tracked_jobs() -> None:
    for job_id, item in list(st.session_state.tracked_jobs.items()):
        if item.get("displayed"):
            continue
        _summary, history = _task_snapshot(item["task_id"])
        if not history:
            continue
        reply = _agent_completion(history, job_id)
        if reply:
            st.session_state.messages.append({"role": "assistant", "content": reply})
            item["displayed"] = True


st.set_page_config(page_title="Creative Workflow", layout="wide")
st.markdown(
    """
    <style>
    .block-container { padding-top: 1.2rem; max-width: 1120px; }
    [data-testid="stSidebar"] { min-width: 320px; }
    .cw-shell { border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px 16px; background: #fbfbfa; }
    .cw-title { font-size: 1.35rem; font-weight: 650; margin-bottom: 0.15rem; }
    .cw-subtle { color: #666; font-size: 0.9rem; }
    .stChatMessage { border-radius: 8px; }
    div[data-testid="stMetric"] { border: 1px solid #eee; border-radius: 8px; padding: 8px 10px; }
    </style>
    """,
    unsafe_allow_html=True,
)

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "Send a brief, ask for analysis, or attach a reference and request an image run. "
                "I will route routine work to Ollama and escalation work to Claude Code or Codex CLI on the worker."
            ),
        }
    ]
if "task_id" not in st.session_state:
    st.session_state.task_id = ""
if "tracked_jobs" not in st.session_state:
    st.session_state.tracked_jobs = {}
if "composer_text" not in st.session_state:
    st.session_state.composer_text = ""

_sync_tracked_jobs()

st.markdown(
    f"""
    <div class="cw-shell">
      <div class="cw-title">Creative Workflow Agent</div>
      <div class="cw-subtle">Operator API: {PUBLIC_API_BASE}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("Session")
    mode = st.radio("Mode", ["Agent chat", "Generate image"], horizontal=False)
    preferred = st.selectbox("Preferred agent", ["Auto", "Ollama", "Claude Code", "Codex CLI"])
    output_type = st.radio("Output type", ["static_image", "video"], horizontal=True)
    reference_files = st.file_uploader(
        "Optional references",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
    )
    if reference_files:
        st.caption(f"{len(reference_files)} reference file(s) ready for the next message.")
        for reference in reference_files:
            st.image(reference, caption=reference.name, use_column_width=True)
    st.session_state.task_id = st.text_input("Current task", st.session_state.task_id)
    if st.button("Refresh status", use_container_width=True):
        st.rerun()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if st.session_state.task_id:
    summary, history = _task_snapshot(st.session_state.task_id)
    if summary and history:
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Task", summary["task_id"])
        col_b.metric("State", summary["workflow_state"])
        col_c.metric("Generated", len(summary["latest_generated_asset_ids"]))
        with st.chat_message("assistant"):
            st.markdown(_latest_job_line(history))
            lines = progress_lines(history)
            if lines:
                st.markdown("**Progress**")
                for line in lines[-5:]:
                    st.markdown(f"- {line}")
            for asset_id in summary["latest_generated_asset_ids"]:
                st.image(f"{PUBLIC_API_BASE}/api/v1/assets/{asset_id}/download", caption=asset_id)

        if summary["workflow_state"] == "waiting_human_review" and summary["latest_run_id"]:
            st.subheader("Review")
            selected = st.selectbox("Generated asset", summary["latest_generated_asset_ids"])
            reason = st.text_input("Rejection feedback")
            col_a, col_b = st.columns(2)
            with _client() as client:
                if col_a.button("Approve", use_container_width=True):
                    client.post(
                        f"/api/v1/tasks/{summary['task_id']}/reviews",
                        json={
                            "run_id": summary["latest_run_id"],
                            "decision": "approved",
                            "selected_asset_id": selected,
                            "reason": "Approved from chat UI.",
                        },
                    ).raise_for_status()
                    st.rerun()
                if col_b.button("Reject and retry", use_container_width=True, disabled=not reason):
                    review = client.post(
                        f"/api/v1/tasks/{summary['task_id']}/reviews",
                        json={
                            "run_id": summary["latest_run_id"],
                            "decision": "rejected",
                            "selected_asset_id": selected,
                            "reason": reason,
                        },
                    )
                    review.raise_for_status()
                    client.post(
                        f"/api/v1/tasks/{summary['task_id']}/retry",
                        json={
                            "source_run_id": summary["latest_run_id"],
                            "review_id": review.json()["review_id"],
                            "repair_instruction": reason,
                        },
                    ).raise_for_status()
                    st.rerun()

        with st.expander("Task history"):
            st.json(history)

with st.container():
    prompt = st.text_area(
        "Message the workflow agent",
        key="composer_text",
        height=150,
        placeholder="Paste the brief here. Attach references in the sidebar when you want an image run.",
    )
    send_clicked = st.button("Send", type="primary", use_container_width=True)

if send_clicked and prompt.strip():
    prompt = prompt.strip()
    current_references = list(reference_files or [])
    st.session_state.messages.append(
        {"role": "user", "content": format_user_message(prompt, reference_summaries(current_references))}
    )
    preferred_agent = {
        "Auto": None,
        "Ollama": "local_ollama",
        "Claude Code": "claude_cli",
        "Codex CLI": "codex_cli",
    }[preferred]
    try:
        if mode == "Generate image":
            if not current_references:
                st.session_state.messages.append(
                    {"role": "assistant", "content": "Attach one or more reference images, then send the image brief again."}
                )
            else:
                started = _create_and_start_task(prompt, current_references, output_type)
                st.session_state.task_id = started["task_id"]
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": (
                            f"Started `{started['task_id']}`. "
                            f"Run `{started['run_id']}` created jobs: `{', '.join(started['created_job_ids'])}`."
                        ),
                    }
                )
        else:
            created = _create_agent_chat(prompt, st.session_state.task_id or None, preferred_agent)
            st.session_state.task_id = created["task_id"]
            if created.get("reply"):
                reply = created["reply"]
                st.session_state.messages.append(
                    {"role": "assistant", "content": f"**{reply.get('routed_to', 'agent')}**\n\n{reply.get('text', '')}"}
                )
            else:
                st.session_state.tracked_jobs[created["job_id"]] = {"task_id": created["task_id"], "displayed": False}
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": (
                            f"Sent to worker as `{created['job_id']}`. "
                            "Use Refresh status if the answer does not appear automatically."
                        ),
                    }
                )
    except httpx.HTTPError as exc:
        st.session_state.messages.append({"role": "assistant", "content": f"Server request failed: `{exc}`"})
    st.session_state.composer_text = ""
    st.rerun()

if st.session_state.task_id:
    _summary, _history = _task_snapshot(st.session_state.task_id)
    if _summary and _history and active_worker_job(_history):
        time.sleep(2)
        st.rerun()
