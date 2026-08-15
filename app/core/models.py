"""Domain models shared across the call flow.

A :class:`CallSession` is the server-side memory of one telephone call.

On identifiers: Plivo's REST API returns a ``request_uuid`` when a call is
queued, but the webhooks that follow carry a ``CallUUID`` — a *different*
value, only minted once the call leg exists. Rather than trying to reconcile
the two, every session gets an application-owned ``session_id`` which we thread
through the callback URLs we hand to Plivo. Plivo's own identifiers are
recorded on the session for traceability, and a secondary index on
``call_uuid`` lets late-arriving events find their session too.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class Language(str, Enum):
    """Languages offered at IVR level 1."""

    ENGLISH = "en"
    SPANISH = "es"

    @classmethod
    def from_menu_digit(cls, digit: str) -> Language | None:
        """Map the level-1 keypad digit to a language, or ``None`` if invalid."""
        return {"1": cls.ENGLISH, "2": cls.SPANISH}.get(digit)

    @classmethod
    def from_code(cls, code: str | None) -> Language | None:
        """Parse a language code from a callback URL, tolerating junk input."""
        if not code:
            return None
        try:
            return cls(code.lower())
        except ValueError:
            return None


class CallStage(str, Enum):
    """Where the caller currently is in the flow. Drives logging and the UI."""

    INITIATED = "initiated"
    ANSWERED = "answered"
    AWAITING_OTP = "awaiting_otp"
    AUTHENTICATED = "authenticated"
    LANGUAGE_MENU = "language_menu"
    MAIN_MENU = "main_menu"
    PLAYING_AUDIO = "playing_audio"
    CONNECTING_ASSOCIATE = "connecting_associate"
    COMPLETED = "completed"
    FAILED = "failed"


class PromptReason(str, Enum):
    """Why a prompt is being played, which decides the wording the caller hears."""

    FIRST_ATTEMPT = "first_attempt"
    INCORRECT_ENTRY = "incorrect_entry"
    NO_INPUT = "no_input"

    @classmethod
    def parse(cls, value: str | None) -> PromptReason:
        """Read the reason from a callback URL, defaulting to the first attempt."""
        if not value:
            return cls.FIRST_ATTEMPT
        try:
            return cls(value)
        except ValueError:
            return cls.FIRST_ATTEMPT


def new_session_id() -> str:
    """Generate an opaque, URL-safe session identifier."""
    return uuid.uuid4().hex


@dataclass
class CallSession:
    """Mutable state for a single call, keyed by an application-owned id."""

    destination_number: str
    caller_number: str
    session_id: str = field(default_factory=new_session_id)
    request_uuid: str | None = None
    call_uuid: str | None = None
    stage: CallStage = CallStage.INITIATED
    language: Language | None = None
    is_authenticated: bool = False
    otp_attempts: int = 0
    consecutive_unrecognized_inputs: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    events: list[dict[str, Any]] = field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)

    def advance_to(self, stage: CallStage) -> None:
        if self.stage is not stage:
            self.stage = stage
            self.record_event("stage_changed", stage=stage.value)
        else:
            self.touch()

    def record_event(self, event_type: str, **details: Any) -> None:
        """Append a timestamped event, forming an audit trail for the call."""
        self.events.append(
            {"at": datetime.now(UTC).isoformat(), "type": event_type, **details}
        )
        self.touch()

    # ------------------------------------------------------------------
    # Authentication state
    # ------------------------------------------------------------------
    def register_failed_otp_attempt(self) -> int:
        self.otp_attempts += 1
        self.consecutive_unrecognized_inputs = 0
        self.record_event("otp_rejected", attempt=self.otp_attempts)
        return self.otp_attempts

    def register_successful_otp(self) -> None:
        self.is_authenticated = True
        self.consecutive_unrecognized_inputs = 0
        self.record_event("otp_accepted", attempts_used=self.otp_attempts + 1)

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------
    def register_no_input(self) -> int:
        """Caller stayed silent through a prompt."""
        self.consecutive_unrecognized_inputs += 1
        self.record_event("no_input", consecutive=self.consecutive_unrecognized_inputs)
        return self.consecutive_unrecognized_inputs

    def register_invalid_selection(self, digits: str) -> int:
        """Caller pressed a key that is not on the current menu."""
        self.consecutive_unrecognized_inputs += 1
        self.record_event(
            "invalid_selection",
            digits=digits,
            consecutive=self.consecutive_unrecognized_inputs,
        )
        return self.consecutive_unrecognized_inputs

    def reset_unrecognized_inputs(self) -> None:
        self.consecutive_unrecognized_inputs = 0

    def select_language(self, language: Language) -> None:
        self.language = language
        self.reset_unrecognized_inputs()
        self.record_event("language_selected", language=language.value)

    def to_public_dict(self) -> dict[str, Any]:
        """Serialise for the status API consumed by the browser control panel."""
        return {
            "session_id": self.session_id,
            "call_uuid": self.call_uuid,
            "request_uuid": self.request_uuid,
            "destination_number": self.destination_number,
            "caller_number": self.caller_number,
            "stage": self.stage.value,
            "language": self.language.value if self.language else None,
            "is_authenticated": self.is_authenticated,
            "otp_attempts": self.otp_attempts,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "events": self.events,
        }
