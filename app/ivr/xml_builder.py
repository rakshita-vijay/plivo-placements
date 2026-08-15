"""Builds the Plivo XML documents that drive the call.

Plivo's voice platform is a state machine driven entirely by the XML we return
from each webhook. Centralising XML construction here keeps the routers thin:
a router decides *what should happen next*, this class decides *how to say it*.

Three conventions are load-bearing:

* **Every ``<GetDigits>`` is followed by a ``<Redirect>``.** If the caller stays
  silent, Plivo does *not* call the ``action`` URL — it falls through to the
  next element in the document. Without that redirect the call goes dead.
* **The session id rides in every callback URL.** Plivo preserves the query
  string of the URLs we give it, so the session survives every hop without
  depending on Plivo's own identifiers.
* **Query parameters are emitted in sorted order.** Plivo signs the exact URL
  it was handed, so the URL we emit must match the URL we later verify.
"""

from __future__ import annotations

from plivo import plivoxml

from app.core.config import Settings
from app.core.models import Language, PromptReason
from app.core.phone_numbers import to_plivo_format
from app.ivr import prompts
from app.ivr.callback_urls import CallbackUrlFactory
from app.ivr.routes import IvrRoute

_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'
_DIGITS_ALLOWED = "0123456789"


class IvrXmlBuilder:
    """Produces the Plivo XML for every step of the IVR."""

    def __init__(
        self, settings: Settings, url_factory: CallbackUrlFactory | None = None
    ) -> None:
        self._settings = settings
        self._urls = url_factory or CallbackUrlFactory(settings)

    # ------------------------------------------------------------------
    # URL + element helpers
    # ------------------------------------------------------------------
    def callback_url(
        self, route: IvrRoute, session_id: str | None = None, **query_params: str | None
    ) -> str:
        """Build an absolute callback URL with deterministic parameter ordering."""
        return self._urls.build(route, session_id, **query_params)

    def _voice_for(self, language: Language | None) -> tuple[str, str]:
        """Return the ``(voice, language_tag)`` pair for Plivo's ``<Speak>``."""
        if language is Language.SPANISH:
            return (
                self._settings.speech_voice_spanish,
                prompts.SPEECH_LANGUAGE_TAGS[Language.SPANISH],
            )
        return (
            self._settings.speech_voice_english,
            prompts.SPEECH_LANGUAGE_TAGS[Language.ENGLISH],
        )

    def _speak(self, element, text: str, language: Language | None = None):
        voice, language_tag = self._voice_for(language)
        element.add_speak(content=text, voice=voice, language=language_tag)
        return element

    @staticmethod
    def _render(response: plivoxml.ResponseElement) -> str:
        return f"{_XML_DECLARATION}\n{response.to_string()}"

    # ------------------------------------------------------------------
    # Level 0 — OTP authentication
    # ------------------------------------------------------------------
    def build_otp_prompt(
        self,
        session_id: str,
        reason: PromptReason = PromptReason.FIRST_ATTEMPT,
        include_greeting: bool = False,
    ) -> str:
        """Ask for the 4-digit OTP and collect DTMF input."""
        response = plivoxml.ResponseElement()

        # A short pause stops the greeting being clipped while the audio path
        # opens on answer — a common cause of "the bot never said anything".
        response.add_wait(length=1)

        collector = plivoxml.GetDigitsElement(
            action=self.callback_url(IvrRoute.OTP_VERIFY, session_id),
            method="POST",
            timeout=self._settings.digit_input_timeout_seconds,
            num_digits=self._settings.otp_length,
            retries=1,
            valid_digits=_DIGITS_ALLOWED,
            redirect=True,
            log=False,  # Never write the caller's access code to Plivo's logs.
        )

        spoken = prompts.OTP_PROMPTS[reason.value]
        if include_greeting:
            spoken = f"{prompts.GREETING_BILINGUAL} {spoken}"
        self._speak(collector, spoken)
        response.add(collector)

        # Reached only when the caller entered nothing at all.
        response.add_redirect(
            content=self.callback_url(
                IvrRoute.OTP_PROMPT, session_id, reason=PromptReason.NO_INPUT.value
            ),
            method="POST",
        )
        return self._render(response)

    def build_otp_accepted(self, session_id: str) -> str:
        """Confirm authentication and hand off to the language menu."""
        response = plivoxml.ResponseElement()
        self._speak(response, prompts.OTP_PROMPTS["accepted"])
        response.add_redirect(
            content=self.callback_url(IvrRoute.LANGUAGE_MENU, session_id), method="POST"
        )
        return self._render(response)

    # ------------------------------------------------------------------
    # Level 1 — language selection
    # ------------------------------------------------------------------
    def build_language_menu(
        self, session_id: str, reason: PromptReason = PromptReason.FIRST_ATTEMPT
    ) -> str:
        """IVR level 1: press 1 for English, 2 for Spanish."""
        response = plivoxml.ResponseElement()

        collector = plivoxml.GetDigitsElement(
            action=self.callback_url(IvrRoute.LANGUAGE_SELECT, session_id),
            method="POST",
            timeout=self._settings.digit_input_timeout_seconds,
            num_digits=1,
            retries=1,
            valid_digits=_DIGITS_ALLOWED,
            redirect=True,
        )
        self._speak(collector, prompts.LANGUAGE_MENU_PROMPTS[reason.value])
        response.add(collector)

        response.add_redirect(
            content=self.callback_url(
                IvrRoute.LANGUAGE_MENU, session_id, reason=PromptReason.NO_INPUT.value
            ),
            method="POST",
        )
        return self._render(response)

    # ------------------------------------------------------------------
    # Level 2 — main menu
    # ------------------------------------------------------------------
    def build_main_menu(
        self,
        session_id: str,
        language: Language,
        reason: PromptReason = PromptReason.FIRST_ATTEMPT,
        confirm_language: bool = False,
    ) -> str:
        """IVR level 2: press 1 to hear a message, 2 to reach an associate."""
        response = plivoxml.ResponseElement()

        if confirm_language:
            self._speak(
                response, prompts.action_prompt(language, "language_confirmed"), language
            )

        collector = plivoxml.GetDigitsElement(
            action=self.callback_url(
                IvrRoute.MAIN_MENU_SELECT, session_id, lang=language.value
            ),
            method="POST",
            timeout=self._settings.digit_input_timeout_seconds,
            num_digits=1,
            retries=1,
            valid_digits=_DIGITS_ALLOWED,
            redirect=True,
        )
        self._speak(collector, prompts.main_menu_prompt(language, reason.value), language)
        response.add(collector)

        response.add_redirect(
            content=self.callback_url(
                IvrRoute.MAIN_MENU,
                session_id,
                lang=language.value,
                reason=PromptReason.NO_INPUT.value,
            ),
            method="POST",
        )
        return self._render(response)

    # ------------------------------------------------------------------
    # Level 2 actions
    # ------------------------------------------------------------------
    def build_play_audio_message(self, session_id: str, language: Language) -> str:
        """Option 1: play the hosted MP3, then return the caller to the menu."""
        audio_url = (
            self._settings.audio_message_url_spanish
            if language is Language.SPANISH
            else self._settings.audio_message_url_english
        )

        response = plivoxml.ResponseElement()
        self._speak(response, prompts.action_prompt(language, "playing_audio"), language)
        response.add_play(content=audio_url)
        self._speak(response, prompts.action_prompt(language, "audio_finished"), language)
        self._speak(response, prompts.action_prompt(language, "returning_to_menu"), language)
        response.add_redirect(
            content=self.callback_url(IvrRoute.MAIN_MENU, session_id, lang=language.value),
            method="POST",
        )
        return self._render(response)

    def build_connect_to_associate(self, session_id: str, language: Language) -> str:
        """Option 2: bridge the caller to the live associate number."""
        response = plivoxml.ResponseElement()
        self._speak(
            response, prompts.action_prompt(language, "connecting_associate"), language
        )

        dial = plivoxml.DialElement(
            action=self.callback_url(
                IvrRoute.ASSOCIATE_DIAL_STATUS, session_id, lang=language.value
            ),
            method="POST",
            caller_id=to_plivo_format(self._settings.caller_number_e164),
            timeout=self._settings.associate_dial_timeout_seconds,
            redirect=True,
        )
        dial.add_number(content=to_plivo_format(self._settings.associate_number_e164))
        response.add(dial)
        return self._render(response)

    def build_associate_unavailable(self, session_id: str, language: Language) -> str:
        """The associate leg failed or went unanswered — recover gracefully."""
        response = plivoxml.ResponseElement()
        self._speak(
            response, prompts.action_prompt(language, "associate_unavailable"), language
        )
        self._speak(response, prompts.action_prompt(language, "returning_to_menu"), language)
        response.add_redirect(
            content=self.callback_url(IvrRoute.MAIN_MENU, session_id, lang=language.value),
            method="POST",
        )
        return self._render(response)

    # ------------------------------------------------------------------
    # Terminal documents
    # ------------------------------------------------------------------
    def build_goodbye(self, language: Language | None = None) -> str:
        """Say goodbye and hang up."""
        response = plivoxml.ResponseElement()
        self._speak(
            response, prompts.action_prompt(language or Language.ENGLISH, "goodbye"), language
        )
        response.add_hangup(reason="Call completed", schedule=0)
        return self._render(response)

    def build_terminating_message(
        self, message: str, language: Language | None = None
    ) -> str:
        """Speak a final message (e.g. attempts exhausted) and end the call."""
        response = plivoxml.ResponseElement()
        self._speak(response, message, language)
        response.add_hangup(reason="Call ended by application", schedule=0)
        return self._render(response)

    def build_empty_response(self) -> str:
        """A valid no-op document, used for events that need no call action."""
        return self._render(plivoxml.ResponseElement())
