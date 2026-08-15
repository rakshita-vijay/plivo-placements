"""OTP authentication: the gate that everything else sits behind."""

from __future__ import annotations

import pytest

from app.services.otp_verifier import OtpVerifier
from tests.conftest import (
    TEST_OTP_CODE,
    get_digits_action,
    path_of,
    redirect_target,
    spoken_text,
)


class TestOtpVerifier:
    """Unit tests for the comparison itself."""

    @pytest.fixture
    def verifier(self) -> OtpVerifier:
        return OtpVerifier(expected_code="1503", code_length=4)

    def test_accepts_the_exact_code(self, verifier: OtpVerifier) -> None:
        assert verifier.is_correct("1503") is True

    def test_accepts_code_with_terminator_key(self, verifier: OtpVerifier) -> None:
        # Callers often press # after the digits.
        assert verifier.is_correct("1503#") is True

    @pytest.mark.parametrize(
        "entered_code",
        ["0000", "1502", "3015", "150", "15033", "", "abcd", "15 3"],
    )
    def test_rejects_anything_else(self, verifier: OtpVerifier, entered_code: str) -> None:
        assert verifier.is_correct(entered_code) is False

    def test_rejects_none(self, verifier: OtpVerifier) -> None:
        assert verifier.is_correct(None) is False

    def test_attempt_description_never_leaks_the_digits(self, verifier: OtpVerifier) -> None:
        description = verifier.describe_attempt("9999")
        assert "9999" not in description
        assert description == "<4 digits>"


class TestOtpCallFlow:
    """End-to-end behaviour of the authentication stage."""

    def test_answered_call_greets_and_asks_for_the_code(self, client, call) -> None:
        driver = call(client)
        response = driver.answer()

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/xml")

        prompt = spoken_text(response.text)
        assert "Welcome to Inspire Works" in prompt
        assert "four digit access code" in prompt
        assert "<GetDigits" in response.text
        assert 'numDigits="4"' in response.text

    def test_access_code_is_never_written_to_plivo_logs(self, client, call) -> None:
        response = call(client).answer()
        assert 'log="false"' in response.text

    def test_silence_falls_through_to_a_redirect_not_a_dead_call(self, client, call) -> None:
        # Plivo does not invoke `action` when no digits are entered; the
        # trailing <Redirect> is the only thing keeping the call alive.
        response = call(client).answer()
        target = redirect_target(response.text)
        assert target is not None
        assert "/ivr/otp/prompt" in target
        assert "reason=no_input" in target

    def test_wrong_code_re_prompts_and_does_not_advance(self, client, call) -> None:
        driver = call(client)
        driver.answer()
        response = driver.enter_otp("9999")

        prompt = spoken_text(response.text)
        assert "was not correct" in prompt
        assert "/ivr/otp/verify" in (get_digits_action(response.text) or "")
        # Crucially, the language menu is not offered.
        assert "press 1" not in prompt.lower()

    def test_wrong_code_re_prompts_indefinitely_by_default(self, client, call) -> None:
        driver = call(client)
        driver.answer()

        for _ in range(12):
            response = driver.enter_otp("0000")
            assert "<Hangup" not in response.text, "call ended despite unlimited attempts"
            assert "was not correct" in spoken_text(response.text)

    def test_correct_code_after_wrong_ones_still_authenticates(self, client, call) -> None:
        driver = call(client)
        driver.answer()
        driver.enter_otp("1111")
        driver.enter_otp("2222")
        response = driver.enter_otp(TEST_OTP_CODE)

        assert "has been verified" in spoken_text(response.text)
        assert "/ivr/menu/language" in (redirect_target(response.text) or "")

    def test_correct_code_leads_to_the_language_menu(self, client, call) -> None:
        driver = call(client)
        driver.answer()
        accepted = driver.enter_otp(TEST_OTP_CODE)

        menu = client.post(path_of(redirect_target(accepted.text)), data={})
        prompt = spoken_text(menu.text)
        assert "For English, press 1" in prompt
        assert "oprima 2" in prompt

    def test_repeated_silence_ends_the_call_politely(self, client, call) -> None:
        driver = call(client)
        driver.answer()

        # Three empty submissions in a row trips MAX_CONSECUTIVE_INVALID_INPUTS.
        driver.enter_otp("")
        driver.enter_otp("")
        response = driver.enter_otp("")

        assert "<Hangup" in response.text
        assert "Goodbye" in spoken_text(response.text)

    def test_answering_the_phone_creates_a_tracked_session(self, client, call) -> None:
        driver = call(client, session_id="tracked-session")
        driver.answer()

        status = client.get("/api/calls/tracked-session")
        assert status.status_code == 200
        assert status.json()["stage"] == "awaiting_otp"
        assert status.json()["is_authenticated"] is False

    def test_successful_authentication_is_recorded_on_the_session(self, client, call) -> None:
        driver = call(client, session_id="auth-session")
        driver.authenticate()

        session = client.get("/api/calls/auth-session").json()
        assert session["is_authenticated"] is True
        assert session["stage"] == "authenticated"
        assert any(event["type"] == "otp_accepted" for event in session["events"])

    def test_failed_attempts_are_counted_on_the_session(self, client, call) -> None:
        driver = call(client, session_id="counter-session")
        driver.answer()
        driver.enter_otp("1111")
        driver.enter_otp("2222")

        session = client.get("/api/calls/counter-session").json()
        assert session["otp_attempts"] == 2
        assert session["is_authenticated"] is False


class TestOtpAttemptCap:
    """The optional safety cap, off by default."""

    def test_cap_ends_the_call_once_configured(self, settings, fake_call_service, call) -> None:
        from fastapi.testclient import TestClient

        from app.main import create_application

        capped_settings = settings.model_copy(update={"otp_max_attempts": 2})
        application = create_application(capped_settings)
        application.state.plivo_call_service = fake_call_service

        with TestClient(application) as capped_client:
            driver = call(capped_client)
            driver.answer()

            first_rejection = driver.enter_otp("0000")
            assert "<Hangup" not in first_rejection.text

            second_rejection = driver.enter_otp("0000")
            assert "<Hangup" in second_rejection.text
            assert "unable to verify" in spoken_text(second_rejection.text)
