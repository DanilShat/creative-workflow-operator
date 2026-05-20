"""Phase 2: conversation API + deterministic orchestrator."""

import io
import json

from fastapi.testclient import TestClient

from creative_workflow.server.app import create_app
from creative_workflow.server.db.base import Base
from creative_workflow.server.db.models import Asset, Job, Run, Task
from creative_workflow.server.db.session import get_db, make_engine, make_session_factory
from creative_workflow.server.services.orchestrator import _parse_variant_count


# 1x1 transparent PNG, enough to satisfy the artifact store + sha256 verify.
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01"
    b"\x00\x01]\xcc\xa1\xe5\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _client(tmp_path, server_settings, db_name="conv.db"):
    server_settings = server_settings.__class__(
        **{**server_settings.__dict__, "database_url": f"sqlite:///{tmp_path / db_name}"}
    )
    engine = make_engine(server_settings.database_url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(server_settings.database_url)
    app = create_app(server_settings)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), factory


# ---------------- CRUD ----------------


def test_create_list_get_round_trip(tmp_path, server_settings):
    client, _ = _client(tmp_path, server_settings)
    assert client.get("/api/v1/conversations").json() == []

    body = client.post("/api/v1/conversations", json={"title": "Spring hero"}).json()
    cid = body["conversation_id"]
    assert body["title"] == "Spring hero"
    assert body["message_count"] == 0
    assert body["thumbnail_asset_id"] is None

    listed = client.get("/api/v1/conversations").json()
    assert [c["conversation_id"] for c in listed] == [cid]

    detail = client.get(f"/api/v1/conversations/{cid}").json()
    assert detail["conversation"]["conversation_id"] == cid
    assert detail["messages"] == []
    assert detail["gallery"] == []
    assert detail["tasks"] == []


def test_get_unknown_conversation_is_404(tmp_path, server_settings):
    client, _ = _client(tmp_path, server_settings)
    assert client.get("/api/v1/conversations/conv_missing").status_code == 404


def test_hide_excludes_from_list_then_restore_brings_back(tmp_path, server_settings):
    client, _ = _client(tmp_path, server_settings)
    cid = client.post("/api/v1/conversations", json={"title": "x"}).json()["conversation_id"]

    assert client.post(f"/api/v1/conversations/{cid}/hide").status_code == 200
    assert client.get("/api/v1/conversations").json() == []
    listed = client.get("/api/v1/conversations?include_hidden=true").json()
    assert len(listed) == 1 and listed[0]["hidden_at"] is not None

    client.post(f"/api/v1/conversations/{cid}/restore")
    assert len(client.get("/api/v1/conversations").json()) == 1


def test_rename_conversation(tmp_path, server_settings):
    client, _ = _client(tmp_path, server_settings)
    cid = client.post("/api/v1/conversations", json={"title": "old"}).json()["conversation_id"]
    r = client.patch(f"/api/v1/conversations/{cid}", json={"title": "new name"})
    assert r.status_code == 200
    assert r.json()["title"] == "new name"


# ---------------- message routing ----------------


def test_text_only_message_yields_placeholder_agent_reply(tmp_path, server_settings):
    client, _ = _client(tmp_path, server_settings)
    cid = client.post("/api/v1/conversations", json={"title": "t"}).json()["conversation_id"]

    body = client.post(
        f"/api/v1/conversations/{cid}/messages",
        data={"text": "what can you do?"},
    ).json()
    assert body["user_message"]["role"] == "user"
    assert body["user_message"]["content"] == "what can you do?"
    assert body["agent_message"] is not None
    assert "next phase" in body["agent_message"]["content"].lower()


def test_empty_message_is_rejected(tmp_path, server_settings):
    client, _ = _client(tmp_path, server_settings)
    cid = client.post("/api/v1/conversations", json={"title": "t"}).json()["conversation_id"]
    r = client.post(f"/api/v1/conversations/{cid}/messages", data={"text": ""})
    assert r.status_code == 409


def test_image_attachment_creates_gate_a_run_with_parsed_variant_count(
    tmp_path, server_settings
):
    client, factory = _client(tmp_path, server_settings)
    cid = client.post("/api/v1/conversations", json={"title": "hero"}).json()["conversation_id"]

    response = client.post(
        f"/api/v1/conversations/{cid}/messages",
        data={"text": "Make 3 variants of a bright product hero on a soft background."},
        files=[("attachments", ("ref.png", io.BytesIO(PNG_BYTES), "image/png"))],
    )
    assert response.status_code == 200, response.text
    body = response.json()

    user_msg = body["user_message"]
    agent_msg = body["agent_message"]
    assert len(user_msg["attachments"]) == 1
    assert user_msg["related_task_id"]
    assert user_msg["related_run_id"]
    assert "3 variant" in agent_msg["content"]

    with factory() as db:
        tasks = db.query(Task).filter(Task.conversation_id == cid).all()
        assert len(tasks) == 1
        task = tasks[0]
        assert task.workflow_state == "waiting_worker"
        jobs = db.query(Job).filter(Job.task_id == task.task_id).all()
        assert len(jobs) == 3  # one Gemini job per variant; Freepik comes later
        assert all(j.required_capability == "browser.gemini" for j in jobs)

    detail = client.get(f"/api/v1/conversations/{cid}").json()
    assert len(detail["messages"]) == 2  # user + agent
    assert len(detail["tasks"]) == 1
    assert detail["tasks"][0]["workflow_state"] == "waiting_worker"


