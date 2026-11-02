"""Additive hour-by-hour review of published scores and their existing alerts."""
from datetime import datetime, timedelta
import bisect

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.api.dependencies import get_active_model, get_db
from src.api.routers.overview import _alert_json, _bounded, _score_json
from src.db.models import Alert, DailyScore, ModelVersion
from src.models.scoring import TIERS

router = APIRouter(prefix="/api/hours", tags=["hourly monitor"])


def requested_hour(request):
    value = request.query_params.get("hour")
    if value is None:
        return None
    if not value.isascii() or not value.isdigit() or len(value) > 10:
        raise HTTPException(400, "hour must be a nonnegative integer window index")
    result = int(value)
    if result > 2_147_483_647:
        raise HTTPException(400, "hour is outside the supported window range")
    return result


def hour_metadata(model, index):
    start = datetime.fromisoformat(model.report["dataset"]["time_origin"]) + timedelta(hours=int(index))
    return {"window_index": int(index), "window_start": start.isoformat(sep=" "),
            "window_end": (start + timedelta(hours=1)).isoformat(sep=" ")}


def summarize_records(records):
    tiers = {tier: 0 for tier in TIERS}
    for row in records:
        tiers[row["risk_tier"]] += 1
    return {"observed_accounts": len(records), "tier_distribution": tiers,
            "flagged_accounts": tiers["HIGH"] + tiers["CRITICAL"],
            "average_risk": sum(row["risk_score"] for row in records) / len(records) if records else None,
            "peak_risk": max((row["risk_score"] for row in records), default=None),
            "observed_events": sum(int(row["explanation"].get("event_count", 0)) for row in records)}


@router.get("")
async def list_hours(request: Request, db: Session = Depends(get_db),
                     model: ModelVersion = Depends(get_active_model)):
    days = _bounded(request, "days", 90, 365)
    latest = db.scalar(select(func.max(DailyScore.relative_day)).where(DailyScore.model_version == model.id))
    hours = []
    if latest is not None:
        rows = db.execute(select(
            DailyScore.relative_day.label("window_index"),
            func.count(DailyScore.id).label("observed_accounts"),
            func.avg(DailyScore.risk_score).label("average_risk"),
            func.max(DailyScore.risk_score).label("peak_risk"),
            func.count(Alert.id).label("alerts"),
            func.sum(case((Alert.status.in_(["OPEN", "IN_PROGRESS"]), 1), else_=0)).label("open_alerts"),
        ).outerjoin(Alert, Alert.score_id == DailyScore.id).where(
            DailyScore.model_version == model.id,
            DailyScore.relative_day >= latest - days * 24 + 1,
        ).group_by(DailyScore.relative_day).order_by(DailyScore.relative_day)).mappings()
        thresholds = model.report["calibration"]["tier_thresholds"]
        hours = [{**dict(row), **hour_metadata(model, row["window_index"]),
                  "peak_tier": TIERS[bisect.bisect_right(thresholds, row["peak_risk"])]} for row in rows]
    return {"hours": hours, "latest_window_index": latest, "model_version": model.id,
            "model_name": model.report.get("display_name", model.id), "window_unit": "hour",
            "scope": "Published user-hour scores; raw-import runs remain in New Data Inference.",
            "time_basis": "Source wall-clock; timezone not supplied. Missing hours are unobserved, not normal."}


@router.get("/{window_index}")
async def hour_detail(window_index: int, db: Session = Depends(get_db),
                      model: ModelVersion = Depends(get_active_model)):
    if window_index < 0 or window_index > 2_147_483_647:
        raise HTTPException(400, "Invalid hour window index")
    rows = list(db.execute(select(DailyScore, Alert).outerjoin(Alert, Alert.score_id == DailyScore.id).where(
        DailyScore.model_version == model.id, DailyScore.relative_day == window_index,
    ).order_by(DailyScore.risk_score.desc(), DailyScore.user)).all())
    if not rows:
        raise HTTPException(404, "No stored observations for this hour; absence is not a normal-risk assessment")
    observations = []
    alerts = []
    for score, alert in rows:
        item = _score_json(score)
        item.update(window_index=score.relative_day, alert_id=alert.id if alert else None,
                    alert_status=alert.status if alert else None)
        observations.append(item)
        if alert:
            alerts.append(_alert_json(alert, score))
    return {**hour_metadata(model, window_index), "model_version": model.id,
            "model_name": model.report.get("display_name", model.id),
            **summarize_records(observations), "observations": observations, "alerts": alerts,
            "open_alerts": sum(alert["status"] in ("OPEN", "IN_PROGRESS") for alert in alerts),
            "alert_threshold": model.report["calibration"]["high_threshold"],
            "scope": "Each row is one account in this closed hour. Existing alerts are reused, not regenerated.",
            "time_basis": "Source wall-clock; timezone not supplied."}
