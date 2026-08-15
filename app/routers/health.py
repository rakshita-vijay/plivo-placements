"""Health and configuration endpoints.

``/health`` doubles as a setup check: it echoes the resolved numbers and the
public base URL, which is the fastest way to spot a stale ngrok URL or a
mistyped caller ID before wasting a call.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.phone_numbers import mask_phone_number
from app.dependencies import SessionStoreDependency, SettingsDependency
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness and config summary")
async def read_health(
    settings: SettingsDependency, session_store: SessionStoreDependency
) -> HealthResponse:
    """Report service health and the configuration the IVR will actually use."""
    return HealthResponse(
        status="ok",
        application=settings.app_name,
        environment=settings.environment,
        public_base_url=settings.public_base_url,
        caller_number=mask_phone_number(settings.caller_number_e164),
        associate_number=mask_phone_number(settings.associate_number_e164),
        signature_verification=settings.validate_plivo_signature,
        active_sessions=len(session_store.list_recent(limit=100)),
    )


@router.get("/health/ready", summary="Readiness probe")
async def read_readiness(settings: SettingsDependency) -> dict[str, bool | str]:
    """Confirm the settings needed to place a call are present and coherent."""
    is_publicly_reachable = settings.public_base_url.startswith("https://")
    return {
        "ready": True,
        "credentials_configured": bool(settings.plivo_auth_id and settings.plivo_auth_token),
        "https_callbacks": is_publicly_reachable,
        "environment": settings.environment,
    }