def test_approve_action_records_review_and_advances_task_state(
    tmp_path, server_settings
):
    client, factory = _client(tmp_path, server_settings)
    cid = client.post("/api/v1/conversations", json={"title": "approve"}).json()["conversation_id"]

    with factory() as db:
        db.add_all(
            [
                Task(
                    task_id="task_approve",
                    conversation_id=cid,
                    title="x",
                    brief_text="b",
                    requested_output_type="static_image",
                    workflow_state="waiting_human_review",
                    created_by="chat",
                ),
                Run(
                    run_id="run_approve",
                    task_id="task_approve",
                    attempt_number=1,
                    status="waiting_human_review",
                ),
                Asset(
                    asset_id="asset_approve",
                    task_id="task_approve",
                    run_id="run_approve",
                    asset_class="generated",
                    retention_class="ttl_30d",
                    original_filename="hero.png",
                    stored_filename="asset_approve.png",
                    relative_path="tasks/task_approve/generated/asset_approve.png",
                    content_type="image/png",
                    size_bytes=10,
                    sha256="x" * 64,
                    source_service="freepik",
                ),
            ]
        )
        db.commit()

    r = client.post(
        f"/api/v1/conversations/{cid}/messages",
        data={
            "action": json.dumps(
                {
                    "type": "approve",
                    "run_id": "run_approve",
                    "selected_asset_id": "asset_approve",
                }
            )
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["agent_message"]["content"].lower().startswith("approved")
    with factory() as db:
        assert db.get(Task, "task_approve").workflow_state == "human_approved"


def test_reject_action_requires_reason(tmp_path, server_settings):
    client, factory = _client(tmp_path, server_settings)
    cid = client.post("/api/v1/conversations", json={"title": "rj"}).json()["conversation_id"]
    with factory() as db:
        db.add_all(
            [
                Task(
                    task_id="t_rj",
                    conversation_id=cid,
                    title="x",
                    brief_text="b",
                    requested_output_type="static_image",
                    workflow_state="waiting_human_review",
                    created_by="chat",
                ),
                Run(run_id="r_rj", task_id="t_rj", attempt_number=1, status="waiting_human_review"),
            ]
        )
        db.commit()

    r_no_reason = client.post(
        f"/api/v1/conversations/{cid}/messages",
        data={"action": json.dumps({"type": "reject", "run_id": "r_rj"})},
    )
    assert r_no_reason.status_code == 409

    r_ok = client.post(
        f"/api/v1/conversations/{cid}/messages",
        data={
            "action": json.dumps(
                {"type": "reject", "run_id": "r_rj", "reason": "too dark"}
            )
        },
    )
    assert r_ok.status_code == 200
    with factory() as db:
        assert db.get(Task, "t_rj").workflow_state == "human_rejected"


def test_action_targeting_a_run_in_another_conversation_is_rejected(
    tmp_path, server_settings
):
    client, factory = _client(tmp_path, server_settings)
    cid_a = client.post("/api/v1/conversations", json={"title": "A"}).json()["conversation_id"]
    cid_b = client.post("/api/v1/conversations", json={"title": "B"}).json()["conversation_id"]
    with factory() as db:
        db.add_all(
            [
                Task(
                    task_id="t_a",
                    conversation_id=cid_a,
                    title="x",
                    brief_text="b",
                    requested_output_type="static_image",
                    workflow_state="waiting_human_review",
                    created_by="chat",
                ),
                Run(run_id="r_a", task_id="t_a", attempt_number=1, status="waiting_human_review"),
            ]
        )
        db.commit()

    r = client.post(
        f"/api/v1/conversations/{cid_b}/messages",
        data={"action": json.dumps({"type": "approve", "run_id": "r_a"})},
    )
    assert r.status_code == 409


def test_posting_to_a_hidden_conversation_is_rejected(tmp_path, server_settings):
    client, _ = _client(tmp_path, server_settings)
    cid = client.post("/api/v1/conversations", json={"title": "h"}).json()["conversation_id"]
    client.post(f"/api/v1/conversations/{cid}/hide")
    r = client.post(
        f"/api/v1/conversations/{cid}/messages", data={"text": "hello"}
    )
    assert r.status_code == 409


# ---------------- helpers ----------------


def test_variant_count_heuristic():
    assert _parse_variant_count("") == 1
    assert _parse_variant_count("hi") == 1
    assert _parse_variant_count("make 3 variants") == 3
    assert _parse_variant_count("I need 4 versions of this") == 4
    assert _parse_variant_count("2 options please") == 2
    assert _parse_variant_count("show me 5 images") == 5
    assert _parse_variant_count("make 30 variants") == 20  # capped at 20
