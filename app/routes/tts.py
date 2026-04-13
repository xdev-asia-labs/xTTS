"""TTS API routes — POST /tts, POST /tts/stream, POST /tts/async."""
from __future__ import annotations

import base64
import io
import json
import logging
import time
import uuid

import httpx
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse

from app.models import TTSAsyncRequest, TTSRequest, TTSResponse
from app.tts_engine import generate_tts

log = logging.getLogger("xTTS")
router = APIRouter(tags=["TTS"])

# In-memory job tracking
_jobs: dict[str, dict] = {}


@router.post("/tts", response_model=TTSResponse)
async def tts(req: TTSRequest):
    """Generate TTS audio (base64 JSON response)."""
    t0 = time.time()
    audio, captions, duration, num_chunks, cached = await generate_tts(
        req.text, req.voice, req.rate, req.volume, req.pitch, req.ssml
    )
    elapsed = round(time.time() - t0, 3)

    return TTSResponse(
        audio=base64.b64encode(audio).decode(),
        audioSize=len(audio),
        captions=captions,
        durationSeconds=round(duration, 2),
        chunks=num_chunks,
        elapsed=elapsed,
        cached=cached,
    )


@router.post("/tts/stream")
async def tts_stream(req: TTSRequest):
    """Generate TTS audio (raw MP3 stream — ideal for browser <audio>)."""
    audio, captions, duration, num_chunks, cached = await generate_tts(
        req.text, req.voice, req.rate, req.volume, req.pitch, req.ssml
    )

    captions_json = json.dumps(
        [c.model_dump() for c in captions],
        ensure_ascii=False,
    )

    return StreamingResponse(
        io.BytesIO(audio),
        media_type="audio/mpeg",
        headers={
            "Content-Length": str(len(audio)),
            "X-Duration-Seconds": str(round(duration, 2)),
            "X-Captions": base64.b64encode(captions_json.encode()).decode(),
            "X-Chunks": str(num_chunks),
            "X-Cached": str(cached).lower(),
            "Content-Disposition": 'inline; filename="speech.mp3"',
        },
    )


# ── Async TTS with webhook callback ────────────────────────────────────────

async def _run_async_tts(job_id: str, req: TTSAsyncRequest):
    """Background task: generate TTS and POST result to callback_url."""
    _jobs[job_id]["status"] = "processing"
    try:
        t0 = time.time()
        audio, captions, duration, num_chunks, cached = await generate_tts(
            req.text, req.voice, req.rate, req.volume, req.pitch, req.ssml
        )
        elapsed = round(time.time() - t0, 3)

        result = {
            "job_id": job_id,
            "status": "completed",
            "audio": base64.b64encode(audio).decode(),
            "audioFormat": "mp3",
            "audioSize": len(audio),
            "captions": [c.model_dump() for c in captions],
            "durationSeconds": round(duration, 2),
            "chunks": num_chunks,
            "elapsed": elapsed,
            "cached": cached,
        }
        _jobs[job_id] = {"status": "completed", "elapsed": elapsed}

        if req.callback_url:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(req.callback_url, json=result)
                log.info(f"[{job_id}] Callback sent to {req.callback_url}")
            except Exception as e:
                log.warning(f"[{job_id}] Callback failed: {e}")

    except Exception as e:
        _jobs[job_id] = {"status": "failed", "error": str(e)}
        log.error(f"[{job_id}] Async TTS failed: {e}")

        if req.callback_url:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(req.callback_url, json={
                        "job_id": job_id, "status": "failed", "error": str(e)
                    })
            except Exception:
                pass


@router.post("/tts/async")
async def tts_async(req: TTSAsyncRequest, background_tasks: BackgroundTasks):
    """Submit TTS job for async processing. Optionally receive result via webhook."""
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {"status": "queued"}
    background_tasks.add_task(_run_async_tts, job_id, req)
    return {
        "job_id": job_id,
        "status": "queued",
        "poll_url": f"/tts/async/{job_id}",
        "callback_url": req.callback_url,
    }


@router.get("/tts/async/{job_id}")
async def tts_async_status(job_id: str):
    """Check status of an async TTS job."""
    if job_id not in _jobs:
        return {"job_id": job_id, "status": "not_found"}
    return {"job_id": job_id, **_jobs[job_id]}
