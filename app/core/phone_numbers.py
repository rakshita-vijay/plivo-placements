"""Phone number normalisation.

Plivo expects destination numbers in E.164. Humans type numbers with spaces,
dashes, leading zeros and international prefixes, so every number entering the
system is funnelled through :func:`normalize_phone_number` before it is used.
"""

from __future__ import annotations

import re

_NON_DIGIT_PATTERN = re.compile(r"[^\d+]")
_MIN_SUBSCRIBER_DIGITS = 7
_MAX_E164_DIGITS = 15


class InvalidPhoneNumberError(ValueError):
    """Raised when a value cannot be interpreted as a dialable phone number."""


def normalize_phone_number(raw_number: str, default_country_code: str = "91") -> str:
    """Convert a loosely formatted number into E.164 (``+<country><subscriber>``).

    Handles the formats a reviewer is likely to paste in:

    ``+91 80 3545 4161`` -> ``+918035454161``
    ``02264236412``      -> ``+912264236412`` (national trunk prefix dropped)
    ``00918035454161``   -> ``+918035454161`` (IDD prefix converted)
    ``8035454161``       -> ``+918035454161`` (default country code applied)
    """
    if raw_number is None:
        raise InvalidPhoneNumberError("Phone number is required")

    cleaned = _NON_DIGIT_PATTERN.sub("", str(raw_number).strip())
    if not cleaned:
        raise InvalidPhoneNumberError(f"'{raw_number}' contains no digits")

    has_plus = cleaned.startswith("+")
    digits = cleaned.lstrip("+")
    if not digits.isdigit():
        raise InvalidPhoneNumberError(f"'{raw_number}' is not a valid phone number")

    country_code = str(default_country_code).lstrip("+")

    if has_plus:
        normalized = digits
    elif digits.startswith("00"):
        # International direct dialing prefix, e.g. 00918035454161
        normalized = digits[2:]
    elif digits.startswith("0"):
        # National trunk prefix, e.g. 022 6423 6412 -> +91 22 6423 6412
        normalized = country_code + digits.lstrip("0")
    elif digits.startswith(country_code) and len(digits) > len(country_code) + _MIN_SUBSCRIBER_DIGITS:
        normalized = digits
    else:
        normalized = country_code + digits

    if not (_MIN_SUBSCRIBER_DIGITS < len(normalized) <= _MAX_E164_DIGITS):
        raise InvalidPhoneNumberError(
            f"'{raw_number}' normalises to {len(normalized)} digits, which is not a valid E.164 number"
        )

    return f"+{normalized}"


def to_plivo_format(e164_number: str) -> str:
    """Plivo's REST API and ``<Number>`` element take E.164 without the plus sign."""
    return e164_number.lstrip("+")


def mask_phone_number(e164_number: str) -> str:
    """Redact the subscriber portion of a number for safe logging."""
    if len(e164_number) <= 5:
        return "*" * len(e164_number)
    return f"{e164_number[:4]}{'*' * (len(e164_number) - 6)}{e164_number[-2:]}"
