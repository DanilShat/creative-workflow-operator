"""Asset upload/download contracts.

Workers never choose final server paths. They submit bytes and metadata, and the
server validates checksums before assigning a safe relative path under
ARTIFACT_ROOT.
"""

from pydantic import BaseModel, Field

from creative_workflow.shared.enums import AssetClass, DebugKind, RetentionClass, SourceService


class AssetUploadMetadata(BaseModel):
    task_id: str
    run_id: str | None = None
    job_id: str | None = None
    asset_class: AssetClass
    retention_class: RetentionClass
    original_filename: str
    content_type: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    source_service: SourceService
    debug_kind: DebugKind | None = None


class ReferenceUploadMetadata(BaseModel):
    original_filename: str
    content_type: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    source_service: SourceService = SourceService.MANUAL


class AssetUploadResponse(BaseModel):
    asset_id: str
    stored: bool
    sha256_verified: bool
    relative_path: str


class ReferenceUploadResponse(BaseModel):
    task_id: str
    asset_id: str
    asset_class: AssetClass
    retention_class: RetentionClass
    stored: bool


class JobInputAsset(BaseModel):
    asset_id: str
    download_url: str
    sha256: str
    content_type: str
    filename: str

