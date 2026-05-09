from pathlib import Path

import pytest

from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.base import Base
from creative_workflow.server.db.session import make_engine, make_session_factory


@pytest.fixture()
def server_settings(tmp_path: Path) -> ServerSettings:
    return ServerSettings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        server_public_base_url="http://testserver",
        artifact_root=tmp_path / "artifacts",
        server_secret="test-secret-at-least-32-characters",
        allow_worker_registration=False,
        trusted_worker_ids={"designer-laptop-01"},
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="test-model",
    )


@pytest.fixture()
def db_session(server_settings: ServerSettings):
    engine = make_engine(server_settings.database_url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(server_settings.database_url)
    with factory() as session:
        yield session

