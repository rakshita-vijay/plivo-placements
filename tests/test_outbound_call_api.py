"""The control-plane API used by the UI and CLI to trigger and monitor calls."""

from __future__ import annotations

from app.services.plivo_call_service import OutboundCallError


class TestPlaceOutboundCall:
    def test_places_a_call_to_the_supplied_number(self, client, fake_call_service) -> None:
        response = client.post("/api/calls", json={"to_number": "+919876500000"})

        assert response.status_code == 201
        body = response.json()
        assert body["destination_number"] == "+919876500000"
        assert body["caller_number"] == "+918035454161"
        assert body["session_id"]
        assert body["request_uuid"]
        assert fake_call_service.placed_calls[0]["destination_number"] == "+919876500000"

    def test_falls_back_to_the_default_destination_number(self, client, fake_call_service) -> None:
        response = client.post("/api/calls", json={})

        assert response.status_code == 201
        assert response.json()["destination_number"] == "+919876543210"

    def test_missing_destination_and_no_default_is_rejected(
        self, settings, fake_call_service
    ) -> None:
        from fastapi.testclient import TestClient

        from app.main import create_application

        no_default_settings = settings.model_copy(update={"default_destination_number": None})
        application = create_application(no_default_settings)
        application.state.plivo_call_service = fake_call_service

        with TestClient(application) as no_default_client:
            response = no_default_client.post("/api/calls", json={})
        assert response.status_code == 422

    def test_invalid_number_format_is_rejected(self, client) -> None:
        response = client.post("/api/calls", json={"to_number": "not-a-number"})
        assert response.status_code == 422

    def test_plivo_rejection_surfaces_as_an_error_response(
        self, settings, fake_call_service
    ) -> None:
        from fastapi.testclient import TestClient

        from app.main import create_application

        application = create_application(settings)
        fake_call_service.error_to_raise = OutboundCallError(
            "Plivo authentication failed", status_code=502
        )
        application.state.plivo_call_service = fake_call_service

        with TestClient(application) as error_client:
            response = error_client.post("/api/calls", json={"to_number": "+919876500000"})
        assert response.status_code == 502
        assert "authentication failed" in response.json()["detail"]

    def test_a_failed_call_request_is_still_visible_in_session_history(
        self, settings, fake_call_service
    ) -> None:
        from fastapi.testclient import TestClient

        from app.main import create_application

        application = create_application(settings)
        fake_call_service.error_to_raise = OutboundCallError("boom", status_code=502)
        application.state.plivo_call_service = fake_call_service

        with TestClient(application) as error_client:
            error_client.post("/api/calls", json={"to_number": "+919876500000"})
            sessions = error_client.get("/api/calls").json()

        assert len(sessions) == 1
        assert sessions[0]["stage"] == "failed"


class TestGetCallStatus:
    def test_returns_404_for_unknown_session(self, client) -> None:
        response = client.get("/api/calls/does-not-exist")
        assert response.status_code == 404

    def test_returns_the_session_after_it_is_created(self, client) -> None:
        placed = client.post("/api/calls", json={"to_number": "+919876500000"}).json()
        response = client.get(f"/api/calls/{placed['session_id']}")

        assert response.status_code == 200
        assert response.json()["session_id"] == placed["session_id"]


class TestListRecentCalls:
    def test_lists_calls_newest_first(self, client) -> None:
        client.post("/api/calls", json={"to_number": "+919876500001"})
        client.post("/api/calls", json={"to_number": "+919876500002"})

        sessions = client.get("/api/calls").json()
        assert len(sessions) == 2
        assert sessions[0]["destination_number"] == "+919876500002"

    def test_respects_the_limit_parameter(self, client) -> None:
        for i in range(5):
            client.post("/api/calls", json={"to_number": f"+91987650000{i}"})

        sessions = client.get("/api/calls?limit=2").json()
        assert len(sessions) == 2


class TestEndCall:
    def test_returns_409_when_call_has_not_been_answered(self, client) -> None:
        placed = client.post("/api/calls", json={"to_number": "+919876500000"}).json()
        response = client.delete(f"/api/calls/{placed['session_id']}")
        assert response.status_code == 409

    def test_returns_404_for_unknown_session(self, client) -> None:
        response = client.delete("/api/calls/does-not-exist")
        assert response.status_code == 404

    def test_hangs_up_an_answered_call(self, client, fake_call_service, call) -> None:
        placed = client.post("/api/calls", json={"to_number": "+919876500000"}).json()
        driver = call(client, session_id=placed["session_id"])
        driver.answer()

        response = client.delete(f"/api/calls/{placed['session_id']}")
        assert response.status_code == 204
        assert fake_call_service.hung_up_call_uuids == [driver.call_uuid]

        session = client.get(f"/api/calls/{placed['session_id']}").json()
        assert session["stage"] == "completed"


class TestHealthEndpoint:
    def test_reports_masked_numbers_and_config(self, client) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "*" in body["caller_number"]
        assert "*" in body["associate_number"]
        assert body["signature_verification"] is False

    def test_readiness_reflects_https_callback_url(self, client) -> None:
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["credentials_configured"] is True
