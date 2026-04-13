"""TTS API routes — POST /tts, POST /tts/stream."""
from __future__ import annotations

import base64
import io
import json
import time

from fastapi import APIRouter

from app.models import TTSRequest, TTSResponse
from app.tts_engine import generate_tts
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["TTS"])


@router.post("/tts", response_model=TTSResponse)
async def tts(req: TTSRequest):
    """Generate TTS audio (base64 JSON response)."""
    t0 = time.time()
    audio, captions, duration, num_chunks, cached = await generate_tts(
        req.text, req.voice, req.rate
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
        req.text, req.voice, req.rate
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
