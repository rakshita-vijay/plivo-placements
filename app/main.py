"""Application entry point.

Run locally with::

    uvicorn app.main:app --reload --port 8000

The application is built by a factory so tests can construct an isolated
instance with their own settings instead of importing a module-level singleton.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import Settings, get_settings
from app.core.logging_config import configure_logging
from app.dependencies import build_application_state
from app.routers import calls, health, ivr

logger = logging.getLogger(__name__)

STATIC_DIRECTORY = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Log the effective configuration on start-up and release it on shutdown."""
    settings: Settings = app.state.settings
    logger.info(
        "%s starting", settings.app_name,
        extra={
            "environment": settings.environment,
            "public_base_url": settings.public_base_url,
            "signature_verification": settings.validate_plivo_signature,
        },
    )
    if not settings.validate_plivo_signature:
        logger.warning(
            "Plivo signature verification is DISABLED. "
            "Do not run this way outside local development."
        )
    yield
    logger.info("%s shutting down", settings.app_name)


def create_application(settings: Settings | None = None) -> FastAPI:
    """Build and wire the FastAPI application."""
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)

    application = FastAPI(
        title=settings.app_name,
        description=(
            "Outbound calling with OTP authentication and a two-level IVR, "
            "built on Plivo's Voice API."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    for state_key, state_value in build_application_state(settings).items():
        setattr(application.state, state_key, state_value)

    application.include_router(health.router)
    application.include_router(calls.router)
    application.include_router(ivr.router)

    if STATIC_DIRECTORY.is_dir():
        application.mount(
            "/static", StaticFiles(directory=STATIC_DIRECTORY), name="static"
        )

        @application.get("/", include_in_schema=False)
        async def serve_control_panel() -> FileResponse:
            """Serve the single-page control panel."""
            return FileResponse(STATIC_DIRECTORY / "index.html")

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        """Never leak a stack trace to a caller — or to Plivo."""
        logger.exception("Unhandled error on %s", request.url.path, exc_info=error)
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error"}
        )

    return application


def __getattr__(name: str) -> FastAPI:
    """Build the default application only when ``app.main:app`` is asked for.

    Deferring construction keeps ``import app.main`` side-effect free, so tests
    (and tooling that merely imports the module) do not need a populated
    environment. ``uvicorn app.main:app`` still works unchanged.
    """
    if name == "app":
        return create_application()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
