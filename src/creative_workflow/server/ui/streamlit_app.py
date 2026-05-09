"""Chat-first Streamlit operator UI for Gate A.

The operator/designer talks to the server as a task agent. The UI still calls
FastAPI for durable task state, artifact storage, and review decisions; it does
not bypass the worker protocol or launch browsers directly.
"""

from pathlib import Path
import hashlib
import json
import os

import httpx
import streamlit as st


PUBLIC_API_BASE = os.getenv("SERVER_PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
INTERNAL_API_BASE = os.getenv("API_INTERNAL_BASE_URL", PUBLIC_API_BASE).rstrip("/")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _client() -> httpx.Client:
    # Streamlit runs server-side Python. In Docker it must talk to the API
    # service over the compose network, while browser-visible asset URLs must
    # still use the public operator URL.
    return httpx.Client(base_url=INTERNAL_API_BASE, timeout=120)


def _title_from_brief(brief: str) -> str:
    first = next((line.strip() for line in brief.splitlines() if line.strip()), "Creative task")
    return first[:80]


def _create_and_start_task(brief: str, reference, output_type: str) -> dict:
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


def _task_snapshot(task_id: str) -> tuple[dict | None, dict | None]:
    with _client() as client:
        summary_resp = client.get(f"/api/v1/tasks/{task_id}")
        if summary_resp.status_code != 200:
            return None, None
        history_resp = client.get(f"/api/v1/tasks/{task_id}/history")
        history_resp.raise_for_status()
        return summary_resp.json(), history_resp.json()


def _latest_job_line(history: dict) -> str:
    jobs = history.get("jobs", [])
    if not jobs:
        return "No worker job has been created yet."
    latest = jobs[-1]
    state = latest.get("state")
    action = latest.get("action_name")
    worker = latest.get("claimed_by_worker_id") or "unclaimed"
    return f"Latest job: `{action}` is `{state}` on `{worker}`."


st.set_page_config(page_title="Creative Workflow", layout="wide")
st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem; max-width: 980px; }
    [data-testid="stSidebar"] { min-width: 310px; }
    .stChatMessage { border-radius: 8px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Creative Workflow")
st.caption(f"Server: {PUBLIC_API_BASE}")

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "Upload a reference, then paste the brief here. I will create the task and send it to the worker.",
        }
    ]
if "task_id" not in st.session_state:
    st.session_state.task_id = ""
if "last_submitted_brief" not in st.session_state:
    st.session_state.last_submitted_brief = ""

with st.sidebar:
    st.subheader("Run Setup")
    output_type = st.radio("Output", ["static_image", "video"], horizontal=True)
    reference = st.file_uploader("Reference", type=["png", "jpg", "jpeg", "webp"])
    if reference:
        st.image(reference, caption=reference.name, use_column_width=True)
    st.session_state.task_id = st.text_input("Task ID", st.session_state.task_id)
    if st.button("Refresh", use_container_width=True):
        st.rerun()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if st.session_state.task_id:
    summary, history = _task_snapshot(st.session_state.task_id)
    if summary and history:
        with st.chat_message("assistant"):
            st.markdown(
                f"Task `{summary['task_id']}` is `{summary['workflow_state']}`. "
                f"{_latest_job_line(history)}"
            )
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
                if col_b.button("Reject And Retry", use_container_width=True, disabled=not reason):
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

brief = st.chat_input("Paste the brief and press Enter")
if brief:
    if brief == st.session_state.last_submitted_brief:
        st.stop()
    st.session_state.last_submitted_brief = brief
    st.session_state.messages.append({"role": "user", "content": brief})
    if reference is None:
        st.session_state.messages.append(
            {"role": "assistant", "content": "Upload a reference image first, then send the brief again."}
        )
        st.rerun()
    try:
        started = _create_and_start_task(brief, reference, output_type)
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
    except httpx.HTTPError as exc:
        st.session_state.messages.append({"role": "assistant", "content": f"Server request failed: `{exc}`"})
    st.rerun()
