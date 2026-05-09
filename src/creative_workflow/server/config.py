"""Server configuration loading.

Runtime configuration is intentionally explicit because this MVP spans two
machines. The worker must see only SERVER_PUBLIC_BASE_URL, while Ollama stays
bound to localhost on the operator laptop.
"""

from dataclasses import dataclass
from pathlib import Path
import os


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


@dataclass(frozen=True)
class ServerSettings:
    database_url: str
    server_public_base_url: str
    artifact_root: Path
    server_secret: str
    allow_worker_registration: bool
    trusted_worker_ids: set[str]
    ollama_base_url: str
    ollama_model: str
    heartbeat_interval_s: int = 15
    claim_poll_interval_s: int = 3
    active_job_lease_ttl_s: int = 90
    default_browser_timeout_s: int = 1200

    @classmethod
    def load(cls, env_file: str | Path | None = ".env.server") -> "ServerSettings":
        env_file = os.getenv("CREATIVE_WORKFLOW_ENV_FILE") or env_file
        if env_file:
            _load_env_file(Path(env_file))
        trusted = {
            item.strip()
            for item in os.getenv("TRUSTED_WORKER_IDS", "designer-laptop-01").split(",")
            if item.strip()
        }
        return cls(
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql+psycopg://creative:creative@localhost:5432/creative_workflow",
            ),
            server_public_base_url=os.getenv("SERVER_PUBLIC_BASE_URL", "http://127.0.0.1:8000"),
            artifact_root=Path(os.getenv("ARTIFACT_ROOT", "D:/creative-workflow/artifacts")),
            server_secret=os.getenv("SERVER_SECRET", ""),
            allow_worker_registration=os.getenv("ALLOW_WORKER_REGISTRATION", "false").lower()
            in {"1", "true", "yes"},
            trusted_worker_ids=trusted,
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "gemma3n:e2b"),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if len(self.server_secret) < 16:
            errors.append("SERVER_SECRET must be at least 16 characters for token hashing.")
        if not self.trusted_worker_ids and not self.allow_worker_registration:
            errors.append("Set TRUSTED_WORKER_IDS or enable ALLOW_WORKER_REGISTRATION.")
        local_llm_hosts = ("127.0.0.1", "localhost", "host.docker.internal")
        if not any(host in self.ollama_base_url for host in local_llm_hosts):
            errors.append("OLLAMA_BASE_URL must remain localhost-bound for MVP, or host.docker.internal inside Docker.")
        return errors
