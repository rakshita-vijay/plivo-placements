"""Phone number normalisation — the numbers straight from the assignment brief
are used as the primary test cases, since those are what must work."""

from __future__ import annotations

import pytest

from app.core.phone_numbers import (
    InvalidPhoneNumberError,
    mask_phone_number,
    normalize_phone_number,
    to_plivo_format,
)


class TestNormalizePhoneNumber:
    def test_plivo_number_from_the_assignment_with_spaces(self) -> None:
        assert normalize_phone_number("+91 80 3545 4161") == "+918035454161"

    def test_associate_number_from_the_assignment_national_format(self) -> None:
        # 022 6423 6412 -> drop the trunk prefix 0, apply country code 91.
        assert normalize_phone_number("02264236412") == "+912264236412"

    def test_already_e164_passes_through(self) -> None:
        assert normalize_phone_number("+919876543210") == "+919876543210"

    def test_bare_national_number_gets_country_code_applied(self) -> None:
        assert normalize_phone_number("9876543210", default_country_code="91") == "+919876543210"

    def test_idd_prefix_converted_to_plus(self) -> None:
        assert normalize_phone_number("00918035454161") == "+918035454161"

    def test_dashes_and_parentheses_are_stripped(self) -> None:
        assert normalize_phone_number("+91 (80) 3545-4161") == "+918035454161"

    def test_us_number_with_default_country_code_91_still_respects_leading_plus(self) -> None:
        assert normalize_phone_number("+14155551234", default_country_code="91") == "+14155551234"

    @pytest.mark.parametrize("garbage", ["", "   ", "not-a-number", "++++", None])
    def test_garbage_input_raises(self, garbage) -> None:
        with pytest.raises(InvalidPhoneNumberError):
            normalize_phone_number(garbage)

    def test_too_short_raises(self) -> None:
        with pytest.raises(InvalidPhoneNumberError):
            normalize_phone_number("12345")


class TestToPlivoFormat:
    def test_strips_leading_plus(self) -> None:
        assert to_plivo_format("+918035454161") == "918035454161"


class TestMaskPhoneNumber:
    def test_masks_the_middle_digits(self) -> None:
        masked = mask_phone_number("+918035454161")
        assert masked.startswith("+918")
        assert masked.endswith("61")
        assert "*" in masked
        assert "35454" not in masked

    def test_short_values_are_fully_masked(self) -> None:
        assert mask_phone_number("123") == "***"
