"""The control-plane API: start a call, watch it, end it.

This is what the browser control panel and the CLI both talk to. The telephony
side of the application never uses these endpoints — Plivo only ever calls the
``/ivr/*`` webhooks.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from app.core.models import CallSession, CallStage
from app.core.phone_numbers import InvalidPhoneNumberError, normalize_phone_number
from app.dependencies import (
    CallServiceDependency,
    SessionStoreDependency,
    SettingsDependency,
)
from app.schemas import CallStatusResponse, PlaceCallRequest, PlaceCallResponse
from app.services.plivo_call_service import OutboundCallError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["calls"])


@router.post(
    "/calls",
    response_model=PlaceCallResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Place an outbound call into the IVR",
)
async def place_outbound_call(
    request_body: PlaceCallRequest,
    settings: SettingsDependency,
    call_service: CallServiceDependency,
    session_store: SessionStoreDependency,
) -> PlaceCallResponse:
    """Dial a number and route the answered call into the IVR flow.

    The session is created *before* dialling so its id can be embedded in the
    callback URLs Plivo is given; there is no window in which a webhook could
    arrive for a session that does not yet exist.
    """
    destination_number = request_body.to_number or settings.default_destination_number
    if not destination_number:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No destination number supplied and DEFAULT_DESTINATION_NUMBER is not set",
        )

    try:
        destination_number = normalize_phone_number(
            destination_number, settings.default_country_code
        )
    except InvalidPhoneNumberError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error

    session = CallSession(
        destination_number=destination_number,
        caller_number=settings.caller_number_e164,
    )
    session.record_event("call_requested", destination=destination_number)
    session_store.create(session)

    try:
        placed_call = call_service.place_call(destination_number, session.session_id)
    except OutboundCallError as error:
        session.advance_to(CallStage.FAILED)
        session.record_event("call_request_failed", error=str(error))
        session_store.save(session)
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error

    session.request_uuid = placed_call.request_uuid
    session.destination_number = placed_call.destination_number
    session.record_event("call_queued", request_uuid=placed_call.request_uuid)
    session_store.save(session)

    return PlaceCallResponse(
        session_id=session.session_id,
        request_uuid=placed_call.request_uuid,
        destination_number=placed_call.destination_number,
        caller_number=placed_call.caller_number,
        message=placed_call.api_message,
    )


@router.get(
    "/calls/{session_id}",
    response_model=CallStatusResponse,
    summary="Read the live state of a call",
)
async def get_call_status(
    session_id: str, session_store: SessionStoreDependency
) -> CallStatusResponse:
    """Return the current stage plus the full event trail for one call."""
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown or expired call session"
        )
    return CallStatusResponse(**session.to_public_dict())


@router.get(
    "/calls",
    response_model=list[CallStatusResponse],
    summary="List recent call sessions",
)
async def list_recent_calls(
    session_store: SessionStoreDependency, limit: int = 20
) -> list[CallStatusResponse]:
    """Most recent calls first. Bounded by the store's TTL."""
    bounded_limit = max(1, min(limit, 100))
    return [
        CallStatusResponse(**session.to_public_dict())
        for session in session_store.list_recent(bounded_limit)
    ]


@router.delete(
    "/calls/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hang up a live call",
)
async def end_call(
    session_id: str,
    session_store: SessionStoreDependency,
    call_service: CallServiceDependency,
) -> None:
    """Terminate a call that is still in progress."""
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown or expired call session"
        )
    if not session.call_uuid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The call has not been answered yet, so it cannot be hung up",
        )

    try:
        call_service.hangup_call(session.call_uuid)
    except OutboundCallError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error

    session.record_event("call_ended_by_operator")
    session.advance_to(CallStage.COMPLETED)
    session_store.save(session)
