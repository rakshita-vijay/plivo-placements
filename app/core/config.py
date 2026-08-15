"""Application configuration.

Every tunable value lives here and is loaded from environment variables (or a
local ``.env`` file). Nothing in the codebase reads ``os.environ`` directly, so
this module is the single source of truth for runtime behaviour.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.phone_numbers import normalize_phone_number


class Settings(BaseSettings):
    """Runtime settings for the Plivo IVR demo application."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------
    # Plivo account credentials
    # ------------------------------------------------------------------
    plivo_auth_id: str = Field(
        ...,
        description="Plivo Auth ID from https://console.plivo.com (starts with MA/SA).",
    )
    plivo_auth_token: str = Field(
        ...,
        description="Plivo Auth Token. Treat as a secret; never commit it.",
    )

    # ------------------------------------------------------------------
    # Phone numbers
    # ------------------------------------------------------------------
    plivo_caller_number: str = Field(
        ...,
        description="Plivo number used as the caller ID for outbound calls.",
    )
    default_destination_number: str | None = Field(
        default=None,
        description="Optional default number to call when the UI/CLI omits one.",
    )
    live_associate_number: str = Field(
        ...,
        description="Number the caller is forwarded to from the 'live associate' menu option.",
    )
    default_country_code: str = Field(
        default="91",
        description="Country code applied to national-format numbers (no plus sign).",
    )

    # ------------------------------------------------------------------
    # Webhook exposure
    # ------------------------------------------------------------------
    public_base_url: str = Field(
        ...,
        description=(
            "Publicly reachable HTTPS base URL of this service, e.g. an ngrok "
            "tunnel. Plivo fetches all call-flow XML from here."
        ),
    )
    validate_plivo_signature: bool = Field(
        default=True,
        description="Reject webhook requests that are not signed by Plivo (V3 signature).",
    )

    # ------------------------------------------------------------------
    # Authentication (OTP)
    # ------------------------------------------------------------------
    otp_code: str = Field(
        default="1234",
        description=(
            "Hardcoded 4-digit OTP. Ships as the placeholder 1234 so the app runs "
            "out of the box; override in .env with the caller's birthdate in DDMM "
            "format to match the original assignment spec exactly."
        ),
    )
    otp_length: int = Field(default=4, ge=1, le=10)
    otp_max_attempts: int = Field(
        default=0,
        ge=0,
        description=(
            "Maximum wrong-OTP attempts before the call is ended. 0 means unlimited, "
            "which matches the assignment's 're-prompt until correct' requirement."
        ),
    )
    max_consecutive_invalid_inputs: int = Field(
        default=3,
        ge=1,
        description=(
            "Consecutive silent or off-menu responses tolerated before the call is "
            "ended politely. Wrong OTP entries are governed by OTP_MAX_ATTEMPTS instead."
        ),
    )

    # ------------------------------------------------------------------
    # Call flow behaviour
    # ------------------------------------------------------------------
    outbound_call_ring_timeout_seconds: int = Field(default=45, ge=10, le=120)
    digit_input_timeout_seconds: int = Field(default=8, ge=3, le=30)
    associate_dial_timeout_seconds: int = Field(default=30, ge=10, le=120)
    speech_voice_english: str = Field(default="Polly.Joanna")
    speech_voice_spanish: str = Field(default="Polly.Lupe")
    audio_message_url_english: str = Field(
        default="https://s3.amazonaws.com/plivocloud/music.mp3",
        description="Publicly accessible MP3 played for the English 'short message' option.",
    )
    audio_message_url_spanish: str = Field(
        default="https://s3.amazonaws.com/plivocloud/music.mp3",
        description="Publicly accessible MP3 played for the Spanish 'short message' option.",
    )

    # ------------------------------------------------------------------
    # Service
    # ------------------------------------------------------------------
    app_name: str = Field(default="InspireWorks IVR Demo")
    environment: Literal["development", "staging", "production"] = "development"
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    log_level: str = Field(default="INFO")
    log_format: Literal["console", "json"] = "console"
    call_session_ttl_seconds: int = Field(default=3600, ge=60)

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @field_validator("public_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("PUBLIC_BASE_URL must start with http:// or https://")
        return value

    @field_validator("otp_code")
    @classmethod
    def _otp_must_be_digits(cls, value: str) -> str:
        value = value.strip()
        if not value.isdigit():
            raise ValueError("OTP_CODE must contain digits only (e.g. 1234, or a birthdate in DDMM format)")
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def _check_otp_length_matches(self) -> Settings:
        if len(self.otp_code) != self.otp_length:
            raise ValueError(
                f"OTP_CODE has {len(self.otp_code)} digits but OTP_LENGTH is {self.otp_length}"
            )
        return self

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------
    @property
    def caller_number_e164(self) -> str:
        return normalize_phone_number(self.plivo_caller_number, self.default_country_code)

    @property
    def associate_number_e164(self) -> str:
        return normalize_phone_number(self.live_associate_number, self.default_country_code)

    @property
    def default_destination_e164(self) -> str | None:
        if not self.default_destination_number:
            return None
        return normalize_phone_number(self.default_destination_number, self.default_country_code)

    def webhook_url(self, path: str) -> str:
        """Build an absolute, publicly reachable callback URL for Plivo."""
        return f"{self.public_base_url}/{path.lstrip('/')}"


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings instance."""
    return Settings()  # type: ignore[call-arg]
