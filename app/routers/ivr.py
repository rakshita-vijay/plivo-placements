"""The IVR call flow.

Each endpoint answers one question — "what should the caller hear next?" — and
returns Plivo XML describing it. The flow is:

    answer -> OTP -> language menu (L1) -> main menu (L2) -> play audio | dial associate

Guard rails that shape the code:

* No endpoint past the OTP will act for an unauthenticated session; it sends the
  caller back to the access-code prompt instead. Callback URLs are guessable, so
  authentication is re-checked on every hop rather than assumed.
* A wrong OTP re-prompts indefinitely by default, as the specification requires.
  Silence and off-menu keypresses are capped separately so a forgotten handset
  cannot hold the line open forever.
* If a session vanishes (process restart mid-call), the caller is re-
  authenticated from scratch rather than being let through unverified.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response

from app.core.models import (
    CallSession,
    CallStage,
    Language,
    PromptReason,
)
from app.dependencies import (
    OtpVerifierDependency,
    SessionStoreDependency,
    SettingsDependency,
    XmlBuilderDependency,
)
from app.ivr import prompts
from app.ivr.routes import IvrRoute
from app.routers.webhook_context import PlivoWebhook, PlivoWebhookDependency

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ivr"])

PLIVO_XML_MEDIA_TYPE = "application/xml"


def xml_response(document: str) -> Response:
    """Wrap a Plivo XML document in an HTTP response with the right content type."""
    return Response(content=document, media_type=PLIVO_XML_MEDIA_TYPE)


def _resolve_session(
    webhook: PlivoWebhook,
    session_store: SessionStoreDependency,
    settings: SettingsDependency,
) -> CallSession:
    """Find the session for this webhook, recreating it if it has been lost.

    A recreated session starts unauthenticated on purpose: losing state must
    never be a way past the access code.
    """
    session_id = webhook.session_id
    if session_id:
        session = session_store.get(session_id)
        if session:
            return session

    if webhook.call_uuid:
        session = session_store.get_by_call_uuid(webhook.call_uuid)
        if session:
            return session

    logger.warning(
        "No session found for webhook; re-authenticating caller",
        extra=webhook.loggable_fields(),
    )
    recreated = CallSession(
        session_id=session_id or CallSession(destination_number="", caller_number="").session_id,
        destination_number=webhook.to_number or "",
        caller_number=webhook.from_number or settings.caller_number_e164,
        call_uuid=webhook.call_uuid,
        request_uuid=webhook.request_uuid,
    )
    recreated.record_event("session_recreated")
    return session_store.create(recreated)


def _attach_plivo_identifiers(session: CallSession, webhook: PlivoWebhook) -> None:
    """Record Plivo's own identifiers the first time we see them."""
    if webhook.call_uuid and session.call_uuid != webhook.call_uuid:
        session.call_uuid = webhook.call_uuid
    if webhook.request_uuid and not session.request_uuid:
        session.request_uuid = webhook.request_uuid


def _language_for(session: CallSession, webhook: PlivoWebhook) -> Language:
    """Resolve the active language, preferring the URL then the session."""
    return (
        Language.from_code(webhook.language_code)
        or session.language
        or Language.ENGLISH
    )


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
@router.post(IvrRoute.ANSWER.value, summary="Call answered — start authentication")
async def handle_call_answered(
    webhook: PlivoWebhookDependency,
    session_store: SessionStoreDependency,
    settings: SettingsDependency,
    xml_builder: XmlBuilderDependency,
) -> Response:
    """``answer_url``: the caller picked up. Greet them and ask for the OTP."""
    session = _resolve_session(webhook, session_store, settings)
    _attach_plivo_identifiers(session, webhook)
    session.advance_to(CallStage.ANSWERED)
    session.record_event("call_answered")
    session.advance_to(CallStage.AWAITING_OTP)
    session_store.save(session)

    logger.info("Call answered", extra=webhook.loggable_fields())
    return xml_response(
        xml_builder.build_otp_prompt(
            session.session_id, PromptReason.FIRST_ATTEMPT, include_greeting=True
        )
    )


