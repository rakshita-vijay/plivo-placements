"""Webhook signature verification.

Uses Plivo's own signing helper to generate valid signatures, so these tests
exercise the exact same code path Plivo's servers do.
"""

from __future__ import annotations

from plivo.utils.signature_v3 import get_signature_v3

from app.core.security import PlivoSignatureVerifier

AUTH_TOKEN = "unit-test-auth-token"
NONCE = "unit-test-nonce"
URL = "https://ivr-test.example.com/ivr/answer?session_id=abc123"


def _sign(url: str, nonce: str = NONCE, auth_token: str = AUTH_TOKEN) -> str:
    signature_bytes = get_signature_v3(auth_token.encode("utf-8"), url, nonce)
    return signature_bytes.decode("utf-8")


class TestPlivoSignatureVerifier:
    def test_accepts_a_correctly_signed_get_request(self) -> None:
        verifier = PlivoSignatureVerifier(AUTH_TOKEN, enabled=True)
        signature = _sign(URL)

        assert verifier.is_authentic(
            method="GET", url=URL, signature=signature, nonce=NONCE
        ) is True

    def test_accepts_a_correctly_signed_post_request_with_form_params(self) -> None:
        verifier = PlivoSignatureVerifier(AUTH_TOKEN, enabled=True)
        params = {"Digits": "1503", "CallUUID": "call-uuid-1"}

        # POST signatures fold the form params into the signed base string via
        # construct_post_url; replicate that exactly the way the SDK does.
        from plivo.utils.signature_v3 import construct_post_url

        base_url = construct_post_url(URL, params).decode("utf-8")
        signature = get_signature_v3(AUTH_TOKEN.encode("utf-8"), base_url, NONCE).decode("utf-8")

        assert verifier.is_authentic(
            method="POST", url=URL, signature=signature, nonce=NONCE, form_params=params
        ) is True

    def test_rejects_a_tampered_url(self) -> None:
        verifier = PlivoSignatureVerifier(AUTH_TOKEN, enabled=True)
        signature = _sign(URL)  # signed for the original URL

        tampered_url = "https://ivr-test.example.com/ivr/answer?session_id=someone-elses"
        assert verifier.is_authentic(
            method="GET", url=tampered_url, signature=signature, nonce=NONCE
        ) is False

    def test_rejects_wrong_auth_token(self) -> None:
        verifier = PlivoSignatureVerifier("a-different-token", enabled=True)
        signature = _sign(URL)

        assert verifier.is_authentic(
            method="GET", url=URL, signature=signature, nonce=NONCE
        ) is False

    def test_rejects_missing_signature(self) -> None:
        verifier = PlivoSignatureVerifier(AUTH_TOKEN, enabled=True)
        assert verifier.is_authentic(
            method="GET", url=URL, signature=None, nonce=NONCE
        ) is False

    def test_rejects_missing_nonce(self) -> None:
        verifier = PlivoSignatureVerifier(AUTH_TOKEN, enabled=True)
        signature = _sign(URL)
        assert verifier.is_authentic(
            method="GET", url=URL, signature=signature, nonce=None
        ) is False

    def test_disabled_verifier_accepts_everything(self) -> None:
        # Used only for local replay of captured webhooks with curl.
        verifier = PlivoSignatureVerifier(AUTH_TOKEN, enabled=False)
        assert verifier.is_authentic(
            method="GET", url=URL, signature=None, nonce=None
        ) is True

    def test_malformed_signature_does_not_raise(self) -> None:
        verifier = PlivoSignatureVerifier(AUTH_TOKEN, enabled=True)
        assert verifier.is_authentic(
            method="GET", url=URL, signature="not-base64-!!!", nonce=NONCE
        ) is False


class TestWebhookRequestsAreVerifiedEndToEnd:
    """The FastAPI dependency actually rejects unsigned traffic when enabled."""

    def test_unsigned_request_is_rejected_when_verification_enabled(
        self, settings, fake_call_service
    ) -> None:
        from fastapi.testclient import TestClient

        from app.main import create_application

        strict_settings = settings.model_copy(update={"validate_plivo_signature": True})
        application = create_application(strict_settings)
        application.state.plivo_call_service = fake_call_service

        with TestClient(application) as strict_client:
            response = strict_client.post(
                "/ivr/answer?session_id=abc",
                data={"CallUUID": "x", "From": "1", "To": "2"},
            )
        assert response.status_code == 403

    def test_correctly_signed_request_is_accepted(self, settings, fake_call_service) -> None:
        from fastapi.testclient import TestClient
        from plivo.utils.signature_v3 import construct_post_url

        from app.core.security import NONCE_HEADER, SIGNATURE_HEADER
        from app.main import create_application

        strict_settings = settings.model_copy(update={"validate_plivo_signature": True})
        application = create_application(strict_settings)
        application.state.plivo_call_service = fake_call_service

        path = "/ivr/answer?session_id=abc"
        full_url = f"{strict_settings.public_base_url}{path}"
        form_params = {"CallUUID": "x", "From": "1", "To": "2"}
        base_url = construct_post_url(full_url, form_params).decode("utf-8")
        signature = get_signature_v3(
            strict_settings.plivo_auth_token.encode("utf-8"), base_url, NONCE
        ).decode("utf-8")

        with TestClient(application) as strict_client:
            response = strict_client.post(
                path,
                data=form_params,
                headers={SIGNATURE_HEADER: signature, NONCE_HEADER: NONCE},
            )
        assert response.status_code == 200
