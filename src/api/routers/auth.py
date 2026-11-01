"""Auth router — login, logout, OIDC, session, rate limiting.

Preserves the exact API surface of the Flask auth.py configure_auth() block
so the React SessionGate component and useApi.js require no changes.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash

from src.db.models import AuditLog, RateLimit, now
from src.api.dependencies import (
    ROLES,
    Settings,
    _get_factory,
    check_csrf,
    get_db,
    get_settings,
)
from src.api.schemas import LoginRequest, LoginResponse, OkResponse, SessionResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Internal helpers (ported from configure_auth)
# ---------------------------------------------------------------------------

def _budget(actor: str, limit: int, kind: str, settings: Settings) -> None:
    """DB-backed per-minute request budget. Raises 429 on excess."""
    factory = _get_factory()
    instant = now()
    minute = int(instant.timestamp()) // 60
    key = hashlib.sha256(f"{actor}|{kind}|{minute}".encode()).hexdigest()
    with factory.begin() as db:
        db.execute(delete(RateLimit).where(RateLimit.expires_at < instant))
        stmt = (
            pg_insert(RateLimit)
            .values(key=key, count=1, expires_at=instant + timedelta(minutes=2))
            .on_conflict_do_update(
                index_elements=[RateLimit.key],
                set_={"count": RateLimit.count + 1},
            )
            .returning(RateLimit.count)
        )
        count = db.scalar(stmt)
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Request budget exceeded; retry next minute",
        )


def _establish_session(
    request: Request,
    actor: str,
    role: str,
    action: str,
    db: Session,
) -> str:
    """Write actor/role/csrf into the Starlette session and create an audit log."""
    csrf = secrets.token_urlsafe(32)
    request.session.clear()
    request.session.update(actor=actor, role=role, csrf=csrf)
    db.add(AuditLog(actor=actor, action=action, target=actor, details={"role": role}))
    db.commit()
    return csrf


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/options")
async def auth_options(settings: Settings = Depends(get_settings)):
    """Return available authentication methods (development login / OIDC)."""
    return {
        "development": settings.app_env == "development",
        "oidc": bool(settings.oidc_issuer),
    }


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    body: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Development username/password login. Disabled in production environments."""
    if settings.app_env != "development":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    _budget(str(request.client.host or "unknown"), 10, "login", settings)

    configured = settings.dev_auth_users.get(body.username)
    if (
        not configured
        or configured.get("role") not in ROLES
        or not check_password_hash(
            configured.get("password_hash", ""), body.password
        )
    ):
        db.add(
            AuditLog(
                actor="anonymous",
                action="auth.failed",
                target="development-login",
                details={},
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    csrf = _establish_session(
        request, body.username, configured["role"], "auth.login", db
    )
    return LoginResponse(actor=body.username, role=configured["role"], csrf_token=csrf)


@router.get("/session", response_model=SessionResponse)
async def current_session(request: Request):
    """Return the current authenticated session details."""
    actor = request.session.get("actor")
    if not actor:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return SessionResponse(
        actor=actor,
        role=request.session.get("role", ""),
        csrf_token=request.session.get("csrf", ""),
    )


@router.post("/logout", response_model=OkResponse)
async def logout(
    request: Request,
    db: Session = Depends(get_db),
    _csrf: None = Depends(check_csrf),
):
    """Invalidate the current session."""
    actor = request.session.get("actor", "anonymous")
    db.add(
        AuditLog(
            actor=actor,
            action="auth.logout",
            target="session",
            details={},
        )
    )
    db.commit()
    request.session.clear()
    return OkResponse()


# ---------------------------------------------------------------------------
# Optional OIDC — registered from main.py when OIDC_ISSUER is set
# ---------------------------------------------------------------------------

def register_oidc(app, settings: Settings) -> None:
    """Attach OIDC routes to the FastAPI app when OIDC is configured."""
    issuer = settings.oidc_issuer
    if not issuer:
        return
    if not issuer.startswith("https://"):
        raise ValueError("OIDC issuer must use HTTPS")

    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        "organization",
        client_id=os.environ["OIDC_CLIENT_ID"],
        client_secret=os.environ["OIDC_CLIENT_SECRET"],
        server_metadata_url=issuer.rstrip("/") + "/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile"},
    )

    oidc_router = APIRouter(prefix="/api/auth", tags=["oidc"])

    @oidc_router.get("/oidc")
    async def oidc_start(request: Request):
        redirect_uri = os.environ["OIDC_REDIRECT_URI"]
        return await oauth.organization.authorize_redirect(request, redirect_uri)

    @oidc_router.get("/callback")
    async def oidc_callback(request: Request, db: Session = Depends(get_db)):
        token = await oauth.organization.authorize_access_token(request)
        identity = token.get("userinfo", {})
        if identity.get("iss") != issuer or not identity.get("sub"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid organization identity",
            )
        actor = identity["sub"]
        role = settings.oidc_roles.get(actor)
        if role not in ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization account is not provisioned",
            )
        _establish_session(request, actor, role, "auth.oidc_login", db)
        from starlette.responses import RedirectResponse
        return RedirectResponse(url=settings.frontend_url)

    app.include_router(oidc_router)
