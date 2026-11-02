"""Users router — paginated user list and individual user dossier.

Routes:
    GET /api/users
    GET /api/users/{user_id}
"""
from __future__ import annotations

import bisect

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from src.db.models import Alert, AuditLog, DailyBehavior, DailyScore, ModelVersion, Relationship
from src.models.scoring import TIERS
from src.api.dependencies import (
    Settings,
    get_active_model,
    get_db,
    get_settings,
    get_actor,
)
from src.api.routers.overview import (
    _alert_json,
    _bounded,
    _observation_scope,
    _pagination,
    _rollups,
    _score_json,
    _thresholds,
    _user_json,
)

router = APIRouter(prefix="/api", tags=["users"])

_VALID_USER_SORTS = frozenset({
    "max_risk_score", "avg_risk_score", "user", "latest_day",
    "high_risk_days", "total_days_active", "graph_score",
})


@router.get("/users")
async def list_users(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    model: ModelVersion = Depends(get_active_model),
    actor: str = Depends(get_actor),
):
    """Paginated, sortable list of users with risk rollup over last 30 data days."""
    page, limit = _pagination(request, 100)
    table = _rollups(model, db)
    query = select(table)

    tier = request.query_params.get("tier")
    if tier:
        if tier not in TIERS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tier"
            )
        i = TIERS.index(tier)
        thres = _thresholds(model)
        if i:
            query = query.where(table.c.max_risk_score >= thres[i - 1])
        if i < 4:
            query = query.where(table.c.max_risk_score < thres[i])

    sort_name = request.query_params.get("sort", "max_risk_score")
    if sort_name not in _VALID_USER_SORTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user sort"
        )
    column = table.c[sort_name]
    order_asc = request.query_params.get("order") == "asc"
    query = query.order_by(
        column.asc() if order_asc else column.desc(), table.c.user
    )

    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    records = [
        _user_json(r, model)
        for r in db.execute(
            query.limit(limit).offset((page - 1) * limit)
        ).mappings()
    ]

    # Attach graph connection counts per user
    for item in records:
        item["graph_connections_count"] = db.scalar(
            select(
                func.count(func.distinct(Relationship.destination_computer))
            ).where(
                Relationship.dataset_id == model.dataset_id,
                Relationship.user == item["user"],
                Relationship.relative_day <= item["latest_day"],
            )
        )

    return {"users": records, "total": total, "page": page, "limit": limit}


@router.get("/users/{user_id}")
async def user_dossier(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    model: ModelVersion = Depends(get_active_model),
    actor: str = Depends(get_actor),
):
    """Full behavioral dossier for a single user including daily history and alerts."""
    table = _rollups(model, db)
    row = db.execute(
        select(table).where(table.c.user == user_id)
    ).mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    result = _user_json(row, model)

    # Daily score history (up to 365 windows, oldest first)
    history = list(
        db.scalars(
            select(DailyScore)
            .where(
                DailyScore.model_version == model.id,
                DailyScore.user == user_id,
            )
            .order_by(DailyScore.relative_day.desc())
            .limit(365)
        )
    )
    result["daily_scores"] = []
    for score in reversed(history):
        item = _score_json(score)
        behavior = db.get(
            DailyBehavior,
            (score.dataset_id, score.user, score.relative_day, score.feature_version),
        )
        if behavior:
            item.update(behavior.values)
        result["daily_scores"].append(item)

    # Alerts for this user
    result["alerts"] = [
        _alert_json(a, s)
        for a, s in db.execute(
            select(Alert, DailyScore)
            .join(DailyScore, Alert.score_id == DailyScore.id)
            .where(
                DailyScore.model_version == model.id,
                DailyScore.user == user_id,
            )
            .order_by(DailyScore.relative_day.desc())
            .limit(100)
        )
    ]

    result["graph_connections_count"] = db.scalar(
        select(
            func.count(func.distinct(Relationship.destination_computer))
        ).where(
            Relationship.dataset_id == model.dataset_id,
            Relationship.user == user_id,
            Relationship.relative_day <= result["latest_day"],
        )
    )
    result["dataset_id"] = model.dataset_id
    result["relative_time"] = model.report.get("relative_time", False)
    result["observation_scope"] = _observation_scope(model)

    db.add(
        AuditLog(
            actor=actor,
            action="user.inspect",
            target=user_id,
            details={"dataset_id": model.dataset_id},
        )
    )
    db.commit()
    return result
