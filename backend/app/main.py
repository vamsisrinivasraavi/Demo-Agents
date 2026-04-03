"""
FastAPI application factory.

Responsibilities:
- App lifespan (startup/shutdown of external clients)
- CORS configuration
- Global exception handling (maps AppException → JSON responses)
- Request middleware (correlation IDs, timing)
- Router registration
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.dependencies import init_clients, shutdown_clients
from app.core.exceptions import AppException
from app.core.logging import (
    get_logger,
    set_correlation_id,
    setup_logging,
)

from app.seed_admin import seed_admin

logger = get_logger(__name__)


# ──────────────────────────────────────────────
# Lifespan
# ──────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manages startup and shutdown of all external connections.
    Replaces the deprecated @app.on_event pattern.
    """
    settings = get_settings()

    # Startup
    setup_logging()
    logger.info(
        "app.starting",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
    )
    await init_clients(settings)

    # 🔥 Seed admin safely inside event loop
    try:
        await seed_admin("admin@gmail.com", "admin@123", "admin")
        logger.info("admin.seeded")
    except Exception as e:
        logger.warning("admin.seed_failed", error=str(e))

    logger.info("app.started")

    yield

    # Shutdown
    logger.info("app.shutting_down")
    await shutdown_clients()
    logger.info("app.stopped")


# ──────────────────────────────────────────────
# App Factory
# ──────────────────────────────────────────────


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        debug=settings.DEBUG,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.ENVIRONMENT != "production" else None,
        redoc_url="/api/redoc" if settings.ENVIRONMENT != "production" else None,
        openapi_url="/api/openapi.json" if settings.ENVIRONMENT != "production" else None,
    )

    # ── CORS ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.ENVIRONMENT != "production" else settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Middleware: Correlation ID + Request Logging ──
    @app.middleware("http")
    async def request_middleware(request: Request, call_next):
        """Attach correlation ID and log request lifecycle."""
        # Use incoming header or generate new
        cid = request.headers.get("X-Correlation-ID")
        cid = set_correlation_id(cid)

        logger.info(
            "request.start",
            method=request.method,
            path=request.url.path,
            client=request.client.host if request.client else "unknown",
        )

        import time
        start = time.perf_counter()

        response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "request.end",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(elapsed_ms, 2),
        )

        response.headers["X-Correlation-ID"] = cid
        response.headers["X-Response-Time-Ms"] = str(round(elapsed_ms, 2))

        return response

    # ── Exception Handlers ──

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        """Convert domain exceptions to structured JSON error responses."""
        logger.warning(
            "app.exception",
            error_code=exc.error_code,
            detail=exc.detail,
            path=request.url.path,
            context=exc.context,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.error_code,
                    "message": exc.detail,
                    "context": exc.context if settings.DEBUG else {},
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """Catch-all for unexpected errors. Logs full traceback."""
        logger.exception(
            "app.unhandled_exception",
            path=request.url.path,
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred"
                    if not settings.DEBUG
                    else str(exc),
                }
            },
        )

    # ── Health Check ──
    @app.get("/health", tags=["system"])
    async def health_check():
        return {
            "status": "healthy",
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        }

    # ── Register Routers ──
    from app.routers import admin, auth, user

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
    app.include_router(user.router, prefix="/api/user", tags=["user"])

    return app


# ──────────────────────────────────────────────
# ASGI Entry Point
# ──────────────────────────────────────────────
# Run with: uvicorn app.main:app --reload
app = create_app()