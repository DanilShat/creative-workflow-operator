"""Server-side artifact storage.

This service is the only component that chooses final artifact paths. It
normalizes filenames, verifies checksums, and keeps binary files out of
PostgreSQL.
"""

from pathlib import Path
import hashlib
import re

from sqlalchemy.orm import Session

from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.models import Asset
from creative_workflow.shared.contracts.assets import AssetUploadMetadata, ReferenceUploadMetadata
from creative_workflow.shared.enums import AssetClass, RetentionClass, SourceService
from creative_workflow.shared.ids import new_id


SAFE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".txt",
    ".json",
    ".zip",
    ".html",
    ".mp4",
    ".mov",
    ".psd",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sanitize_filename(filename: str) -> str:
    name = Path(filename).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or "upload.bin"


def safe_extension(filename: str, content_type: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in SAFE_EXTENSIONS:
        return ext
    if content_type == "image/png":
        return ".png"
    if content_type in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if content_type == "text/plain":
        return ".txt"
    if content_type == "application/json":
        return ".json"
    return ".bin"


class ArtifactService:
    def __init__(self, db: Session, settings: ServerSettings):
        self.db = db
        self.settings = settings

    def store_upload(self, metadata: AssetUploadMetadata, data: bytes) -> Asset:
        actual = sha256_bytes(data)
        if actual.lower() != metadata.sha256.lower():
            raise ValueError("sha256 mismatch")
        asset_id = new_id("asset")
        sanitized = sanitize_filename(metadata.original_filename)
        ext = safe_extension(sanitized, metadata.content_type)
        stored_filename = f"{asset_id}{ext}"
        relative = Path("tasks") / metadata.task_id / metadata.asset_class.value / stored_filename
        self._write(relative, data)
        asset = Asset(
            asset_id=asset_id,
            task_id=metadata.task_id,
            run_id=metadata.run_id,
            job_id=metadata.job_id,
            asset_class=metadata.asset_class.value,
            retention_class=metadata.retention_class.value,
            original_filename=sanitized,
            stored_filename=stored_filename,
            relative_path=relative.as_posix(),
            content_type=metadata.content_type,
            size_bytes=len(data),
            sha256=actual,
            source_service=metadata.source_service.value,
            debug_kind=metadata.debug_kind.value if metadata.debug_kind else None,
        )
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def store_reference(self, task_id: str, metadata: ReferenceUploadMetadata, data: bytes) -> Asset:
        upload = AssetUploadMetadata(
            task_id=task_id,
            run_id=None,
            job_id=None,
            asset_class=AssetClass.REFERENCE,
            retention_class=RetentionClass.KEEP,
            original_filename=metadata.original_filename,
            content_type=metadata.content_type,
            size_bytes=metadata.size_bytes,
            sha256=metadata.sha256,
            source_service=SourceService.MANUAL,
            debug_kind=None,
        )
        return self.store_upload(upload, data)

    def read_asset(self, asset: Asset) -> bytes:
        path = self._absolute_path(asset.relative_path)
        return path.read_bytes()

    def _write(self, relative: Path, data: bytes) -> None:
        path = self._absolute_path(relative.as_posix())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _absolute_path(self, relative_path: str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe relative path in asset metadata")
        root = self.settings.artifact_root.resolve()
        resolved = (root / relative).resolve()
        if root not in resolved.parents and resolved != root:
            raise ValueError("asset path escaped artifact root")
        return resolved

