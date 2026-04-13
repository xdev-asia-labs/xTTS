"""Text chunking and caption merging utilities."""
from __future__ import annotations

import re


def split_text_into_chunks(text: str, max_chars: int) -> list[str]:
    """Split long text into chunks respecting paragraph/sentence boundaries."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    result: list[str] = []
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


def merge_word_captions(
    words: list[dict],
    max_words: int = 6,
    max_gap_frames: int = 10,
) -> list[dict]:
    """Merge individual word boundaries into readable phrase captions."""
    if not words:
        return []

    merged: list[dict] = []
    buf_words: list[str] = []
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


def estimate_mp3_duration(data: bytes) -> float:
    """Quick estimate: file_size / bitrate. Assumes 48kbps (edge-tts default)."""
    return len(data) / (48 * 128)
