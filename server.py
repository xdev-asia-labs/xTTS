#!/usr/bin/env python3
"""
xTTS — Lightweight TTS microservice using edge-tts
Calls edge-tts Python library directly (no subprocess) for maximum speed.

POST /tts  { text, voice?, rate? }
  → { audio: base64, captions: [...], durationSeconds, chunks, elapsed }

GET  /health  → service status
GET  /voices  → available voices

Env:
  PORT=3099
  TTS_MAX_CHUNK=500        max chars per chunk
  TTS_MAX_RETRIES=3        retries per chunk on transient errors
  TTS_MAX_TEXT_LENGTH=20000 max input text length
"""
import asyncio
import base64
import hashlib
import io
import logging
import os
import re
import struct
import tempfile
import time
from pathlib import Path

import edge_tts
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ── Config ──────────────────────────────────────────────────────────────────
PORT = int(os.getenv("PORT", "3099"))
MAX_CHUNK = int(os.getenv("TTS_MAX_CHUNK", "500"))
MAX_RETRIES = int(os.getenv("TTS_MAX_RETRIES", "3"))
MAX_TEXT_LENGTH = int(os.getenv("TTS_MAX_TEXT_LENGTH", "20000"))
FPS = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("xTTS")

app = FastAPI(title="xTTS", version="1.0.0", docs_url="/docs")


# ── Models ──────────────────────────────────────────────────────────────────
class TTSRequest(BaseModel):
    text: str
    voice: str = "vi-VN-HoaiMyNeural"
    rate: str = "+0%"


class Caption(BaseModel):
    startFrame: int
    endFrame: int
    text: str


class TTSResponse(BaseModel):
    audio: str = Field(description="Base64-encoded MP3")
    audioFormat: str = "mp3"
    audioSize: int
    captions: list[Caption]
    durationSeconds: float
    chunks: int
    elapsed: float


# ── Health ──────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "ok": True,
        "version": "1.0.0",
        "uptime": int(time.time() - _start_time),
        "edge_tts": edge_tts.__version__ if hasattr(edge_tts, "__version__") else "unknown",
    }


_start_time = time.time()


# ── Voices ──────────────────────────────────────────────────────────────────
_voices_cache: list | None = None


@app.get("/voices")
async def list_voices(lang: str = "vi"):
    global _voices_cache
    if _voices_cache is None:
        _voices_cache = await edge_tts.list_voices()
    filtered = [v for v in _voices_cache if v["Locale"].startswith(lang)]
    return {"voices": filtered}


