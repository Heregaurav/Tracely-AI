"""Inference router — raw CSV upload and stream-linked inference.

Routes:
    GET  /api/inference/context
    POST /api/inference/import
    GET  /api/inference/runs
    GET  /api/inference/runs/{run_id}
    POST /api/inference/alerts/{alert_id}/status
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.api.dependencies import (
    Settings,
    _get_factory,
    check_csrf,
    get_db,
    get_settings,
    require_role,
)
from src.api.schemas import InferenceAlertStatusRequest
from src.db.models import AuditLog, InferenceAlert, InferenceRun
from src.inference.raw import ACTIONS, InputError, MAX_BYTES, RAW_COLUMNS
from src.inference.service import context_info, import_csv

router = APIRouter(prefix="/api/inference", tags=["inference"])


def _inference_directory(settings: Settings) -> str:
    value = settings.inference_context_directory
    if not value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Verified raw-inference history has not been provisioned.",
        )
    return value



# ---------------------------------------------------------------------------
# GET /api/inference/context
# ---------------------------------------------------------------------------

@router.get("/context")
async def inference_context(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_role("ANALYST")),
):
    try:
        result = context_info(
            _get_factory(),
            _inference_directory(settings),
            settings.dataset_id,
        )
    except (InputError, OSError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        )
    return {
        **result,
        "required_columns": RAW_COLUMNS,
        "actions": {k: sorted(v) for k, v in ACTIONS.items()},
        "allow_test_fixtures": settings.allow_fixture_data,
        "max_bytes": MAX_BYTES,
        "max_events": 1000,
    }


# ---------------------------------------------------------------------------
# POST /api/inference/import
# ---------------------------------------------------------------------------

@router.post("/import", status_code=201)
async def upload_inference(
    request: Request,
    file: UploadFile = File(...),
    context_token: str = Form(...),
    coverage_start: str = Form(...),
    coverage_end: str = Form(...),
    complete_hours: str = Form(...),
    profile: str = Form(...),
    source_kind: str = Form(...),
    provenance: str = Form(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_role("ANALYST")),
    _csrf: None = Depends(check_csrf),
):
    """Accept and score a compatible SPEDIA-format CSV upload.

    File size is limited to MAX_BYTES. Form fields must match the inference
    context contract exactly. No training data is modified.
    """
    content = await file.read(MAX_BYTES + 1)
    form_settings = {
        "context_token": context_token,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "complete_hours": complete_hours,
        "profile": profile,
        "source_kind": source_kind,
        "provenance": provenance,
    }
    try:
        result = import_csv(
            _get_factory(),
            _inference_directory(settings),
            settings.dataset_id,
            content,
            form_settings,
            actor=actor,
            allow_fixture=settings.allow_fixture_data,
        )
    except InputError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        )
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Trusted model/context storage is unavailable.",
        )
    # Return 200 for reused runs, 201 for new ones (same as Flask)
    return result


# ---------------------------------------------------------------------------
# GET /api/inference/runs
# ---------------------------------------------------------------------------

@router.get("/runs")
async def list_runs(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_role("ANALYST")),
):
    rows = db.scalars(
        select(InferenceRun)
        .where(InferenceRun.dataset_id == settings.dataset_id)
        .order_by(InferenceRun.created_at.desc())
        .limit(50)
    )
    return {
        "runs": [
            {
                "run_id": r.id,
                "model_version": r.model_version,
                "coverage_start": r.coverage_start,
                "coverage_end": r.coverage_end,
                "source_kind": r.provenance["source_kind"],
                "windows": len(r.predictions),
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# GET /api/inference/runs/{run_id}
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_role("ANALYST")),
):
    row = db.get(InferenceRun, run_id)
    if row is None or row.dataset_id != settings.dataset_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Imported inference run not found.",
        )
    alerts = {
        a.id: a
        for a in db.scalars(
            select(InferenceAlert).where(InferenceAlert.run_id == run_id)
        )
    }
    predictions = [
        {
            **p,
            "alert_status": alerts[p["alert_id"]].status
            if p["alert_id"] in alerts
            else None,
            "alert_version": alerts[p["alert_id"]].version
            if p["alert_id"] in alerts
            else None,
        }
        for p in row.predictions
    ]
    return {
        "run_id": row.id,
        "model_version": row.model_version,
        "provenance": row.provenance,
        "coverage_start": row.coverage_start,
        "coverage_end": row.coverage_end,
        "predictions": predictions,
        "created_at": row.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# POST /api/inference/alerts/{alert_id}/status
# ---------------------------------------------------------------------------

@router.post("/alerts/{alert_id}/status")
async def update_inference_alert_status(
    alert_id: str,
    body: InferenceAlertStatusRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_role("ANALYST")),
    _csrf: None = Depends(check_csrf),
):
    alert = db.scalar(
        select(InferenceAlert)
        .join(InferenceRun, InferenceRun.id == InferenceAlert.run_id)
        .where(
            InferenceAlert.id == alert_id,
            InferenceRun.dataset_id == settings.dataset_id,
        )
    )
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Imported alert not found.",
        )
    old = alert.status
    changed = db.execute(
        update(InferenceAlert)
        .where(
            InferenceAlert.id == alert_id,
            InferenceAlert.version == body.version,
        )
        .values(status=body.status, version=body.version + 1)
    )
    if changed.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Alert changed; refresh its current version.",
        )
    db.add(
        AuditLog(
            actor=actor,
            action="inference.alert.status",
            target=alert_id,
            details={
                "from": old,
                "to": body.status,
                "version": body.version + 1,
            },
        )
    )
    db.commit()
    return {"status": "ok"}
