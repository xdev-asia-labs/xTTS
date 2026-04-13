"""Simple in-memory rate limiter middleware — no external dependencies."""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Token-bucket rate limiter per client IP.
    Only applies to POST endpoints (TTS generation).
    """

    def __init__(self, app, max_requests: int = 30, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        if request.method != "POST":
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        cutoff = now - self.window_seconds

        # Clean old entries
        self._requests[client_ip] = [
            t for t in self._requests[client_ip] if t > cutoff
        ]

        if len(self._requests[client_ip]) >= self.max_requests:
            retry_after = int(
                self._requests[client_ip][0] + self.window_seconds - now
            ) + 1
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "detail": (
                        f"Max {self.max_requests} requests per "
                        f"{self.window_seconds}s. Retry after {retry_after}s."
                    ),
                },
                headers={"Retry-After": str(retry_after)},
            )

        self._requests[client_ip].append(now)
        return await call_next(request)
