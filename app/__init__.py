"""
xTTS — Lightweight TTS microservice using edge-tts.

App factory: create_app() builds and configures the FastAPI application.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.auth import ApiKeyMiddleware
from app.config import settings
from app.metrics import MetricsMiddleware, router as metrics_router
from app.rate_limit import RateLimitMiddleware
from app.routes import system_router, tts_router
from app.tts_engine import tts_cache

log = logging.getLogger("xTTS")


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup: pre-warm voices cache. Shutdown: clear caches."""
    log.info("Starting xTTS — pre-warming voices cache...")
    from app import tts_engine
    from app.tts_engine import ensure_voices_loaded

    try:
        await ensure_voices_loaded()
        log.info(f"Loaded {len(tts_engine.voices_list)} voices")
    except Exception as e:
        log.warning(f"Failed to pre-warm voices: {e}")
    yield
    log.info("Shutting down xTTS — clearing caches")
    tts_cache.clear()


def create_app() -> FastAPI:
    """Build the FastAPI application with all middleware and routes."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    application = FastAPI(
        title="xTTS",
        version="1.1.0",
        description="Lightweight TTS microservice using edge-tts",
        docs_url="/docs",
        lifespan=lifespan,
    )

    # GZip compression
    application.add_middleware(GZipMiddleware, minimum_size=1000)

    # API Key auth (only active when API_KEY is set)
    if settings.api_key:
        application.add_middleware(ApiKeyMiddleware, api_key=settings.api_key)
        log.info("API key authentication enabled")

    # Prometheus metrics
    application.add_middleware(MetricsMiddleware)

    # CORS
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting
    application.add_middleware(
        RateLimitMiddleware,
        max_requests=settings.rate_limit_max,
        window_seconds=settings.rate_limit_window,
    )

    # Global error handler
    @application.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        log.error(
            f"Unhandled error on {request.method} {request.url.path}: {exc}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"},
        )

    # Routes
    application.include_router(system_router)
    application.include_router(tts_router)
    application.include_router(metrics_router)

    # Static files (Web UI)
    static_dir = Path(__file__).resolve().parent.parent / "static"
    if static_dir.is_dir():
        application.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return application
