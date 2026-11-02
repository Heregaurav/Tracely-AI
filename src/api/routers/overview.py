"""Overview router — stats, timeline, metadata, model metrics, export.

Routes (all preserved from Flask service.py):
    GET /api/stats
    GET /api/timeline
    GET /api/graph
    GET /api/departments   (returns empty — no SPEDIA dept metadata)
    GET /api/heatmap       (returns empty — no SPEDIA dept metadata)
    GET /api/model-metrics
    GET /api/data-sources
    GET /api/export
"""
from __future__ import annotations

import bisect
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.db.models import (
    Alert, AuditLog, DailyBehavior, DailyScore, Dataset, ModelVersion,
    Relationship, now,
)
from src.models.scoring import TIERS
from src.api.dependencies import (
    Settings,
    get_active_model,
    get_db,
    get_settings,
    get_actor,
)

router = APIRouter(prefix="/api", tags=["overview"])


# ---------------------------------------------------------------------------
# Shared helpers (ported exactly from service.py closures)
# ---------------------------------------------------------------------------

def _thresholds(model: ModelVersion) -> list:
    return model.report.get("calibration", {}).get("tier_thresholds", [40, 70, 85, 95])


def _windows_per_day(model: ModelVersion) -> int:
    return model.report.get("contract", {}).get("windows_per_day", 24)


def _observation_scope(_model: ModelVersion) -> str:
    return "Closed user-hours from controlled hybrid research data; timestamps have no supplied timezone."


def _rollups(model: ModelVersion, db: Session):
    """Subquery: per-user risk rollup over the last 30 data days."""
    wpd = _windows_per_day(model)
    latest = (
        select(func.max(DailyScore.relative_day))
        .where(DailyScore.model_version == model.id)
        .scalar_subquery()
    )
    return (
        select(
            DailyScore.user,
            func.max(DailyScore.risk_score).label("max_risk_score"),
            func.avg(DailyScore.risk_score).label("avg_risk_score"),
            func.max(
                DailyScore.components["graph_score"].as_float()
            ).label("graph_score"),
            func.count().label("total_days_active"),
            func.max(DailyScore.relative_day).label("latest_day"),
            func.sum(
                case((DailyScore.risk_tier.in_(["HIGH", "CRITICAL"]), 1), else_=0)
            ).label("high_risk_days"),
        )
        .where(
            DailyScore.model_version == model.id,
            DailyScore.relative_day >= latest - 30 * wpd + 1,
        )
        .group_by(DailyScore.user)
        .subquery()
    )


def _bounded(request: Request, name: str, default: int, maximum: int) -> int:
    try:
        value = int(request.query_params.get(name, default))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} must be an integer",
        )
    if value < 1 or value > maximum:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{name} must be between 1 and {maximum}",
        )
    return value


def _pagination(request: Request, default: int = 50):
    return (
        _bounded(request, "page", 1, 100_000),
        _bounded(request, "limit", default, 500),
    )


def _score_json(row: DailyScore) -> dict:
    behavior = row.explanation
    return {
        "user": row.user,
        "relative_day": row.relative_day,
        "day": behavior.get("window_start"),
        "window_start": behavior.get("window_start"),
        "window_unit": behavior.get("window_unit", "hour"),
        "risk_score": row.risk_score,
        "risk_tier": row.risk_tier,
        **row.components,
        "ae_score": row.components.get(
            "neural_score", row.components.get("pca_score")
        ),
        "explanation": behavior,
        "model_version": row.model_version,
    }


def _alert_json(alert: Alert, score: DailyScore) -> dict:
    return {
        "alert_id": alert.id,
        "user_id": score.user,
        "risk_score": score.risk_score,
        "risk_tier": alert.severity,
        "status": alert.status,
        "version": alert.version,
        **score.components,
        "ae_score": score.components.get(
            "neural_score", score.components.get("pca_score")
        ),
        "alert_type": "HOUR_ANOMALY",
        "relative_day": score.relative_day,
        "timestamp": score.explanation.get("window_start"),
        "created_at": alert.created_at.isoformat(),
        "message": "Unusual observed behavior; inspect evidence before drawing conclusions.",
        "explanation": score.explanation,
        "department": None,
    }


def _user_json(row: dict, model: ModelVersion) -> dict:
    item = dict(row)
    value = item["max_risk_score"]
    item.update(
        account_id=item["user"],
        display_name=None,
        name=None,
        department=None,
        role=None,
        risk_tier=TIERS[bisect.bisect_right(_thresholds(model), value)],
        trend="unavailable",
        avg_risk_score=float(item["avg_risk_score"]),
    )
    return item


# ---------------------------------------------------------------------------
# GET /api/stats
# ---------------------------------------------------------------------------

