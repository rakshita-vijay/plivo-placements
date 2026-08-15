"""Level 1 (language) and level 2 (main menu) branching."""

from __future__ import annotations

from tests.conftest import (
    dialed_numbers,
    path_of,
    played_audio_urls,
    redirect_target,
    spoken_text,
)


class TestLanguageMenu:
    """IVR level 1."""

    def test_pressing_1_selects_english_and_shows_main_menu(self, client, call) -> None:
        driver = call(client)
        driver.authenticate()
        response = driver.select_language("1")

        prompt = spoken_text(response.text)
        assert "You have selected English" in prompt
        assert "listen to a short message" in prompt
        assert "live associate" in prompt

    def test_pressing_2_selects_spanish_and_shows_main_menu(self, client, call) -> None:
        driver = call(client)
        driver.authenticate()
        response = driver.select_language("2")

        prompt = spoken_text(response.text)
        assert "Ha seleccionado espanol" in prompt
        assert "mensaje corto" in prompt
        assert "agente" in prompt

    def test_off_menu_digit_repeats_the_language_menu(self, client, call) -> None:
        driver = call(client)
        driver.authenticate()
        response = driver.select_language("7")

        prompt = spoken_text(response.text)
        assert "not a valid option" in prompt
        assert "press 1" in prompt.lower()
        assert "<Hangup" not in response.text

    def test_language_choice_is_recorded_on_the_session(self, client, call) -> None:
        driver = call(client, session_id="lang-session")
        driver.authenticate()
        driver.select_language("2")

        session = client.get("/api/calls/lang-session").json()
        assert session["language"] == "es"
        assert session["stage"] == "main_menu"

    def test_unauthenticated_caller_cannot_reach_language_select(self, client, call) -> None:
        # A caller who never entered the OTP but somehow hit this URL directly
        # (e.g. a stale bookmark, or a replayed request) is bounced back.
        driver = call(client)
        driver.answer()  # no OTP entered
        response = driver.select_language("1")

        assert "four digit access code" in spoken_text(response.text)
        assert "press 1" not in spoken_text(response.text).lower()


class TestMainMenu:
    """IVR level 2."""

    def test_option_1_plays_the_audio_message(self, client, call) -> None:
        driver = call(client)
        driver.authenticate()
        driver.select_language("1")
        response = driver.select_menu_option("1", language="en")

        assert played_audio_urls(response.text)
        prompt = spoken_text(response.text)
        assert "short message" in prompt
        assert "end of the message" in prompt
        # Caller is returned to the main menu afterwards.
        assert "/ivr/menu/main" in (redirect_target(response.text) or "")

    def test_option_1_plays_the_spanish_audio_message(self, client, call) -> None:
        driver = call(client)
        driver.authenticate()
        driver.select_language("2")
        response = driver.select_menu_option("1", language="es")

        assert played_audio_urls(response.text)
        assert "Aqui esta su mensaje" in spoken_text(response.text)

    def test_option_2_dials_the_associate_number(self, client, call, settings) -> None:
        driver = call(client)
        driver.authenticate()
        driver.select_language("1")
        response = driver.select_menu_option("2", language="en")

        assert "<Dial" in response.text
        numbers = dialed_numbers(response.text)
        assert numbers == ["912264236412"]
        assert "connect you to a live associate" in spoken_text(response.text)

    def test_off_menu_digit_repeats_the_main_menu(self, client, call) -> None:
        driver = call(client)
        driver.authenticate()
        driver.select_language("1")
        response = driver.select_menu_option("9", language="en")

        prompt = spoken_text(response.text)
        assert "not a valid option" in prompt
        assert "<Hangup" not in response.text

    def test_repeated_invalid_selections_end_the_call(self, client, call) -> None:
        driver = call(client)
        driver.authenticate()
        driver.select_language("1")
        driver.select_menu_option("9", language="en")
        driver.select_menu_option("8", language="en")
        response = driver.select_menu_option("7", language="en")

        assert "<Hangup" in response.text
        assert "Goodbye" in spoken_text(response.text)

    def test_unauthenticated_caller_cannot_reach_main_menu_select(self, client, call) -> None:
        driver = call(client)
        driver.answer()
        response = driver.select_menu_option("1", language="en")
        assert "four digit access code" in spoken_text(response.text)


class TestAssociateDialOutcome:
    """``<Dial action>`` — what happens after the transfer attempt."""

    def test_completed_dial_ends_the_call_gracefully(self, client, call) -> None:
        driver = call(client, session_id="dial-completed")
        driver.authenticate()
        driver.select_language("1")
        driver.select_menu_option("2", language="en")

        response = driver.post(
            "/ivr/associate/status?lang=en", DialStatus="completed"
        )
        assert "<Hangup" in response.text
        assert "Goodbye" in spoken_text(response.text)

    def test_no_answer_returns_caller_to_the_menu(self, client, call) -> None:
        driver = call(client, session_id="dial-no-answer")
        driver.authenticate()
        driver.select_language("1")
        driver.select_menu_option("2", language="en")

        response = driver.post(
            "/ivr/associate/status?lang=en", DialStatus="no-answer"
        )
        prompt = spoken_text(response.text)
        assert "could not reach an associate" in prompt
        assert "/ivr/menu/main" in (redirect_target(response.text) or "")
        assert "<Hangup" not in response.text

    def test_busy_returns_caller_to_the_menu(self, client, call) -> None:
        driver = call(client, session_id="dial-busy")
        driver.authenticate()
        driver.select_language("2")
        driver.select_menu_option("2", language="es")

        response = driver.post(
            "/ivr/associate/status?lang=es", DialStatus="busy"
        )
        assert "no pudimos comunicarle" in spoken_text(response.text)


class TestFullCallJourney:
    """The whole flow, end to end, exactly as the demo video should show it."""

    def test_wrong_otp_then_correct_otp_then_english_then_audio(self, client, call) -> None:
        driver = call(client, session_id="journey-audio")

        greeting = driver.answer()
        assert "four digit access code" in spoken_text(greeting.text)

        wrong = driver.enter_otp("9999")
        assert "was not correct" in spoken_text(wrong.text)

        accepted = driver.enter_otp("1503")
        assert "has been verified" in spoken_text(accepted.text)

        menu_url = path_of(redirect_target(accepted.text))
        language_menu = client.post(menu_url, data={"session_id": "journey-audio"})
        assert "For English, press 1" in spoken_text(language_menu.text)

        main_menu = driver.select_language("1")
        assert "listen to a short message" in spoken_text(main_menu.text)

        audio = driver.select_menu_option("1", language="en")
        assert played_audio_urls(audio.text)

        final_session = client.get("/api/calls/journey-audio").json()
        assert final_session["is_authenticated"] is True
        assert final_session["language"] == "en"
        assert final_session["otp_attempts"] == 1

    def test_correct_otp_then_spanish_then_associate(self, client, call) -> None:
        driver = call(client, session_id="journey-associate")
        driver.authenticate()
        driver.select_language("2")
        dial_response = driver.select_menu_option("2", language="es")

        assert dialed_numbers(dial_response.text) == ["912264236412"]

        final_session = client.get("/api/calls/journey-associate").json()
        assert final_session["language"] == "es"
        assert final_session["stage"] == "connecting_associate"
