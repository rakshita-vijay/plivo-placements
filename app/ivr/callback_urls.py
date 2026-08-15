"""Callback URL construction.

Both the XML builder (writing ``action`` and ``<Redirect>`` targets) and the
outbound call service (setting ``answer_url``, ``hangup_url``, ``fallback_url``)
need to produce URLs that point back at this application. They share this
factory so a URL is built exactly one way everywhere.

Parameter ordering is deterministic because Plivo signs the precise URL string
it was handed; verification later re-derives the signature from that same URL.
"""

from __future__ import annotations

from urllib.parse import urlencode

from app.core.config import Settings
from app.ivr.routes import IvrRoute

SESSION_QUERY_PARAM = "session_id"
LANGUAGE_QUERY_PARAM = "lang"
REASON_QUERY_PARAM = "reason"


class CallbackUrlFactory:
    """Builds absolute, publicly reachable callback URLs for Plivo."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def build(
        self, route: IvrRoute, session_id: str | None = None, **query_params: str | None
    ) -> str:
        """Return ``{PUBLIC_BASE_URL}{route}?{sorted query params}``."""
        parameters = {key: value for key, value in query_params.items() if value}
        if session_id:
            parameters[SESSION_QUERY_PARAM] = session_id

        url = self._settings.webhook_url(route.value)
        if parameters:
            url = f"{url}?{urlencode(sorted(parameters.items()))}"
        return url