@router.get("/stats")
async def stats(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    model: ModelVersion = Depends(get_active_model),
    actor: str = Depends(get_actor),
):
    users = _rollups(model, db)
    total = db.scalar(select(func.count()).select_from(users))
    edges = [0, *_thresholds(model), 101]
    boundaries = list(
        zip(["NORMAL", "LOW", "MEDIUM", "HIGH", "CRITICAL"], edges, edges[1:])
    )
    tier_counts = db.execute(
        select(
            *[
                func.sum(
                    case(
                        (
                            (users.c.max_risk_score >= low)
                            & (users.c.max_risk_score < high),
                            1,
                        ),
                        else_=0,
                    )
                )
                for name, low, high in boundaries
            ]
        )
    ).one()
    tiers = {
        name: int(value or 0)
        for (name, low, high), value in zip(boundaries, tier_counts)
    }
    open_alerts = db.scalar(
        select(func.count())
        .select_from(Alert)
        .join(DailyScore, Alert.score_id == DailyScore.id)
        .where(
            DailyScore.model_version == model.id,
            Alert.status.in_(["OPEN", "IN_PROGRESS"]),
        )
    )
    observed = model.report["dataset"].get("analyzed_event_count", 0)
    latest_hour = db.scalar(select(func.max(DailyScore.relative_day)).where(DailyScore.model_version == model.id))
    hourly_rows = db.execute(select(DailyScore.risk_tier, func.count()).where(
        DailyScore.model_version == model.id,
        DailyScore.relative_day >= (latest_hour or 0) - 30 * _windows_per_day(model) + 1,
    ).group_by(DailyScore.risk_tier)).all()
    hourly_tiers = {tier: 0 for tier in TIERS}
    hourly_tiers.update({tier: int(count) for tier, count in hourly_rows})
    return {
        "total_users": total,
        "critical_users": tiers["CRITICAL"],
        "high_risk_users": tiers["HIGH"],
        "open_alerts": open_alerts,
        "tier_distribution": tiers,
        "hourly_tier_distribution": hourly_tiers,
        "hourly_observations": sum(hourly_tiers.values()),
        "user_tier_basis": "Highest observed hourly risk per user over the last 30 data days",
        "hourly_tier_basis": "Each observed user-hour counted once over the last 30 data days",
        "model_name": model.report.get("display_name", model.id),
        "avg_risk_score": float(
            db.scalar(select(func.avg(users.c.avg_risk_score))) or 0
        ),
        "risk_trend_pct": None,
        "observed_event_volume": int(observed),
        "dataset_id": model.dataset_id,
        "model_version": model.id,
        "relative_time": model.report.get("relative_time", False),
        "window_unit": model.report.get("window_unit", "hour"),
        "is_fixture": model.report["is_fixture"],
        "observation_scope": _observation_scope(model),
        "last_updated": now().isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /api/timeline
# ---------------------------------------------------------------------------

@router.get("/timeline")
async def timeline(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    model: ModelVersion = Depends(get_active_model),
    actor: str = Depends(get_actor),
):
    days = _bounded(request, "days", 60, 365)
    wpd = _windows_per_day(model)
    last = (
        db.scalar(
            select(func.max(DailyScore.relative_day)).where(
                DailyScore.model_version == model.id
            )
        )
        or 0
    )
    query = select(
        DailyScore.relative_day.label("relative_day"),
        func.avg(DailyScore.risk_score).label("risk_score_avg"),
        func.max(DailyScore.risk_score).label("risk_score_max"),
        func.sum(
            case((DailyScore.risk_tier.in_(["HIGH", "CRITICAL"]), 1), else_=0)
        ).label("n_anomalies"),
    ).where(
        DailyScore.model_version == model.id,
        DailyScore.relative_day >= last - days * wpd + 1,
    )

    user_id = request.query_params.get("user_id")
    if user_id:
        query = query.where(DailyScore.user == user_id)

    rows = [
        dict(r)
        for r in db.execute(
            query.group_by(DailyScore.relative_day).order_by(
                DailyScore.relative_day
            )
        ).mappings()
    ]

    origin = datetime.fromisoformat(model.report["dataset"]["time_origin"])
    for row in rows:
        row["day"] = (origin + timedelta(hours=row["relative_day"])).isoformat(
            sep=" "
        )
        row["window_start"] = row["day"]

    return {
        "timeline": rows,
        "relative_time": model.report.get("relative_time", False),
        "window_unit": model.report.get("window_unit", "hour"),
        "tier_thresholds": _thresholds(model),
    }


# ---------------------------------------------------------------------------
# GET /api/graph
# ---------------------------------------------------------------------------

@router.get("/graph")
async def graph(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    model: ModelVersion = Depends(get_active_model),
    actor: str = Depends(get_actor),
):
    user = request.query_params.get("user_id", "").strip()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="user_id required"
        )
    limit = _bounded(request, "limit", 30, 100)
    max_day = (
        db.scalar(
            select(func.max(DailyScore.relative_day)).where(
                DailyScore.model_version == model.id
            )
        )
        or 0
    )
    try:
        cutoff = int(request.query_params.get("relative_day", max_day))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="relative_day must be integer",
        )
    if cutoff < 0 or cutoff > max_day:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="relative_day outside active scoring range",
        )

    table = Relationship
    query = (
        select(
            table.destination_computer,
            func.sum(table.weight).label("weight"),
        )
        .where(
            table.dataset_id == model.dataset_id,
            table.user == user,
            table.relative_day <= cutoff,
        )
        .group_by(table.destination_computer)
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = list(
        db.execute(
            query.order_by(
                func.sum(table.weight).desc(), table.destination_computer
            ).limit(limit)
        )
    )
    nodes = [
        {
            "id": "user_" + user,
            "type": "user",
            "label": user,
            "key": user,
            "connections": total,
        }
    ]
    edges = []
    for destination, weight in rows:
        node = "computer_" + destination
        nodes.append(
            {
                "id": node,
                "type": "device",
                "label": destination,
                "key": destination,
                "connections": 1,
            }
        )
        edges.append(
            {
                "source": "user_" + user,
                "target": node,
                "type": "observed_on_host",
                "weight": int(weight),
            }
        )
    return {
        "nodes": nodes if total else [],
        "edges": edges,
        "total_edges": total,
        "returned_edges": len(edges),
        "graph_connections_count": total,
        "relative_day": cutoff,
        "truncated": total > len(edges),
    }


# ---------------------------------------------------------------------------
# GET /api/departments  and  GET /api/heatmap  (no SPEDIA dept metadata)
# ---------------------------------------------------------------------------

@router.get("/departments")
@router.get("/heatmap")
async def unavailable_metadata(
    actor: str = Depends(get_actor),
):
    return {
        "departments": [],
        "heatmap": [],
        "reason": "Source has no verified department metadata",
    }


# ---------------------------------------------------------------------------
# GET /api/model-metrics
# ---------------------------------------------------------------------------

@router.get("/model-metrics")
async def model_metrics(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    model: ModelVersion = Depends(get_active_model),
    actor: str = Depends(get_actor),
):
    keys = (
        "version", "created_at", "is_fixture", "evaluation_scope",
        "active_configuration", "weights", "models", "parameters", "contract",
        "split_policy", "splits", "scaling", "calibration", "selection_policy",
        "validation_metrics", "held_out_metrics", "benchmark", "limitations",
        "primary_evaluation", "primary_metrics", "display_name", "fusion",
    )
    return {
        key: model.report.get(key)
        for key in (*keys, "window_unit", "relative_time", "external_evaluation")
    }


# ---------------------------------------------------------------------------
# GET /api/data-sources
# ---------------------------------------------------------------------------

@router.get("/data-sources")
async def data_sources(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    model: ModelVersion = Depends(get_active_model),
    actor: str = Depends(get_actor),
):
    dataset = db.get(Dataset, model.dataset_id)
    labels = model.report["dataset"].get("labels", {})
    return {
        "dataset_id": dataset.id,
        "is_fixture": dataset.is_fixture,
        "source_url": dataset.provenance.get("source_url"),
        "sha256": dataset.provenance.get("sha256"),
        "authenticity": dataset.provenance.get("authenticity"),
        "actual_download_url": dataset.provenance.get("actual_download_url"),
        "upstream_selection": dataset.provenance.get("derivation"),
        "observation_scope": _observation_scope(model),
        "label_reconciliation": labels,
        "selection_policy": model.report["dataset"]["selection_policy"],
        "limitations": "Controlled mixed-origin annotations; indirect source confounding remains.",
    }


# ---------------------------------------------------------------------------
# GET /api/export
# ---------------------------------------------------------------------------

@router.get("/export")
async def export(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    model: ModelVersion = Depends(get_active_model),
    actor: str = Depends(get_actor),
):
    limit = _bounded(request, "limit", 100, 500)
    kind = request.query_params.get("kind", "scores")

    scores_q = select(DailyScore).where(DailyScore.model_version == model.id)

    if kind == "scores":
        data = [
            _score_json(s)
            for s in db.scalars(
                scores_q.order_by(
                    DailyScore.risk_score.desc(), DailyScore.id
                ).limit(limit)
            )
        ]
    elif kind == "alerts":
        data = [
            _alert_json(a, s)
            for a, s in db.execute(
                select(Alert, DailyScore)
                .join(DailyScore, Alert.score_id == DailyScore.id)
                .where(DailyScore.model_version == model.id)
                .order_by(DailyScore.risk_score.desc(), Alert.id)
                .limit(limit)
            )
        ]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported export kind",
        )

    db.add(
        AuditLog(
            actor=actor,
            action=kind + ".export",
            target=model.id,
            details={"returned": len(data)},
        )
    )
    db.commit()
    return {"records": data, "model_version": model.id, "limit": limit, "truncated": True}
