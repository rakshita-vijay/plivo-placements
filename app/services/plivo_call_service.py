"""Outbound call placement via Plivo's REST API.

This is the only module that talks to Plivo's API. Everything else in the
application either receives webhooks from Plivo or returns XML to it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import plivo
from plivo.exceptions import (
    AuthenticationError,
    InvalidRequestError,
    PlivoRestError,
    ResourceNotFoundError,
    ValidationError,
)

from app.core.config import Settings
from app.core.phone_numbers import (
    InvalidPhoneNumberError,
    mask_phone_number,
    normalize_phone_number,
    to_plivo_format,
)
from app.ivr.callback_urls import CallbackUrlFactory
from app.ivr.routes import IvrRoute

logger = logging.getLogger(__name__)


class OutboundCallError(RuntimeError):
    """Raised when Plivo refuses or fails to place the call."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class PlacedCall:
    """Result of a successful call request.

    ``request_uuid`` is Plivo's identifier for the *queued request*; the
    ``CallUUID`` seen in later webhooks is a different value, which is why the
    application carries its own ``session_id``.
    """

    request_uuid: str
    session_id: str
    destination_number: str
    caller_number: str
    api_message: str


class PlivoCallService:
    """Places outbound calls and points them at this application's IVR."""

    def __init__(
        self,
        settings: Settings,
        client: plivo.RestClient | None = None,
        url_factory: CallbackUrlFactory | None = None,
    ) -> None:
        self._settings = settings
        self._urls = url_factory or CallbackUrlFactory(settings)
        self._client = client or plivo.RestClient(
            auth_id=settings.plivo_auth_id,
            auth_token=settings.plivo_auth_token,
        )

    def place_call(self, destination_number: str, session_id: str) -> PlacedCall:
        """Dial ``destination_number`` and hand the answered leg to the IVR.

        The session id is threaded into every callback URL so the answered call
        is matched to the state we created before dialling.

        Raises:
            OutboundCallError: if the number is unusable or Plivo rejects the request.
        """
        try:
            destination_e164 = normalize_phone_number(
                destination_number, self._settings.default_country_code
            )
        except InvalidPhoneNumberError as error:
            raise OutboundCallError(str(error), status_code=422) from error

        caller_e164 = self._settings.caller_number_e164
        if destination_e164 == caller_e164:
            raise OutboundCallError(
                "Destination number must be different from the Plivo caller ID",
                status_code=422,
            )

        answer_url = self._urls.build(IvrRoute.ANSWER, session_id)
        logger.info(
            "Placing outbound call",
            extra={
                "session_id": session_id,
                "destination": mask_phone_number(destination_e164),
                "caller_id": mask_phone_number(caller_e164),
                "answer_url": answer_url,
            },
        )

        try:
            api_response = self._client.calls.create(
                from_=to_plivo_format(caller_e164),
                to_=to_plivo_format(destination_e164),
                answer_url=answer_url,
                answer_method="POST",
                hangup_url=self._urls.build(IvrRoute.HANGUP_EVENT, session_id),
                hangup_method="POST",
                fallback_url=self._urls.build(IvrRoute.FALLBACK, session_id),
                fallback_method="POST",
                ring_timeout=self._settings.outbound_call_ring_timeout_seconds,
            )
        except AuthenticationError as error:
            logger.error("Plivo rejected our credentials", exc_info=error)
            raise OutboundCallError(
                "Plivo authentication failed. Check PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN.",
                status_code=502,
            ) from error
        except (ValidationError, InvalidRequestError) as error:
            logger.warning("Plivo rejected the call request", exc_info=error)
            raise OutboundCallError(f"Plivo rejected the call request: {error}", status_code=400) from error
        except ResourceNotFoundError as error:
            raise OutboundCallError(
                "Plivo could not find the requested resource. Is the caller ID a number on your account?",
                status_code=400,
            ) from error
        except PlivoRestError as error:
            logger.error("Plivo API error while placing call", exc_info=error)
            raise OutboundCallError(f"Plivo API error: {error}", status_code=502) from error

        request_uuid = self._extract_request_uuid(api_response)
        if not request_uuid:
            raise OutboundCallError("Plivo accepted the call but returned no request UUID")

        logger.info(
            "Outbound call accepted by Plivo",
            extra={
                "session_id": session_id,
                "request_uuid": request_uuid,
                "destination": mask_phone_number(destination_e164),
            },
        )
        return PlacedCall(
            request_uuid=request_uuid,
            session_id=session_id,
            destination_number=destination_e164,
            caller_number=caller_e164,
            api_message=self._extract_field(api_response, "message", "call fired"),
        )

    def hangup_call(self, call_uuid: str) -> None:
        """Terminate a live call. Used by the control panel's 'End call' button."""
        try:
            self._client.calls.delete(call_uuid=call_uuid)
        except ResourceNotFoundError as error:
            raise OutboundCallError("That call is no longer active", status_code=404) from error
        except PlivoRestError as error:
            raise OutboundCallError(f"Could not end the call: {error}") from error

    # ------------------------------------------------------------------
    # Response parsing — the SDK returns objects in some versions, dicts in others.
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_field(api_response: object, field_name: str, default: str = "") -> str:
        if isinstance(api_response, dict):
            return str(api_response.get(field_name, default))
        return str(getattr(api_response, field_name, default))

    @classmethod
    def _extract_request_uuid(cls, api_response: object) -> str:
        for field_name in ("request_uuid", "requestUuid", "call_uuid"):
            value = cls._extract_field(api_response, field_name)
            if value:
                return value
        return ""
