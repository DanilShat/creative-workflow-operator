"""Tests for the operator console: task/worker list endpoints and SPA serving."""

from fastapi.testclient import TestClient

from creative_workflow.server.app import create_app
from creative_workflow.server.db.base import Base
from creative_workflow.server.db.models import Worker
from creative_workflow.server.db.session import get_db, make_engine, make_session_factory
from creative_workflow.shared.time import utc_now


def _client(tmp_path, server_settings, db_name):
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


def test_list_tasks_returns_created_tasks_newest_first(tmp_path, server_settings):
    client, _ = _client(tmp_path, server_settings, "tasks_list.db")
    assert client.get("/api/v1/tasks").json() == []

    created = client.post("/api/v1/tasks", json={"title": "Hero", "brief_text": "A bright product hero."})
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    listing = client.get("/api/v1/tasks")
    assert listing.status_code == 200
    body = listing.json()
    assert len(body) == 1
    assert body[0]["task_id"] == task_id
    assert body[0]["title"] == "Hero"
    assert body[0]["workflow_state"] == "draft"
    assert body[0]["reference_count"] == 0
    assert body[0]["generated_count"] == 0
    assert body[0]["thumbnail_asset_id"] is None


def test_list_workers_returns_registered_workers(tmp_path, server_settings):
    client, factory = _client(tmp_path, server_settings, "workers_list.db")
    assert client.get("/api/v1/workers").json() == []

    with factory() as db:
        db.add(
            Worker(
                worker_id="designer-laptop-01",
                display_name="Designer",
                status="idle",
                capabilities=["browser.gemini", "browser.freepik"],
                last_heartbeat_at=utc_now(),
            )
        )
        db.commit()

    body = client.get("/api/v1/workers").json()
    assert len(body) == 1
    assert body[0]["worker_id"] == "designer-laptop-01"
    assert body[0]["status"] == "idle"
    assert body[0]["capabilities"] == ["browser.gemini", "browser.freepik"]


def test_console_spa_is_served(tmp_path, server_settings):
    client, _ = _client(tmp_path, server_settings, "console.db")

    root = client.get("/", follow_redirects=False)
    assert root.status_code in (307, 308)
    assert root.headers["location"] == "/app/"

    page = client.get("/app/")
    assert page.status_code == 200
    assert "Operator Console" in page.text
