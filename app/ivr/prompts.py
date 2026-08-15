"""Every word the caller hears, in one place.

Keeping copy out of the routing code means adding a third language is a matter
of adding a dictionary entry — no branching logic changes. Prompt keys are
named after the moment in the call, not the text, so translations can diverge
in phrasing without breaking lookups.
"""

from __future__ import annotations

from app.core.models import Language

# Spoken before the caller has chosen a language, so it is intentionally
# bilingual and short.
GREETING_BILINGUAL = (
    "Welcome to Inspire Works. "
    "Bienvenido a Inspire Works."
)

OTP_PROMPTS: dict[str, str] = {
    "first_attempt": (
        "To continue, please enter your four digit access code using your phone keypad."
    ),
    "incorrect_entry": (
        "Sorry, that access code was not correct. "
        "Please enter your four digit access code again."
    ),
    "no_input": (
        "Sorry, I did not receive any digits. "
        "Please enter your four digit access code using your phone keypad."
    ),
    "accepted": "Thank you. Your identity has been verified.",
    "attempts_exhausted": (
        "We were unable to verify your access code. "
        "Please contact support for assistance. Goodbye."
    ),
}

# Level 1 is spoken in both languages because the caller has not chosen yet.
LANGUAGE_MENU_PROMPTS: dict[str, str] = {
    "first_attempt": "For English, press 1. Para continuar en espanol, oprima 2.",
    "incorrect_entry": (
        "Sorry, that is not a valid option. "
        "For English, press 1. Para continuar en espanol, oprima 2."
    ),
    "no_input": (
        "I did not receive a selection. "
        "For English, press 1. Para continuar en espanol, oprima 2."
    ),
}

MAIN_MENU_PROMPTS: dict[Language, dict[str, str]] = {
    Language.ENGLISH: {
        "first_attempt": (
            "Main menu. Press 1 to listen to a short message. "
            "Press 2 to speak with a live associate."
        ),
        "incorrect_entry": (
            "Sorry, that is not a valid option. "
            "Press 1 to listen to a short message. "
            "Press 2 to speak with a live associate."
        ),
        "no_input": (
            "I did not receive a selection. "
            "Press 1 to listen to a short message. "
            "Press 2 to speak with a live associate."
        ),
    },
    Language.SPANISH: {
        "first_attempt": (
            "Menu principal. Oprima 1 para escuchar un mensaje corto. "
            "Oprima 2 para hablar con un agente."
        ),
        "incorrect_entry": (
            "Lo sentimos, esa opcion no es valida. "
            "Oprima 1 para escuchar un mensaje corto. "
            "Oprima 2 para hablar con un agente."
        ),
        "no_input": (
            "No recibimos ninguna seleccion. "
            "Oprima 1 para escuchar un mensaje corto. "
            "Oprima 2 para hablar con un agente."
        ),
    },
}

ACTION_PROMPTS: dict[Language, dict[str, str]] = {
    Language.ENGLISH: {
        "language_confirmed": "You have selected English.",
        "playing_audio": "Here is your short message.",
        "audio_finished": "That was the end of the message.",
        "connecting_associate": (
            "Please hold while we connect you to a live associate."
        ),
        "associate_unavailable": (
            "Sorry, we could not reach an associate right now. "
            "Please try again later."
        ),
        "returning_to_menu": "Returning you to the main menu.",
        "goodbye": "Thank you for calling Inspire Works. Goodbye.",
    },
    Language.SPANISH: {
        "language_confirmed": "Ha seleccionado espanol.",
        "playing_audio": "Aqui esta su mensaje corto.",
        "audio_finished": "Ese fue el final del mensaje.",
        "connecting_associate": (
            "Por favor espere mientras le comunicamos con un agente."
        ),
        "associate_unavailable": (
            "Lo sentimos, no pudimos comunicarle con un agente en este momento. "
            "Por favor intente mas tarde."
        ),
        "returning_to_menu": "Le regresamos al menu principal.",
        "goodbye": "Gracias por llamar a Inspire Works. Hasta luego.",
    },
}

# BCP-47 tags passed to Plivo's <Speak> element.
SPEECH_LANGUAGE_TAGS: dict[Language, str] = {
    Language.ENGLISH: "en-US",
    Language.SPANISH: "es-US",
}


def action_prompt(language: Language, key: str) -> str:
    """Look up a post-selection prompt, falling back to English if untranslated."""
    return ACTION_PROMPTS.get(language, ACTION_PROMPTS[Language.ENGLISH]).get(
        key, ACTION_PROMPTS[Language.ENGLISH][key]
    )


def main_menu_prompt(language: Language, reason: str) -> str:
    """Look up the level-2 menu prompt for a language and prompt reason."""
    prompts = MAIN_MENU_PROMPTS.get(language, MAIN_MENU_PROMPTS[Language.ENGLISH])
    return prompts.get(reason, prompts["first_attempt"])