# ----------------------------------------------------------------------
# Level 0 — OTP authentication
# ----------------------------------------------------------------------
@router.post(IvrRoute.OTP_PROMPT.value, summary="Ask for the access code")
async def prompt_for_otp(
    webhook: PlivoWebhookDependency,
    session_store: SessionStoreDependency,
    settings: SettingsDependency,
    xml_builder: XmlBuilderDependency,
) -> Response:
    """Re-ask for the OTP. Reached by redirect after silence or a wrong code."""
    session = _resolve_session(webhook, session_store, settings)
    reason = PromptReason.parse(webhook.prompt_reason)

    if reason is PromptReason.NO_INPUT:
        silent_prompts = session.register_no_input()
        if silent_prompts >= settings.max_consecutive_invalid_inputs:
            session.advance_to(CallStage.FAILED)
            session_store.save(session)
            logger.info("Ending call after repeated silence", extra=webhook.loggable_fields())
            return xml_response(xml_builder.build_goodbye())

    session.advance_to(CallStage.AWAITING_OTP)
    session_store.save(session)
    return xml_response(xml_builder.build_otp_prompt(session.session_id, reason))


@router.post(IvrRoute.OTP_VERIFY.value, summary="Verify the entered access code")
async def verify_otp(
    webhook: PlivoWebhookDependency,
    session_store: SessionStoreDependency,
    settings: SettingsDependency,
    xml_builder: XmlBuilderDependency,
    otp_verifier: OtpVerifierDependency,
) -> Response:
    """Check the DTMF digits against the hardcoded access code."""
    session = _resolve_session(webhook, session_store, settings)
    entered_digits = webhook.digits

    if not otp_verifier.normalize_dtmf_input(entered_digits):
        silent_prompts = session.register_no_input()
        session_store.save(session)
        if silent_prompts >= settings.max_consecutive_invalid_inputs:
            session.advance_to(CallStage.FAILED)
            session_store.save(session)
            return xml_response(xml_builder.build_goodbye())
        return xml_response(
            xml_builder.build_otp_prompt(session.session_id, PromptReason.NO_INPUT)
        )

    if otp_verifier.is_correct(entered_digits):
        session.register_successful_otp()
        session.advance_to(CallStage.AUTHENTICATED)
        session_store.save(session)
        logger.info("Caller authenticated", extra=webhook.loggable_fields())
        return xml_response(xml_builder.build_otp_accepted(session.session_id))

    attempts = session.register_failed_otp_attempt()
    session_store.save(session)
    logger.info(
        "Incorrect access code",
        extra={
            **webhook.loggable_fields(),
            "attempt": attempts,
            "entered": otp_verifier.describe_attempt(entered_digits),
        },
    )

    # OTP_MAX_ATTEMPTS of 0 means "re-prompt forever", which is the behaviour the
    # assignment specifies. A positive value turns on a safety cap.
    if settings.otp_max_attempts and attempts >= settings.otp_max_attempts:
        session.advance_to(CallStage.FAILED)
        session_store.save(session)
        return xml_response(
            xml_builder.build_terminating_message(prompts.OTP_PROMPTS["attempts_exhausted"])
        )

    return xml_response(
        xml_builder.build_otp_prompt(session.session_id, PromptReason.INCORRECT_ENTRY)
    )


# ----------------------------------------------------------------------
# Level 1 — language selection
# ----------------------------------------------------------------------
@router.post(IvrRoute.LANGUAGE_MENU.value, summary="IVR level 1 — language menu")
async def present_language_menu(
    webhook: PlivoWebhookDependency,
    session_store: SessionStoreDependency,
    settings: SettingsDependency,
    xml_builder: XmlBuilderDependency,
) -> Response:
    """Play the level-1 menu: 1 for English, 2 for Spanish."""
    session = _resolve_session(webhook, session_store, settings)
    if not session.is_authenticated:
        return _redirect_to_authentication(session, session_store, xml_builder)

    reason = PromptReason.parse(webhook.prompt_reason)
    if reason is PromptReason.NO_INPUT:
        silent_prompts = session.register_no_input()
        if silent_prompts >= settings.max_consecutive_invalid_inputs:
            session.advance_to(CallStage.COMPLETED)
            session_store.save(session)
            return xml_response(xml_builder.build_goodbye())

    session.advance_to(CallStage.LANGUAGE_MENU)
    session_store.save(session)
    return xml_response(xml_builder.build_language_menu(session.session_id, reason))


