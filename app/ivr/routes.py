"""Canonical webhook paths.

The XML builder writes these URLs into ``action`` and ``<Redirect>`` elements,
and the router registers its endpoints from the same enum. A single definition
means a renamed endpoint can never silently break a call flow.
"""

from __future__ import annotations

from enum import Enum


class IvrRoute(str, Enum):
    """Every URL Plivo is ever asked to call back."""

    #: ``answer_url`` for the outbound call — the entry point of the flow.
    ANSWER = "/ivr/answer"

    #: Level 0 — OTP authentication.
    OTP_PROMPT = "/ivr/otp/prompt"
    OTP_VERIFY = "/ivr/otp/verify"

    #: Level 1 — language selection.
    LANGUAGE_MENU = "/ivr/menu/language"
    LANGUAGE_SELECT = "/ivr/menu/language/select"

    #: Level 2 — main menu and its actions.
    MAIN_MENU = "/ivr/menu/main"
    MAIN_MENU_SELECT = "/ivr/menu/main/select"
    ASSOCIATE_DIAL_STATUS = "/ivr/associate/status"

    #: Out-of-band call lifecycle events.
    HANGUP_EVENT = "/ivr/events/hangup"
    FALLBACK = "/ivr/events/fallback"

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.value
