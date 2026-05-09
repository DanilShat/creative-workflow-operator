"""Worker token creation and validation.

Raw tokens are shown once to the operator and copied to the designer laptop.
The server stores only a salted hash so logs and DB dumps do not expose worker
credentials.
"""

from dataclasses import dataclass
import hashlib
import secrets

from sqlalchemy.orm import Session

from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.models import Worker, WorkerToken
from creative_workflow.shared.time import utc_now


class AuthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def hash_worker_token(raw_token: str, server_secret: str) -> str:
    return hashlib.sha256(f"{raw_token}{server_secret}".encode("utf-8")).hexdigest()


@dataclass
class CreatedWorkerToken:
    worker_id: str
    token: str


class WorkerAuthService:
    def __init__(self, db: Session, settings: ServerSettings):
        self.db = db
        self.settings = settings

    def create_token(self, worker_id: str) -> CreatedWorkerToken:
        raw = secrets.token_urlsafe(32)
        worker = self.db.get(Worker, worker_id)
        if worker is None:
            worker = Worker(worker_id=worker_id, status="idle", capabilities=[])
            self.db.add(worker)
        token = self.db.get(WorkerToken, worker_id)
        if token is None:
            token = WorkerToken(worker_id=worker_id, token_hash="")
            self.db.add(token)
        token.token_hash = hash_worker_token(raw, self.settings.server_secret)
        token.revoked_at = None
        token.created_at = utc_now()
        self.db.commit()
        return CreatedWorkerToken(worker_id=worker_id, token=raw)

    def revoke_token(self, worker_id: str) -> bool:
        token = self.db.get(WorkerToken, worker_id)
        if token is None:
            return False
        token.revoked_at = utc_now()
        self.db.commit()
        return True

    def validate(self, worker_id: str, raw_token: str) -> None:
        if worker_id not in self.settings.trusted_worker_ids and not self.settings.allow_worker_registration:
            raise AuthError("registration_disabled", f"Worker {worker_id} is not trusted.")
        token = self.db.get(WorkerToken, worker_id)
        if token is None:
            raise AuthError("invalid_token", "Worker token has not been created on the server.")
        if token.revoked_at is not None:
            raise AuthError("token_revoked", "Worker token has been revoked.")
        expected = hash_worker_token(raw_token, self.settings.server_secret)
        if not secrets.compare_digest(expected, token.token_hash):
            raise AuthError("invalid_token", "Worker token is invalid.")
        token.last_used_at = utc_now()

    def validate_any_active_token(self, raw_token: str) -> str:
        expected = hash_worker_token(raw_token, self.settings.server_secret)
        for token in self.db.query(WorkerToken).all():
            if token.revoked_at is None and secrets.compare_digest(expected, token.token_hash):
                token.last_used_at = utc_now()
                return token.worker_id
        raise AuthError("invalid_token", "Worker token is invalid.")
