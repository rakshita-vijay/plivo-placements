"""Shared test fixtures.

Tests drive the application exactly as Plivo would: form-encoded POSTs to the
webhook URLs, following each ``<Redirect>`` by hand. The Plivo REST client is
replaced by a fake, so the suite never touches the network and never spends
call credit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_application
from app.services.plivo_call_service import OutboundCallError, PlacedCall

TEST_OTP_CODE = "1503"
TEST_PUBLIC_BASE_URL = "https://ivr-test.example.com"


@dataclass
class FakePlivoCallService:
    """Stand-in for :class:`PlivoCallService` that records calls instead of placing them."""

    placed_calls: list[dict[str, str]] = field(default_factory=list)
    hung_up_call_uuids: list[str] = field(default_factory=list)
    error_to_raise: OutboundCallError | None = None

    def place_call(self, destination_number: str, session_id: str) -> PlacedCall:
        if self.error_to_raise:
            raise self.error_to_raise
        self.placed_calls.append(
            {"destination_number": destination_number, "session_id": session_id}
        )
        return PlacedCall(
            request_uuid=f"req-{len(self.placed_calls)}",
            session_id=session_id,
            destination_number=destination_number,
            caller_number="+918035454161",
            api_message="call fired",
        )

    def hangup_call(self, call_uuid: str) -> None:
        self.hung_up_call_uuids.append(call_uuid)


@pytest.fixture
def settings() -> Settings:
    """Deterministic settings with signature verification switched off."""
    return Settings(
        plivo_auth_id="MATEST0000000000TEST",
        plivo_auth_token="test-auth-token",
        plivo_caller_number="+918035454161",
        default_destination_number="+919876543210",
        live_associate_number="02264236412",
        public_base_url=TEST_PUBLIC_BASE_URL,
        validate_plivo_signature=False,
        otp_code=TEST_OTP_CODE,
        otp_max_attempts=0,
        max_consecutive_invalid_inputs=3,
        log_level="WARNING",
    )


@pytest.fixture
def fake_call_service() -> FakePlivoCallService:
    return FakePlivoCallService()


@pytest.fixture
def client(settings: Settings, fake_call_service: FakePlivoCallService) -> TestClient:
    """A test client wired to an isolated application instance."""
    application = create_application(settings)
    application.state.plivo_call_service = fake_call_service
    with TestClient(application) as test_client:
        yield test_client


class CallDriver:
    """Drives a call through the IVR the way Plivo would."""

    def __init__(self, client: TestClient, session_id: str = "test-session") -> None:
        self.client = client
        self.session_id = session_id
        self.call_uuid = "call-uuid-under-test"

    def post(self, path: str, **form_fields: str):
        """POST a form-encoded webhook, mirroring Plivo's request shape."""
        payload = {
            "CallUUID": self.call_uuid,
            "From": "918035454161",
            "To": "919876543210",
            "Direction": "outbound",
            "CallStatus": "in-progress",
            **form_fields,
        }
        separator = "&" if "?" in path else "?"
        url = f"{path}{separator}session_id={self.session_id}"
        return self.client.post(url, data=payload)

    def answer(self):
        return self.post("/ivr/answer")

    def enter_otp(self, digits: str):
        return self.post("/ivr/otp/verify", Digits=digits)

    def select_language(self, digits: str):
        return self.post("/ivr/menu/language/select", Digits=digits)

    def select_menu_option(self, digits: str, language: str = "en"):
        return self.post(f"/ivr/menu/main/select?lang={language}", Digits=digits)

    def authenticate(self):
        """Fast-forward through answer + correct OTP."""
        self.answer()
        return self.enter_otp(TEST_OTP_CODE)


@pytest.fixture
def call() -> Any:
    """Factory for a :class:`CallDriver` bound to the test client."""

    def _build(client: TestClient, session_id: str = "test-session") -> CallDriver:
        return CallDriver(client, session_id)

    return _build


# ----------------------------------------------------------------------
# Assertion helpers
# ----------------------------------------------------------------------
def spoken_text(xml_document: str) -> str:
    """Concatenate everything the caller would hear from a ``<Speak>``."""
    return " ".join(re.findall(r"<Speak[^>]*>(.*?)</Speak>", xml_document, re.DOTALL))


def get_digits_action(xml_document: str) -> str | None:
    """Return the ``action`` URL of the document's ``<GetDigits>``, if any."""
    match = re.search(r'<GetDigits[^>]*action="([^"]+)"', xml_document)
    return match.group(1).replace("&amp;", "&") if match else None


def redirect_target(xml_document: str) -> str | None:
    """Return the URL of the document's ``<Redirect>``, if any."""
    match = re.search(r"<Redirect[^>]*>(.*?)</Redirect>", xml_document)
    return match.group(1).replace("&amp;", "&") if match else None


def dialed_numbers(xml_document: str) -> list[str]:
    """Return every number inside a ``<Dial>``."""
    return re.findall(r"<Number[^>]*>(.*?)</Number>", xml_document)


def played_audio_urls(xml_document: str) -> list[str]:
    return re.findall(r"<Play[^>]*>(.*?)</Play>", xml_document)


def path_of(absolute_url: str) -> str:
    """Strip the public base URL so tests can re-post a redirect target."""
    return absolute_url.replace(TEST_PUBLIC_BASE_URL, "")