@router.post(IvrRoute.LANGUAGE_SELECT.value, summary="Handle the language keypress")
async def handle_language_selection(
    webhook: PlivoWebhookDependency,
    session_store: SessionStoreDependency,
    settings: SettingsDependency,
    xml_builder: XmlBuilderDependency,
) -> Response:
    """Branch on the level-1 digit, or repeat the menu if it is not on it."""
    session = _resolve_session(webhook, session_store, settings)
    if not session.is_authenticated:
        return _redirect_to_authentication(session, session_store, xml_builder)

    selected_language = Language.from_menu_digit(webhook.digits)
    if selected_language is None:
        return _repeat_language_menu(webhook, session, session_store, settings, xml_builder)

    session.select_language(selected_language)
    session.advance_to(CallStage.MAIN_MENU)
    session_store.save(session)
    logger.info(
        "Language selected",
        extra={**webhook.loggable_fields(), "language": selected_language.value},
    )
    return xml_response(
        xml_builder.build_main_menu(
            session.session_id, selected_language, confirm_language=True
        )
    )


# ----------------------------------------------------------------------
# Level 2 — main menu
# ----------------------------------------------------------------------
@router.post(IvrRoute.MAIN_MENU.value, summary="IVR level 2 — main menu")
async def present_main_menu(
    webhook: PlivoWebhookDependency,
    session_store: SessionStoreDependency,
    settings: SettingsDependency,
    xml_builder: XmlBuilderDependency,
) -> Response:
    """Play the level-2 menu: 1 for the audio message, 2 for an associate."""
    session = _resolve_session(webhook, session_store, settings)
    if not session.is_authenticated:
        return _redirect_to_authentication(session, session_store, xml_builder)

    language = _language_for(session, webhook)
    if session.language is None:
        session.language = language

    reason = PromptReason.parse(webhook.prompt_reason)
    if reason is PromptReason.NO_INPUT:
        silent_prompts = session.register_no_input()
        if silent_prompts >= settings.max_consecutive_invalid_inputs:
            session.advance_to(CallStage.COMPLETED)
            session_store.save(session)
            return xml_response(xml_builder.build_goodbye(language))

    session.advance_to(CallStage.MAIN_MENU)
    session_store.save(session)
    return xml_response(xml_builder.build_main_menu(session.session_id, language, reason))


@router.post(IvrRoute.MAIN_MENU_SELECT.value, summary="Handle the main menu keypress")
async def handle_main_menu_selection(
    webhook: PlivoWebhookDependency,
    session_store: SessionStoreDependency,
    settings: SettingsDependency,
    xml_builder: XmlBuilderDependency,
) -> Response:
    """Branch on the level-2 digit: play audio, or bridge to an associate."""
    session = _resolve_session(webhook, session_store, settings)
    if not session.is_authenticated:
        return _redirect_to_authentication(session, session_store, xml_builder)

    language = _language_for(session, webhook)
    selected_option = webhook.digits

    if selected_option == "1":
        session.reset_unrecognized_inputs()
        session.advance_to(CallStage.PLAYING_AUDIO)
        session.record_event("audio_message_started", language=language.value)
        session_store.save(session)
        return xml_response(
            xml_builder.build_play_audio_message(session.session_id, language)
        )

    if selected_option == "2":
        session.reset_unrecognized_inputs()
        session.advance_to(CallStage.CONNECTING_ASSOCIATE)
        session.record_event("associate_transfer_started", language=language.value)
        session_store.save(session)
        logger.info("Transferring to associate", extra=webhook.loggable_fields())
        return xml_response(
            xml_builder.build_connect_to_associate(session.session_id, language)
        )

    invalid_selections = session.register_invalid_selection(selected_option or "<none>")
    session_store.save(session)
    if invalid_selections >= settings.max_consecutive_invalid_inputs:
        session.advance_to(CallStage.COMPLETED)
        session_store.save(session)
        return xml_response(xml_builder.build_goodbye(language))

    return xml_response(
        xml_builder.build_main_menu(
            session.session_id, language, PromptReason.INCORRECT_ENTRY
        )
    )


