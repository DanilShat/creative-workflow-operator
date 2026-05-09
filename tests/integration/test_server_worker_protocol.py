from fastapi.testclient import TestClient

from creative_workflow.server.app import create_app
from creative_workflow.server.db.base import Base
from creative_workflow.server.db.models import Job, Run, Task, Worker
from creative_workflow.server.db.session import get_db, make_engine, make_session_factory
from creative_workflow.server.services.worker_auth import WorkerAuthService
from creative_workflow.shared.enums import JobState, JobType, WorkflowState
from creative_workflow.shared.time import utc_now


def test_worker_register_heartbeat_and_invalid_token_rejected(tmp_path, server_settings):
    server_settings = server_settings.__class__(
        **{**server_settings.__dict__, "database_url": f"sqlite:///{tmp_path / 'api.db'}"}
    )
    engine = make_engine(server_settings.database_url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(server_settings.database_url)
    with factory() as db:
        token = WorkerAuthService(db, server_settings).create_token("designer-laptop-01").token

    app = create_app(server_settings)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    payload = {
        "worker_id": "designer-laptop-01",
        "display_name": "Designer",
        "version": "0.1.0",
        "capabilities": ["browser.gemini", "browser.freepik"],
        "host_apps": {},
        "profiles": {},
        "machine_info": {},
    }
    assert client.post("/api/v1/workers/register", json=payload, headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.post("/api/v1/workers/register", json=payload, headers={"Authorization": "Bearer bad"}).status_code == 401

    heartbeat = {
        "worker_id": "designer-laptop-01",
        "status": "idle",
        "active_job_id": None,
        "capabilities": ["browser.gemini"],
        "profile_status": {"gemini": "authenticated"},
        "host_app_status": {},
        "health": {},
    }
    response = client.post("/api/v1/workers/heartbeat", json=heartbeat, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    with factory() as db:
        assert db.get(Worker, "designer-laptop-01").last_heartbeat_at is not None


def test_heartbeat_does_not_clear_server_owned_active_job(tmp_path, server_settings):
    server_settings = server_settings.__class__(
        **{**server_settings.__dict__, "database_url": f"sqlite:///{tmp_path / 'heartbeat.db'}"}
    )
    engine = make_engine(server_settings.database_url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(server_settings.database_url)
    with factory() as db:
        token = WorkerAuthService(db, server_settings).create_token("designer-laptop-01").token
        task = Task(
            task_id="task_1",
            title="Hero",
            brief_text="Brief",
            requested_output_type="static_image",
            workflow_state=WorkflowState.WAITING_WORKER.value,
            created_by="operator",
        )
        run = Run(run_id="run_1", task_id="task_1", attempt_number=1, status="running")
        job = Job(
            job_id="job_1",
            task_id="task_1",
            run_id="run_1",
            job_type=JobType.BROWSER_FLOW.value,
            required_capability="browser.gemini",
            action_name="gemini_build_prompt_from_brief_and_refs",
            inputs_json={},
            state=JobState.CLAIMED.value,
            claimed_by_worker_id="designer-laptop-01",
            lease_expires_at=utc_now(),
            retry_policy_json={},
        )
        worker = db.get(Worker, "designer-laptop-01")
        worker.active_job_id = "job_1"
        worker.status = "running"
        db.add_all([task, run, job])
        db.commit()

    app = create_app(server_settings)

    def override_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    response = client.post(
        "/api/v1/workers/heartbeat",
        json={
            "worker_id": "designer-laptop-01",
            "status": "idle",
            "active_job_id": None,
            "capabilities": ["browser.gemini"],
            "profile_status": {},
            "host_app_status": {},
            "health": {},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    with factory() as db:
        worker = db.get(Worker, "designer-laptop-01")
        assert worker.active_job_id == "job_1"
        assert worker.status == "running"
