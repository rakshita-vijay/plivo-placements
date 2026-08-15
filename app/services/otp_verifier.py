"""OTP verification.

The assignment fixes the OTP to the caller's birthdate in DDMM format, so there
is no database and no delivery channel — but the comparison is still done in
constant time and the code is never logged. Those habits cost nothing here and
are exactly what a real deployment needs.
"""

from __future__ import annotations

import hmac
import logging

logger = logging.getLogger(__name__)

#: Plivo appends the terminator key when the caller presses it explicitly.
_DTMF_TERMINATOR_KEYS = "#*"


class OtpVerifier:
    """Validates DTMF input against the configured access code."""

    def __init__(self, expected_code: str, code_length: int) -> None:
        self._expected_code = expected_code.strip()
        self._code_length = code_length

    @staticmethod
    def normalize_dtmf_input(raw_digits: str | None) -> str:
        """Strip terminator keys and whitespace from raw DTMF input."""
        if not raw_digits:
            return ""
        return raw_digits.strip().strip(_DTMF_TERMINATOR_KEYS).strip()

    def is_correct(self, raw_digits: str | None) -> bool:
        """Return ``True`` only for an exact, correct-length match."""
        entered_code = self.normalize_dtmf_input(raw_digits)
        if len(entered_code) != self._code_length or not entered_code.isdigit():
            return False
        return hmac.compare_digest(entered_code, self._expected_code)

    @staticmethod
    def describe_attempt(raw_digits: str | None) -> str:
        """Redacted description of an attempt, safe to write to logs."""
        entered_code = OtpVerifier.normalize_dtmf_input(raw_digits)
        if not entered_code:
            return "<no digits>"
        return f"<{len(entered_code)} digits>"
