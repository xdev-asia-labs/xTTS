"""Core TTS engine — generates audio and captions from text using edge-tts."""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging

import edge_tts
from fastapi import HTTPException

from app.cache import LRUCache, cache_key
from app.config import settings
from app.models import Caption
from app.text_utils import estimate_mp3_duration, merge_word_captions, split_text_into_chunks

log = logging.getLogger("xTTS")

# ── Shared state ────────────────────────────────────────────────────────────
tts_cache = LRUCache(settings.tts_cache_size)

stats = {
    "requests_total": 0,
    "requests_ok": 0,
    "requests_error": 0,
    "chars_processed": 0,
    "audio_bytes_generated": 0,
    "cache_hits": 0,
    "cache_misses": 0,
}

# Voices cache
voices_list: list | None = None
voice_names: set[str] = set()


async def ensure_voices_loaded():
    """Ensure voices list is loaded for validation."""
    global voices_list, voice_names
    if voices_list is None:
        voices_list = await edge_tts.list_voices()
        voice_names = {v["ShortName"] for v in voices_list}


async def validate_voice(voice: str):
    """Check if the requested voice exists."""
    await ensure_voices_loaded()
    if voice_names and voice not in voice_names:
        raise HTTPException(
            400,
            f"Unknown voice '{voice}'. Use GET /voices to list available voices.",
        )


# ── Core generation ─────────────────────────────────────────────────────────
async def generate_tts(
    text: str,
    voice: str,
    rate: str,
) -> tuple[bytes, list[Caption], float, int, bool]:
    """
    Returns (audio_bytes, captions, duration_seconds, num_chunks, from_cache).
    """
    text = text.strip()
    if not text:
        raise HTTPException(400, "Empty text")
    if len(text) > settings.tts_max_text_length:
        raise HTTPException(
            400,
            f"Text too long ({len(text)} > {settings.tts_max_text_length})",
        )

    await validate_voice(voice)
    stats["requests_total"] += 1

    # Check cache
    ckey = cache_key(text, voice, rate)
    cached = tts_cache.get(ckey)
    if cached is not None:
        stats["cache_hits"] += 1
        audio_bytes, captions, duration, num_chunks = cached
        return audio_bytes, captions, duration, num_chunks, True

    stats["cache_misses"] += 1

    job_id = hashlib.md5(text.encode()).hexdigest()[:8]
    log.info(f"[{job_id}] TTS: {len(text)} chars, voice={voice}")

    chunks = split_text_into_chunks(text, settings.tts_max_chunk)
    log.info(f"[{job_id}] {len(chunks)} chunks")

    semaphore = asyncio.Semaphore(settings.tts_concurrency)
    tasks = [
        _process_chunk(semaphore, chunks[i], i, len(chunks), voice, rate, job_id)
        for i in range(len(chunks))
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, r in enumerate(results):
        if isinstance(r, Exception):
            stats["requests_error"] += 1
            log.error(f"[{job_id}] Chunk {i+1} failed: {r}")
            raise HTTPException(500, f"TTS failed on chunk {i+1}/{len(chunks)}: {r}")

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
        time_offset_frames += round(chunk_duration * settings.fps)

    combined_audio = b"".join(audio_parts)
    total_duration = time_offset_frames / settings.fps

    stats["requests_ok"] += 1
    stats["chars_processed"] += len(text)
    stats["audio_bytes_generated"] += len(combined_audio)

    tts_cache.put(ckey, (combined_audio, all_captions, total_duration, len(chunks)))

    log.info(
        f"[{job_id}] Done — "
        f"{len(all_captions)} captions, {len(combined_audio)//1024}KB, {total_duration:.1f}s audio"
    )

    return combined_audio, all_captions, total_duration, len(chunks), False


# ── Process single chunk with retries ───────────────────────────────────────
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
        for attempt in range(1, settings.tts_max_retries + 1):
            try:
                if attempt > 1:
                    await asyncio.sleep(attempt * 1.5)
                    log.info(
                        f"[{job_id}] Chunk {idx+1}/{total}: retry {attempt}/{settings.tts_max_retries}"
                    )

                communicate = edge_tts.Communicate(text, voice, rate=rate)
                audio_buf = io.BytesIO()
                captions: list[dict] = []

                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_buf.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        offset_ms = chunk["offset"] / 10_000  # 100ns → ms
                        duration_ms = chunk["duration"] / 10_000
                        captions.append({
                            "startFrame": round(offset_ms / 1000 * settings.fps),
                            "endFrame": round(
                                (offset_ms + duration_ms) / 1000 * settings.fps
                            ),
                            "text": chunk["text"],
                        })

                audio_data = audio_buf.getvalue()
                if len(audio_data) < 100:
                    raise ValueError("No audio data received")

                merged = merge_word_captions(
                    captions,
                    max_words=settings.caption_max_words,
                    max_gap_frames=settings.caption_max_gap_frames,
                )
                duration = estimate_mp3_duration(audio_data)

                log.info(
                    f"[{job_id}] Chunk {idx+1}/{total}: OK "
                    f"({len(audio_data)} bytes, {duration:.1f}s)"
                )
                return audio_data, merged, duration

            except Exception as e:
                last_err = e
                log.warning(
                    f"[{job_id}] Chunk {idx+1}/{total} attempt {attempt}: {e}"
                )

        raise RuntimeError(f"Failed after {settings.tts_max_retries} retries: {last_err}")
