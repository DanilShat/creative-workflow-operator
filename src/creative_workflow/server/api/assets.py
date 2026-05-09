"""Asset upload/download endpoints for workers and task references."""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from creative_workflow.server.api.deps import bearer_token, get_settings, validate_any_worker_token
from creative_workflow.server.config import ServerSettings
from creative_workflow.server.db.models import Asset
from creative_workflow.server.db.session import get_db
from creative_workflow.server.services.artifacts import ArtifactService
from creative_workflow.shared.contracts.assets import AssetUploadMetadata, AssetUploadResponse

router = APIRouter(prefix="/api/v1/assets", tags=["assets"])


@router.post("/upload", response_model=AssetUploadResponse)
async def upload_asset(
    file: UploadFile = File(...),
    metadata: str = Form(...),
    token: str = Depends(bearer_token),
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    validate_any_worker_token(token, db, settings)
    try:
        parsed = AssetUploadMetadata.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail={"code": "validation_error", "message": str(exc)}) from exc
    data = await file.read()
    try:
        asset = ArtifactService(db, settings).store_upload(parsed, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "validation_error", "message": str(exc)}) from exc
    return AssetUploadResponse(
        asset_id=asset.asset_id,
        stored=True,
        sha256_verified=True,
        relative_path=asset.relative_path,
    )


@router.get("/{asset_id}/download")
def download_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    settings: ServerSettings = Depends(get_settings),
):
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "asset not found"})
    data = ArtifactService(db, settings).read_asset(asset)
    return Response(
        content=data,
        media_type=asset.content_type,
        headers={"Content-Disposition": f'attachment; filename="{asset.original_filename}"'},
    )
