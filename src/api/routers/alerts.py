"""Alerts router — threat list and status updates.

Routes:
    GET  /api/threats
    POST /api/threats/{alert_id}/status
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from src.db.models import Alert, AlertEvent, AuditLog, DailyScore, ModelVersion, now
from src.api.dependencies import (
    Settings,
    get_active_model,
    get_db,
    get_settings,
    get_actor,
)
from src.api.routers.overview import _alert_json, _bounded, _pagination
from src.api.schemas import AlertStatusRequest
from src.api.routers.hours import requested_hour

router = APIRouter(prefix="/api", tags=["alerts"])

_VALID_SORTS = {"risk", "time"}


@router.get("/threats")
async def list_threats(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    model: ModelVersion = Depends(get_active_model),
    actor: str = Depends(get_actor),
):
    """Paginated, filterable list of analyst-visible alerts."""
    page, limit = _pagination(request)
    query = (
        select(Alert, DailyScore)
        .join(DailyScore, Alert.score_id == DailyScore.id)
        .where(DailyScore.model_version == model.id)
    )
    hour = requested_hour(request)
    if hour is not None:
        query = query.where(DailyScore.relative_day == hour)

    for arg, column in (
        ("tier", Alert.severity),
        ("status", Alert.status),
        ("user_id", DailyScore.user),
    ):
        if request.query_params.get(arg):
            query = query.where(column == request.query_params[arg])

    sort = request.query_params.get("sort", "risk")
    if sort not in _VALID_SORTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sort must be risk or time",
        )
    order_col = DailyScore.risk_score if sort == "risk" else DailyScore.relative_day
    query = query.order_by(order_col.desc(), Alert.id)

    total = db.scalar(
        select(func.count()).select_from(query.order_by(None).subquery())
    )
    rows = db.execute(query.limit(limit).offset((page - 1) * limit))
    return {
        "alerts": [_alert_json(a, s) for a, s in rows],
        "total": total,
        "page": page,
        "limit": limit,
        "window_index": hour,
    }


@router.post("/threats/{alert_id}/status")
async def update_threat_status(
    alert_id: str,
    body: AlertStatusRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    model: ModelVersion = Depends(get_active_model),
    actor: str = Depends(get_actor),
):
    """Optimistic-concurrency alert status update with full audit trail."""
    row = db.execute(
        select(Alert, DailyScore)
        .join(DailyScore, Alert.score_id == DailyScore.id)
        .where(
            Alert.id == alert_id,
            DailyScore.model_version == model.id,
        )
    ).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found"
        )
    alert, score = row
    old = alert.status

    changed = db.execute(
        update(Alert)
        .where(Alert.id == alert_id, Alert.version == body.version)
        .values(
            status=body.status,
            version=body.version + 1,
            resolved_at=now() if body.status == "RESOLVED" else None,
        )
    )
    if changed.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Alert changed; refresh and retry with its current version",
        )

    db.add(
        AlertEvent(
            alert_id=alert_id,
            actor=actor,
            previous_status=old,
            status=body.status,
        )
    )
    db.add(
        AuditLog(
            actor=actor,
            action="alert.status",
            target=alert_id,
            details={"from": old, "to": body.status, "version": body.version + 1},
        )
    )
    db.commit()
    db.refresh(alert)
    return {"status": "ok", "alert": _alert_json(alert, score)}
