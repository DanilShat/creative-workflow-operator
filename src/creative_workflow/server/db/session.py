"""Database engine/session helpers.

The runtime target is PostgreSQL. Tests may inject a SQLite URL to validate
service behavior without pretending SQLite is the deployment database.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker



def make_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=make_engine(database_url), autoflush=False, expire_on_commit=False, future=True)


SessionLocal: sessionmaker[Session] | None = None


def get_db() -> Generator[Session, None, None]:
    global SessionLocal
    if SessionLocal is None:
        from creative_workflow.server.config import ServerSettings

        SessionLocal = make_session_factory(ServerSettings.load().database_url)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
