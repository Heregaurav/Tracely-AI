"""Models router — version management and activation.

Routes:
    GET  /api/model-versions
    POST /api/model-versions/{version}/activate
    POST /api/retrain              (returns 409 — frozen model policy)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from src.data.integrity import sha256_file
from src.data.neon_assets import resolve_asset_path
from src.db.models import AuditLog, ModelVersion
from src.api.dependencies import (
    Settings,
    get_db,
    get_settings,
    get_actor,
)
from src.api.routers.overview import _bounded, _pagination

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/model-versions")
async def list_model_versions(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(get_actor),
):
    """List all model versions for the active dataset."""
    page, limit = _pagination(request)
    rows = db.scalars(
        select(ModelVersion)
        .where(ModelVersion.dataset_id == settings.dataset_id)
        .order_by(ModelVersion.created_at.desc())
        .limit(limit)
        .offset((page - 1) * limit)
    )
    return {
        "versions": [
            {
                "id": m.id,
                "active": m.active,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ]
    }


@router.post("/model-versions/{version}/activate")
async def activate_model(
    version: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(get_actor),
):
    """Activate a specific model version.

    Validates:
    - Version exists and belongs to the active dataset.
    - Feature contract is spedia-hour-v1.
    - Fixture flag matches deployment policy.
    - Artifact file is present and checksum matches.
    Uses a PostgreSQL advisory lock to serialise activation per dataset.
    """
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:dataset))"),
        {"dataset": settings.dataset_id},
    )
    model = db.get(ModelVersion, version)
    if not model or model.dataset_id != settings.dataset_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model version not found",
        )
    if model.feature_version != "spedia-hour-v1":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Model is incompatible with the supported feature contract",
        )
    if model.report.get("is_fixture") and not settings.allow_fixture_data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fixture activation is disabled in this deployment",
        )
    artifact = resolve_asset_path(model.artifact_path) / "model.joblib"
    if not artifact.is_file() or sha256_file(artifact) != model.artifact_sha256:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Artifact missing or checksum invalid",
        )

    db.execute(
        update(ModelVersion)
        .where(ModelVersion.dataset_id == model.dataset_id)
        .values(active=False)
    )
    db.execute(
        update(ModelVersion).where(ModelVersion.id == version).values(active=True)
    )
    db.add(
        AuditLog(
            actor=actor,
            action="model.activate",
            target=version,
            details={},
        )
    )
    db.commit()
    return {"status": "ok", "version": version}


@router.post("/retrain")
async def retrain(
    actor: str = Depends(get_actor),
):
    """Always returns 409 — the approved SPEDIA model is frozen.

    Use explicit offline research scripts to train new model candidates;
    runtime API retraining is intentionally disabled to protect evaluation
    integrity.
    """
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "This approved model is frozen. Use an explicit offline study with "
            "an untouched evaluation set; runtime retraining is unavailable."
        ),
    )
