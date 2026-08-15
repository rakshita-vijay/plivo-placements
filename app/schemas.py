"""Request and response bodies for the JSON API consumed by the UI and CLI."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlaceCallRequest(BaseModel):
    """Body of ``POST /api/calls``."""

    to_number: str | None = Field(
        default=None,
        description=(
            "Destination in E.164 or national format. Falls back to "
            "DEFAULT_DESTINATION_NUMBER when omitted."
        ),
        examples=["+919876543210"],
    )


class PlaceCallResponse(BaseModel):
    """Confirmation that Plivo has queued the call."""

    session_id: str = Field(description="Application-owned id; poll the status endpoint with it.")
    request_uuid: str = Field(description="Plivo's identifier for the queued call request.")
    destination_number: str
    caller_number: str
    message: str


class CallStatusResponse(BaseModel):
    """Live view of a call session, polled by the control panel."""

    session_id: str
    call_uuid: str | None = None
    request_uuid: str | None = None
    destination_number: str
    caller_number: str
    stage: str
    language: str | None = None
    is_authenticated: bool
    otp_attempts: int
    created_at: str
    updated_at: str
    events: list[dict[str, Any]] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Uniform error envelope."""

    detail: str


class HealthResponse(BaseModel):
    """Liveness and configuration summary."""

    status: str
    application: str
    environment: str
    public_base_url: str
    caller_number: str
    associate_number: str
    signature_verification: bool
    active_sessions: int
