"""Health router — liveness and readiness probes.

Routes:
    GET /health/live   — simple liveness probe (always 200)
    GET /health        — alias for /health/ready
    GET /health/ready  — checks DB, active model, and artifact file
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.data.neon_assets import resolve_asset_path
from src.db.models import DailyScore, ModelVersion
from src.api.dependencies import Settings, get_db, get_settings

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live():
    """Liveness probe — always succeeds while the process is running."""
    return {"status": "ok", "supported_feature_versions": ["spedia-hour-v1", "spedia-behavioral-v6"]}


@router.get("/health")
@router.get("/health/ready")
async def ready(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Readiness probe — verifies DB connectivity, active model, and artifact file."""
    try:
        db.execute(text("SELECT 1"))
        model = db.scalar(
            select(ModelVersion).where(
                ModelVersion.dataset_id == settings.dataset_id,
                ModelVersion.active,
            )
        )
        if model is None:
            return JSONResponse(
                {"status": "not_ready", "error": "No active model registered"},
                status_code=503,
            )

        if model.report.get("is_fixture") and not settings.allow_fixture_data:
            return JSONResponse(
                {"status": "not_ready", "error": "No permitted active dataset/model"},
                status_code=503,
            )

        has_scores = db.scalar(
            select(DailyScore.id)
            .where(DailyScore.model_version == model.id)
            .limit(1)
        )
        artifact = resolve_asset_path(model.artifact_path) / "model.joblib"
        if not has_scores or not artifact.is_file():
            return JSONResponse(
                {
                    "status": "not_ready",
                    "error": "Active scores or durable model artifact unavailable",
                },
                status_code=503,
            )

        return {"status": "ok", "data_loaded": True, "model_version": model.id}

    except SQLAlchemyError:
        return JSONResponse(
            {
                "status": "not_ready",
                "error": "Database unavailable or migrations missing",
            },
            status_code=503,
        )
