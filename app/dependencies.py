"""Dependency wiring.

Singletons are built once at import time and handed to routers through FastAPI's
dependency system. Tests override these providers to inject fakes, which is why
the routers never construct their collaborators directly.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.core.security import PlivoSignatureVerifier
from app.ivr.xml_builder import IvrXmlBuilder
from app.services.call_session_store import CallSessionStore, InMemoryCallSessionStore
from app.services.otp_verifier import OtpVerifier
from app.services.plivo_call_service import PlivoCallService


def get_app_settings(request: Request) -> Settings:
    """Settings bound to *this* application instance, not the process env.

    Reading from ``app.state`` rather than the module-level cache is what lets
    tests build an isolated application with their own configuration.
    """
    return request.app.state.settings


def get_call_session_store(request: Request) -> CallSessionStore:
    """Session storage. Swap :class:`InMemoryCallSessionStore` for Redis here."""
    return request.app.state.call_session_store


def get_xml_builder(request: Request) -> IvrXmlBuilder:
    return request.app.state.xml_builder


def get_otp_verifier(request: Request) -> OtpVerifier:
    return request.app.state.otp_verifier


def get_signature_verifier(request: Request) -> PlivoSignatureVerifier:
    return request.app.state.signature_verifier


def get_plivo_call_service(request: Request) -> PlivoCallService:
    return request.app.state.plivo_call_service


def build_application_state(settings: Settings) -> dict[str, object]:
    """Construct every long-lived collaborator the application needs."""
    return {
        "settings": settings,
        "call_session_store": InMemoryCallSessionStore(
            ttl_seconds=settings.call_session_ttl_seconds
        ),
        "xml_builder": IvrXmlBuilder(settings),
        "otp_verifier": OtpVerifier(
            expected_code=settings.otp_code, code_length=settings.otp_length
        ),
        "signature_verifier": PlivoSignatureVerifier(
            auth_token=settings.plivo_auth_token,
            enabled=settings.validate_plivo_signature,
        ),
        "plivo_call_service": PlivoCallService(settings),
    }


SettingsDependency = Annotated[Settings, Depends(get_app_settings)]
SessionStoreDependency = Annotated[CallSessionStore, Depends(get_call_session_store)]
XmlBuilderDependency = Annotated[IvrXmlBuilder, Depends(get_xml_builder)]
OtpVerifierDependency = Annotated[OtpVerifier, Depends(get_otp_verifier)]
SignatureVerifierDependency = Annotated[
    PlivoSignatureVerifier, Depends(get_signature_verifier)
]
CallServiceDependency = Annotated[PlivoCallService, Depends(get_plivo_call_service)]
