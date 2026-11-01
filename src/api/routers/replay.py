"""Replay router — frozen SPEDIA analysis and chronological replay.

Routes:
    GET  /api/replay
    POST /api/replay/detect
    GET  /api/replay/runs/{run_id}
    GET  /api/replay/runs/{run_id}/events
    GET  /api/replay/runs/{run_id}/ground-truth
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import sessionmaker
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.dependencies import (
    Settings,
    _get_factory,
    check_csrf,
    get_db,
    get_settings,
    require_role,
)
from src.api.schemas import ReplayDetectRequest
from src.data.integrity import sha256_file
from src.db.models import Alert, AuditLog, ModelVersion, ReplayRun
from src.db.replay import execute_replay, load_replay

router = APIRouter(prefix="/api/replay", tags=["replay"])


# ---------------------------------------------------------------------------
# Internal helpers (ported from register_replay)
# ---------------------------------------------------------------------------

def _replay_root(mode: str, settings: Settings) -> Path:
    if mode not in ("analysis", "realistic"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown replay mode"
        )
    directory = settings.replay_directory
    if mode == "realistic":
        directory = settings.realistic_replay_directory or (
            str(Path(directory).parent / "replay-realistic-v1") if directory else None
        )
    if not directory or not (Path(directory) / "replay_manifest.json").is_file():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No verified replay dataset configured",
        )
    return Path(directory)


def _run_root(row: ReplayRun, settings: Settings):
    """Identify which replay directory a persisted run came from."""
    for mode in ("analysis", "realistic"):
        try:
            directory = _replay_root(mode, settings)
        except HTTPException:
            continue
        try:
            manifest, frame = load_replay(directory)
        except (ValueError, OSError):
            continue
        if (
            manifest["inputs_sha256"] == row.inputs_sha256
            and manifest["model_version"] == row.model_version
        ):
            return directory, manifest, frame, mode
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="Replay input version mismatch"
    )


# ---------------------------------------------------------------------------
# GET /api/replay
# ---------------------------------------------------------------------------

@router.get("")
async def replay_info(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_role("ANALYST")),
):
    mode = request.query_params.get("mode", "analysis")
    try:
        manifest, frame = load_replay(_replay_root(mode, settings))
    except (ValueError, OSError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Replay integrity check failed",
        )
    model = db.get(ModelVersion, manifest["model_version"])
    if model is None or model.dataset_id != settings.dataset_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Matching replay model is not published in this dataset",
        )
    threshold = model.report["calibration"]["high_threshold"]
    return {
        "mode": mode,
        "model_version": manifest["model_version"],
        "threshold": threshold,
        "events": manifest["events"],
        "windows": manifest["windows"],
        "selection": manifest["selection"],
        "history": manifest["history"],
    }


# ---------------------------------------------------------------------------
# POST /api/replay/detect
# ---------------------------------------------------------------------------

@router.post("/detect")
async def detect(
    body: ReplayDetectRequest,
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_role("ANALYST")),
    _csrf: None = Depends(check_csrf),
):
    try:
        result = execute_replay(
            _get_factory(),
            _replay_root(body.mode, settings),
            actor=actor,
            dataset_id=settings.dataset_id,
        )
    except (ValueError, OSError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Replay unavailable or integrity check failed; inspect configured artifacts",
        )
    return result


# ---------------------------------------------------------------------------
# GET /api/replay/runs/{run_id}
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}")
async def replay_run(
    run_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_role("ANALYST")),
):
    row = db.get(ReplayRun, run_id)
    if row is None or row.dataset_id != settings.dataset_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Replay run not found"
        )
    _, _, _, mode = _run_root(row, settings)
    predictions = [dict(p) for p in row.predictions]
    ids = [p["alert_id"] for p in predictions if p["alert_id"]]
    alerts = (
        {a.id: a for a in db.scalars(select(Alert).where(Alert.id.in_(ids)))}
        if ids
        else {}
    )
    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "replay.detect", AuditLog.target == run_id
        )
    )
    for p in predictions:
        alert = alerts.get(p["alert_id"])
        p["alert_status"] = alert.status if alert else None
        p["alert_version"] = alert.version if alert else None
    return {
        "run_id": row.id,
        "mode": mode,
        "model_version": row.model_version,
        "predictions": predictions,
        "created_at": row.created_at.isoformat(),
        "timings": audit.details.get("timings", {}) if audit else {},
    }


# ---------------------------------------------------------------------------
# GET /api/replay/runs/{run_id}/events
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/events")
async def replay_events(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_role("ANALYST")),
):
    row = db.get(ReplayRun, run_id)
    if row is None or row.dataset_id != settings.dataset_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Replay run not found"
        )
    permitted = {p["window_id"] for p in row.predictions}
    directory, manifest, inputs, mode = _run_root(row, settings)

    window = request.query_params.get("window_id")
    if window is not None and window not in permitted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Replay window not found"
        )

    events = pd.read_parquet(directory / "replay_events.parquet").sort_values(
        ["time", "source_record_id"]
    )
    if window is not None:
        selected = inputs.loc[inputs.window_id == window].iloc[0]
        events = events.loc[events.source_record_id.isin(selected.record_ids)]
        return {
            "events": json.loads(
                events.to_json(orient="records", date_format="iso")
            )
        }

    try:
        offset = int(request.query_params.get("offset", 0))
        limit = int(request.query_params.get("limit", 200))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination"
        )
    if offset < 0 or not 1 <= limit <= 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination"
        )
    total = len(events)
    events = events.iloc[offset : offset + limit]
    return {
        "events": json.loads(events.to_json(orient="records", date_format="iso")),
        "total": total,
        "next_offset": offset + len(events) if offset + len(events) < total else None,
    }


# ---------------------------------------------------------------------------
# GET /api/replay/runs/{run_id}/ground-truth
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/ground-truth")
async def ground_truth(
    run_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(require_role("ANALYST")),
):
    row = db.get(ReplayRun, run_id)
    if row is None or row.dataset_id != settings.dataset_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Replay run not found"
        )
    directory, manifest, _, mode = _run_root(row, settings)
    file = directory / "replay_ground_truth.json"
    if sha256_file(file) != manifest["ground_truth_sha256"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ground-truth manifest mismatch",
        )
    windows = json.loads(file.read_text())["windows"]
    predictions = {p["window_id"]: p for p in row.predictions}
    for w in windows:
        p = predictions[w["window_id"]]
        w["example_outcome"] = (
            ("TP" if w["label"] else "FP")
            if p["prediction"]
            else ("FN" if w["label"] else "TN")
        )
        if w["example_outcome"] == "FN":
            w["miss_explanation"] = (
                f"Score {p['risk_score']:.2f} remained below the frozen threshold. "
                f"{p['events']} observed events; host novelty component "
                f"{p['components'].get('graph', 0):.2f}. "
                "The annotation marks an attack, but aggregated behavior did not "
                "trigger this model. These comparisons do not establish a causal "
                "attribution."
            )
    return {
        "windows": windows,
        "warning": (
            "Outcome-selected examples; this is not a performance evaluation sample."
            if mode == "analysis"
            else "Complete retained historical test replay; already evaluated, never a new independent test or live traffic."
        ),
    }
