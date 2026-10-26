"""FastAPI application entry point."""

import logging
import re
import threading
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from sentinelflow import __version__
from sentinelflow.ai.model_client import ModelNotConfiguredError
from sentinelflow.api.routes.alerts import router as alerts_router
from sentinelflow.api.routes.audit import router as audit_router
from sentinelflow.api.routes.auth import router as auth_router
from sentinelflow.api.routes.detections import router as detections_router
from sentinelflow.api.routes.events import router as events_router
from sentinelflow.api.routes.health import router as health_router
from sentinelflow.api.routes.investigations import router as investigations_router
from sentinelflow.api.routes.reports import router as reports_router
from sentinelflow.core.config import get_settings
from sentinelflow.core.security import AuthConfigurationError
from sentinelflow.db.session import get_session_factory
from sentinelflow.services.investigation_worker import run_worker

logger = logging.getLogger(__name__)
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        """Run the investigation queue worker for the lifetime of the process.

        The worker is a single thread polling a database table. Tests disable it
        with ``AGENT_WORKER_ENABLED=false`` and drain the queue explicitly, so
        they never depend on thread timing.
        """
        stop_event = threading.Event()
        worker: threading.Thread | None = None
        if get_settings().agent_worker_enabled:
            factory = getattr(application.state, "session_factory", None)
            factory = factory or get_session_factory()
            worker = threading.Thread(
                target=run_worker,
                kwargs={"stop_event": stop_event, "session_factory": factory},
                name="investigation-worker",
                daemon=True,
            )
            worker.start()
            logger.info("Investigation worker started")
        try:
            yield
        finally:
            stop_event.set()
            if worker is not None:
                worker.join(timeout=5)
                logger.info("Investigation worker stopped")

    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        description=(
            "AI-assisted security event triage and response platform. This "
            "deterministic build imports events, runs the AUTH-001 rule, and "
            "generates investigation reports without an LLM."
        ),
    )
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(events_router)
    application.include_router(detections_router)
    application.include_router(alerts_router)
    application.include_router(reports_router)
    application.include_router(investigations_router)
    application.include_router(audit_router)

    @application.middleware("http")
    async def enforce_request_body_size(request: Request, call_next):
        """Reject oversized bodies before they are parsed.

        Only the declared Content-Length is checked. A client that streams a
        body without declaring it is out of scope; a reverse proxy must enforce
        the same limit in front of the app.
        """
        limit = get_settings().max_request_body_bytes
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                size = int(declared)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header"},
                )
            if size > limit:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large"},
                )
        return await call_next(request)

    @application.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID")
        if request_id is None or not _REQUEST_ID_PATTERN.fullmatch(request_id):
            request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Do not echo client input: validation errors can otherwise expose
        # passwords or other sensitive values.
        errors = [
            {
                "type": error.get("type", "validation_error"),
                "loc": list(error.get("loc", [])),
                "msg": error.get("msg", "Invalid input"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    @application.exception_handler(AuthConfigurationError)
    async def handle_auth_configuration_error(
        request: Request, exc: AuthConfigurationError
    ) -> JSONResponse:
        logger.error(
            "Authentication configuration error while handling %s %s: %s",
            request.method,
            request.url.path,
            exc,
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "Authentication is not configured"},
        )

    @application.exception_handler(ModelNotConfiguredError)
    async def handle_model_not_configured(
        request: Request, exc: ModelNotConfiguredError
    ) -> JSONResponse:
        logger.warning(
            "Agent model is not configured while handling %s %s",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "AI agent is not configured"},
        )

    @application.exception_handler(SQLAlchemyError)
    async def handle_database_error(
        request: Request, exc: SQLAlchemyError
    ) -> JSONResponse:
        logger.exception(
            "Database error while handling %s %s", request.method, request.url.path
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Database operation failed"},
        )

    return application


app = create_app()
