"""Inbound webhook parsing.

Plivo posts ``application/x-www-form-urlencoded`` bodies. This module turns one
of those raw requests into a typed object, and refuses it outright if the
signature does not check out.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings
from app.core.security import NONCE_HEADER, SIGNATURE_HEADER, PlivoSignatureVerifier
from app.dependencies import get_app_settings, get_signature_verifier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlivoWebhook:
    """A verified webhook from Plivo, with the fields the IVR actually reads."""

    form_params: dict[str, str]
    query_params: dict[str, str]
    request_url: str

    @property
    def call_uuid(self) -> str | None:
        return self.form_params.get("CallUUID")

    @property
    def request_uuid(self) -> str | None:
        return self.form_params.get("RequestUUID")

    @property
    def from_number(self) -> str | None:
        return self.form_params.get("From")

    @property
    def to_number(self) -> str | None:
        return self.form_params.get("To")

    @property
    def digits(self) -> str:
        """DTMF digits collected by the preceding ``<GetDigits>``."""
        return (self.form_params.get("Digits") or "").strip()

    @property
    def dial_status(self) -> str:
        """Outcome of a ``<Dial>``: completed, busy, no-answer, failed, cancel."""
        return (self.form_params.get("DialStatus") or "").strip().lower()

    @property
    def hangup_cause(self) -> str:
        return self.form_params.get("HangupCause") or self.form_params.get("DialHangupCause") or ""

    @property
    def session_id(self) -> str | None:
        """Our own session id, threaded through the callback URL."""
        return self.query_params.get("session_id")

    @property
    def language_code(self) -> str | None:
        return self.query_params.get("lang")

    @property
    def prompt_reason(self) -> str | None:
        return self.query_params.get("reason")

    def loggable_fields(self) -> dict[str, str]:
        """Identifying fields safe to attach to a log record (never DTMF)."""
        return {
            key: value
            for key, value in {
                "call_uuid": self.call_uuid or "",
                "session_id": self.session_id or "",
            }.items()
            if value
        }


async def parse_plivo_webhook(
    request: Request,
    signature_verifier: Annotated[PlivoSignatureVerifier, Depends(get_signature_verifier)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> PlivoWebhook:
    """FastAPI dependency: verify the signature and parse the request body.

    The URL used for verification is rebuilt from ``PUBLIC_BASE_URL`` rather than
    read off the request, because a tunnel or load balancer terminates TLS and
    rewrites the scheme and host that the ASGI server sees.
    """
    form_data = await request.form()
    form_params = {key: str(value) for key, value in form_data.items()}

    reconstructed_url = f"{settings.public_base_url}{request.url.path}"
    if request.url.query:
        reconstructed_url = f"{reconstructed_url}?{request.url.query}"

    is_authentic = signature_verifier.is_authentic(
        method=request.method,
        url=reconstructed_url,
        signature=request.headers.get(SIGNATURE_HEADER),
        nonce=request.headers.get(NONCE_HEADER),
        form_params=form_params,
    )
    if not is_authentic:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request signature could not be verified as originating from Plivo",
        )

    return PlivoWebhook(
        form_params=form_params,
        query_params=dict(request.query_params),
        request_url=reconstructed_url,
    )


PlivoWebhookDependency = Annotated[PlivoWebhook, Depends(parse_plivo_webhook)]
