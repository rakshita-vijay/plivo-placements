"""Webhook authentication.

Our IVR endpoints are publicly reachable — they have to be, since Plivo fetches
them from the internet. Without verification, anyone who discovers the tunnel
URL could drive the call flow or forge call events.

Plivo signs every webhook with an HMAC-SHA256 over the exact URL it called plus
a per-request nonce. We recompute that signature with our auth token and reject
anything that does not match.
"""

from __future__ import annotations

import logging

from plivo.utils import validate_v3_signature

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Plivo-Signature-V3"
NONCE_HEADER = "X-Plivo-Signature-V3-Nonce"


class PlivoSignatureVerifier:
    """Verifies the ``X-Plivo-Signature-V3`` header on inbound webhooks."""

    def __init__(self, auth_token: str, *, enabled: bool = True) -> None:
        self._auth_token = auth_token
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def is_authentic(
        self,
        *,
        method: str,
        url: str,
        signature: str | None,
        nonce: str | None,
        form_params: dict[str, str] | None = None,
    ) -> bool:
        """Return ``True`` when the request provably came from Plivo.

        When verification is disabled every request is accepted — useful when
        replaying captured webhooks by hand, but it must not be the production
        setting.
        """
        if not self._enabled:
            return True

        if not signature or not nonce:
            logger.warning(
                "Rejected unsigned webhook", extra={"url": url, "has_nonce": bool(nonce)}
            )
            return False

        try:
            is_valid = validate_v3_signature(
                method=method.upper(),
                uri=url,
                nonce=nonce,
                auth_token=self._auth_token,
                v3_signature=signature,
                params=dict(form_params or {}),
            )
        except Exception as error:  # noqa: BLE001 - never let verification 500 the webhook
            logger.warning("Signature verification raised", extra={"url": url}, exc_info=error)
            return False

        if not is_valid:
            logger.warning("Rejected webhook with invalid signature", extra={"url": url})
        return is_valid
