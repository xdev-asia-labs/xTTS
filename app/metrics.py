"""Prometheus metrics — exposes /metrics endpoint."""
from __future__ import annotations

import time

from fastapi import APIRouter, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

router = APIRouter(tags=["Metrics"])

# ── Simple counters (no external dependency) ────────────────────────────────
_metrics = {
    "http_requests_total": {},       # {method_path_status: count}
    "http_request_duration_seconds": {},  # {method_path: [sum, count]}
    "tts_requests_total": 0,
    "tts_requests_ok": 0,
    "tts_requests_error": 0,
    "tts_chars_processed": 0,
    "tts_audio_bytes_generated": 0,
    "tts_cache_hits": 0,
    "tts_cache_misses": 0,
}


class MetricsMiddleware(BaseHTTPMiddleware):
    """Track HTTP request counts and duration."""

    async def dispatch(self, request: Request, call_next):
        t0 = time.time()
        response = await call_next(request)
        elapsed = time.time() - t0

        method = request.method
        path = request.url.path
        status = response.status_code

        # Request count
        key = f'{method}|{path}|{status}'
        _metrics["http_requests_total"][key] = _metrics["http_requests_total"].get(key, 0) + 1

        # Duration
        dkey = f'{method}|{path}'
        if dkey not in _metrics["http_request_duration_seconds"]:
            _metrics["http_request_duration_seconds"][dkey] = [0.0, 0]
        _metrics["http_request_duration_seconds"][dkey][0] += elapsed
        _metrics["http_request_duration_seconds"][dkey][1] += 1

        return response


def sync_tts_stats():
    """Pull latest stats from tts_engine."""
    from app.tts_engine import stats
    _metrics["tts_requests_total"] = stats["requests_total"]
    _metrics["tts_requests_ok"] = stats["requests_ok"]
    _metrics["tts_requests_error"] = stats["requests_error"]
    _metrics["tts_chars_processed"] = stats["chars_processed"]
    _metrics["tts_audio_bytes_generated"] = stats["audio_bytes_generated"]
    _metrics["tts_cache_hits"] = stats["cache_hits"]
    _metrics["tts_cache_misses"] = stats["cache_misses"]


@router.get("/metrics")
async def prometheus_metrics():
    """Prometheus-compatible /metrics endpoint (text exposition format)."""
    sync_tts_stats()
    lines: list[str] = []

    # HTTP request counters
    lines.append("# HELP xtts_http_requests_total Total HTTP requests")
    lines.append("# TYPE xtts_http_requests_total counter")
    for key, count in sorted(_metrics["http_requests_total"].items()):
        method, path, status = key.split("|")
        lines.append(
            f'xtts_http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}'
        )

    # HTTP duration
    lines.append("# HELP xtts_http_request_duration_seconds HTTP request duration")
    lines.append("# TYPE xtts_http_request_duration_seconds summary")
    for key, (total, count) in sorted(_metrics["http_request_duration_seconds"].items()):
        method, path = key.split("|")
        lines.append(
            f'xtts_http_request_duration_seconds_sum{{method="{method}",path="{path}"}} {total:.4f}'
        )
        lines.append(
            f'xtts_http_request_duration_seconds_count{{method="{method}",path="{path}"}} {count}'
        )

    # TTS counters
    for name in [
        "tts_requests_total", "tts_requests_ok", "tts_requests_error",
        "tts_chars_processed", "tts_audio_bytes_generated",
        "tts_cache_hits", "tts_cache_misses",
    ]:
        lines.append(f"# HELP xtts_{name} {name.replace('_', ' ')}")
        lines.append(f"# TYPE xtts_{name} counter")
        lines.append(f"xtts_{name} {_metrics[name]}")

    lines.append("")
    return Response(content="\n".join(lines), media_type="text/plain; charset=utf-8")
