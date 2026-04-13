"""System routes — /health, /stats, /voices."""
from __future__ import annotations

import time

import edge_tts
from fastapi import APIRouter

from app.config import settings
from app import tts_engine
from app.tts_engine import ensure_voices_loaded, stats, tts_cache

router = APIRouter(tags=["System"])

_start_time = time.time()


@router.get("/health")
async def health():
    return {
        "ok": True,
        "version": "1.1.0",
        "uptime": int(time.time() - _start_time),
        "edge_tts": getattr(edge_tts, "__version__", "unknown"),
        "cache_size": len(tts_cache),
        "voices_loaded": len(tts_engine.voices_list) if tts_engine.voices_list else 0,
    }


@router.get("/stats")
async def get_stats():
    return {
        **stats,
        "uptime": int(time.time() - _start_time),
        "cache_entries": len(tts_cache),
        "cache_max": settings.tts_cache_size,
    }


@router.get("/voices")
async def list_voices(lang: str = "vi"):
    await ensure_voices_loaded()
    filtered = [v for v in tts_engine.voices_list if v["Locale"].startswith(lang)]
    return {"voices": filtered, "total": len(filtered)}
