"""Pydantic request and response schemas.

All response shapes mirror the existing Flask JSON exactly so the React
frontend requires no changes after the migration.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str = Field(..., max_length=256)
    password: str = Field(..., max_length=1024)


class LoginResponse(BaseModel):
    actor: str
    role: str
    csrf_token: str


class SessionResponse(BaseModel):
    actor: str
    role: str
    csrf_token: str


# ---------------------------------------------------------------------------
# Alert status update
# ---------------------------------------------------------------------------

VALID_STATUSES = {"OPEN", "IN_PROGRESS", "RESOLVED"}


class AlertStatusRequest(BaseModel):
    status: str
    version: int

    @field_validator("status")
    @classmethod
    def check_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}")
        return v

    @field_validator("version")
    @classmethod
    def check_version(cls, v: int) -> int:
        if v < 1:
            raise ValueError("version must be >= 1")
        return v


# ---------------------------------------------------------------------------
# Model activation
# ---------------------------------------------------------------------------

class ActivateModelRequest(BaseModel):
    pass  # No body needed; version is a path param


# ---------------------------------------------------------------------------
# Inference alert status update  (same shape as AlertStatusRequest)
# ---------------------------------------------------------------------------

class InferenceAlertStatusRequest(BaseModel):
    status: str
    version: int

    @field_validator("status")
    @classmethod
    def check_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}")
        return v

    @field_validator("version")
    @classmethod
    def check_version(cls, v: int) -> int:
        if v < 1:
            raise ValueError("version must be >= 1")
        return v


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

class ReplayDetectRequest(BaseModel):
    mode: str = "analysis"

    @field_validator("mode")
    @classmethod
    def check_mode(cls, v: str) -> str:
        if v not in ("analysis", "realistic"):
            raise ValueError("mode must be 'analysis' or 'realistic'")
        return v


# ---------------------------------------------------------------------------
# Generic
# ---------------------------------------------------------------------------

class OkResponse(BaseModel):
    status: str = "ok"


class ErrorResponse(BaseModel):
    error: str
    status: str = "error"
