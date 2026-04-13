"""API Key authentication middleware — optional, only active when API_KEY is set."""
from __future__ import annotations

import hmac
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger("xTTS")

# Paths that never require auth
_PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/metrics"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """
    Require X-API-Key header for all non-public endpoints.
    Disabled when api_key is empty/None.
    """

    def __init__(self, app, api_key: str | None = None):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        if not self.api_key:
            return await call_next(request)

        path = request.url.path

        # Allow public paths and static files
        if path in _PUBLIC_PATHS or path == "/":
            return await call_next(request)

        # Allow GET on static-like paths (Web UI assets)
        if request.method == "GET" and (
            path.endswith((".html", ".css", ".js", ".ico", ".png", ".svg"))
        ):
            return await call_next(request)

        provided = request.headers.get("X-API-Key", "")
        if not provided:
            provided = request.query_params.get("api_key", "")

        if not provided:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Missing API key",
                    "detail": "Provide X-API-Key header or ?api_key= param",
                },
            )

        if not hmac.compare_digest(provided, self.api_key):
            client_ip = request.client.host if request.client else "unknown"
            log.warning(f"Invalid API key from {client_ip}")
            return JSONResponse(
                status_code=403,
                content={"error": "Invalid API key"},
            )

        return await call_next(request)