# ── Main TTS endpoint ──────────────────────────────────────────────────────
@app.post("/tts", response_model=TTSResponse)
async def tts(req: TTSRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Empty text")
    if len(text) > MAX_TEXT_LENGTH:
        raise HTTPException(400, f"Text too long ({len(text)} > {MAX_TEXT_LENGTH})")

    job_id = hashlib.md5(text.encode()).hexdigest()[:8]
    t0 = time.time()
    log.info(f"[{job_id}] TTS: {len(text)} chars, voice={req.voice}")

    # Split into chunks
    chunks = split_text_into_chunks(text, MAX_CHUNK)
    log.info(f"[{job_id}] {len(chunks)} chunks")

    # Process chunks concurrently (2 at a time to avoid rate limit)
    semaphore = asyncio.Semaphore(2)
    tasks = [
        _process_chunk(semaphore, chunks[i], i, len(chunks), req.voice, req.rate, job_id)
        for i in range(len(chunks))
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Check for errors
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            log.error(f"[{job_id}] Chunk {i+1} failed: {r}")
            raise HTTPException(500, f"TTS failed on chunk {i+1}/{len(chunks)}: {r}")

    # Concatenate MP3 data
    audio_parts: list[bytes] = []
    all_captions: list[Caption] = []
    time_offset_frames = 0

    for chunk_audio, chunk_captions, chunk_duration in results:
        audio_parts.append(chunk_audio)
        for cap in chunk_captions:
            all_captions.append(Caption(
                startFrame=cap["startFrame"] + time_offset_frames,
                endFrame=cap["endFrame"] + time_offset_frames,
                text=cap["text"],
            ))
        time_offset_frames += round(chunk_duration * FPS)

    combined_audio = b"".join(audio_parts)
    total_duration = time_offset_frames / FPS
    elapsed = round(time.time() - t0, 1)

    log.info(
        f"[{job_id}] Done in {elapsed}s — "
        f"{len(all_captions)} captions, {len(combined_audio)//1024}KB, {total_duration:.1f}s audio"
    )

    return TTSResponse(
        audio=base64.b64encode(combined_audio).decode(),
        audioSize=len(combined_audio),
        captions=all_captions,
        durationSeconds=round(total_duration, 2),
        chunks=len(chunks),
        elapsed=elapsed,
    )


# ── Process single chunk with retries ──────────────────────────────────────
async def _process_chunk(
    sem: asyncio.Semaphore,
    text: str,
    idx: int,
    total: int,
    voice: str,
    rate: str,
    job_id: str,
) -> tuple[bytes, list[dict], float]:
    """Returns (mp3_bytes, captions_list, duration_seconds)."""
    async with sem:
        last_err = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if attempt > 1:
                    await asyncio.sleep(attempt * 1.5)
                    log.info(f"[{job_id}] Chunk {idx+1}/{total}: retry {attempt}/{MAX_RETRIES}")

                communicate = edge_tts.Communicate(text, voice, rate=rate)
                audio_buf = io.BytesIO()
                captions = []

                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_buf.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        offset_ms = chunk["offset"] / 10_000  # 100ns → ms
                        duration_ms = chunk["duration"] / 10_000
                        captions.append({
                            "startFrame": round(offset_ms / 1000 * FPS),
                            "endFrame": round((offset_ms + duration_ms) / 1000 * FPS),
                            "text": chunk["text"],
                        })

                audio_data = audio_buf.getvalue()
                if len(audio_data) < 100:
                    raise ValueError("No audio data received")

                # Merge word-level captions into phrase-level (~3-5 words)
                merged = _merge_word_captions(captions)
                duration = _estimate_mp3_duration(audio_data)

                log.info(f"[{job_id}] Chunk {idx+1}/{total}: OK ({len(audio_data)} bytes, {duration:.1f}s)")
                return audio_data, merged, duration

            except Exception as e:
                last_err = e
                log.warning(f"[{job_id}] Chunk {idx+1}/{total} attempt {attempt}: {e}")

        raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {last_err}")


# ── Merge word-level captions into phrases ─────────────────────────────────
def _merge_word_captions(words: list[dict], max_words: int = 6, max_gap_frames: int = 10) -> list[dict]:
    """Merge individual word boundaries into readable phrase captions."""
    if not words:
        return []

    merged = []
    buf_words = []
    buf_start = words[0]["startFrame"]
    buf_end = words[0]["endFrame"]

    for w in words:
        gap = w["startFrame"] - buf_end if buf_end else 0
        if len(buf_words) >= max_words or (gap > max_gap_frames and buf_words):
            merged.append({
                "startFrame": buf_start,
                "endFrame": buf_end,
                "text": " ".join(buf_words),
            })
            buf_words = []
            buf_start = w["startFrame"]

        buf_words.append(w["text"])
        buf_end = w["endFrame"]

    if buf_words:
        merged.append({
            "startFrame": buf_start,
            "endFrame": buf_end,
            "text": " ".join(buf_words),
        })

    return merged


# ── Estimate MP3 duration from raw bytes ───────────────────────────────────
def _estimate_mp3_duration(data: bytes) -> float:
    """Quick estimate: file_size / bitrate. Good enough for concat offset."""
    # Assume 48kbps (edge-tts default for Vietnamese)
    # More accurate: parse MPEG frames, but overkill here
    return len(data) / (48 * 128)  # bytes / (kbps * 128) = seconds


# ── Text chunking ──────────────────────────────────────────────────────────
def split_text_into_chunks(text: str, max_chars: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    result = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chars and current:
            result.append(current.strip())
            current = ""

        if len(para) > max_chars:
            if current:
                result.append(current.strip())
                current = ""
            # Split by sentences
            sentences = re.split(r"(?<=[.!?。])\s+", para)
            buf = ""
            for s in sentences:
                if len(buf) + len(s) + 1 > max_chars and buf:
                    result.append(buf.strip())
                    buf = ""
                buf += (" " if buf else "") + s
            if buf:
                result.append(buf.strip())
        else:
            current += ("\n\n" if current else "") + para

    if current.strip():
        result.append(current.strip())

    return result if result else [text]


# ── Entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info(f"Starting xTTS on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