@router.post(IvrRoute.ASSOCIATE_DIAL_STATUS.value, summary="Associate leg finished")
async def handle_associate_dial_status(
    webhook: PlivoWebhookDependency,
    session_store: SessionStoreDependency,
    settings: SettingsDependency,
    xml_builder: XmlBuilderDependency,
) -> Response:
    """``<Dial action>``: decide what happens after the transfer attempt ends."""
    session = _resolve_session(webhook, session_store, settings)
    language = _language_for(session, webhook)
    status = webhook.dial_status

    session.record_event("associate_dial_finished", dial_status=status or "unknown")
    session_store.save(session)
    logger.info(
        "Associate dial finished",
        extra={**webhook.loggable_fields(), "dial_status": status or "unknown"},
    )

    if status == "completed":
        # The caller spoke to the associate and the leg ended normally.
        session.advance_to(CallStage.COMPLETED)
        session_store.save(session)
        return xml_response(xml_builder.build_goodbye(language))

    # busy / no-answer / failed / cancel — keep the caller in the IVR.
    return xml_response(
        xml_builder.build_associate_unavailable(session.session_id, language)
    )


# ----------------------------------------------------------------------
# Lifecycle events
# ----------------------------------------------------------------------
@router.post(IvrRoute.HANGUP_EVENT.value, summary="Call ended")
async def handle_hangup_event(
    webhook: PlivoWebhookDependency,
    session_store: SessionStoreDependency,
    settings: SettingsDependency,
    xml_builder: XmlBuilderDependency,
) -> Response:
    """``hangup_url``: the call is over. Close out the session's audit trail."""
    session = _resolve_session(webhook, session_store, settings)
    _attach_plivo_identifiers(session, webhook)
    session.record_event(
        "call_ended",
        hangup_cause=webhook.hangup_cause or "unknown",
        duration_seconds=webhook.form_params.get("Duration", "0"),
    )
    if session.stage not in (CallStage.COMPLETED, CallStage.FAILED):
        session.advance_to(CallStage.COMPLETED)
    session_store.save(session)

    logger.info(
        "Call ended",
        extra={**webhook.loggable_fields(), "cause": webhook.hangup_cause or "unknown"},
    )
    return xml_response(xml_builder.build_empty_response())


@router.post(IvrRoute.FALLBACK.value, summary="Primary answer URL failed")
async def handle_fallback(
    webhook: PlivoWebhookDependency,
    session_store: SessionStoreDependency,
    settings: SettingsDependency,
    xml_builder: XmlBuilderDependency,
) -> Response:
    """``fallback_url``: Plivo could not reach our answer URL. Fail politely."""
    session = _resolve_session(webhook, session_store, settings)
    session.advance_to(CallStage.FAILED)
    session.record_event("fallback_invoked", error=webhook.form_params.get("ErrorMessage", ""))
    session_store.save(session)

    logger.error("Fallback URL invoked by Plivo", extra=webhook.loggable_fields())
    return xml_response(
        xml_builder.build_terminating_message(
            "We are experiencing a technical problem. Please try your call again later."
        )
    )


# ----------------------------------------------------------------------
# Shared branches
# ----------------------------------------------------------------------
def _redirect_to_authentication(
    session: CallSession,
    session_store: SessionStoreDependency,
    xml_builder: XmlBuilderDependency,
) -> Response:
    """Send an unauthenticated caller back to the access-code prompt."""
    session.record_event("authentication_required")
    session.advance_to(CallStage.AWAITING_OTP)
    session_store.save(session)
    logger.warning(
        "Blocked unauthenticated menu access", extra={"session_id": session.session_id}
    )
    return xml_response(
        xml_builder.build_otp_prompt(session.session_id, PromptReason.FIRST_ATTEMPT)
    )


def _repeat_language_menu(
    webhook: PlivoWebhook,
    session: CallSession,
    session_store: SessionStoreDependency,
    settings: SettingsDependency,
    xml_builder: XmlBuilderDependency,
) -> Response:
    """Handle an off-menu keypress at level 1."""
    invalid_selections = session.register_invalid_selection(webhook.digits or "<none>")
    session_store.save(session)

    if invalid_selections >= settings.max_consecutive_invalid_inputs:
        session.advance_to(CallStage.COMPLETED)
        session_store.save(session)
        return xml_response(xml_builder.build_goodbye())

    return xml_response(
        xml_builder.build_language_menu(session.session_id, PromptReason.INCORRECT_ENTRY)
    )
