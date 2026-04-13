"""Request/Response Pydantic models."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

RATE_PATTERN = re.compile(r"^[+-]\d{1,3}%$")
VOLUME_PATTERN = re.compile(r"^[+-]\d{1,3}%$")
PITCH_PATTERN = re.compile(r"^[+-]\d{1,3}Hz$")


class TTSRequest(BaseModel):
    text: str
    voice: str = "vi-VN-HoaiMyNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"

    @field_validator("rate")
    @classmethod
    def validate_rate(cls, v: str) -> str:
        if not RATE_PATTERN.match(v):
            raise ValueError(
                f"Invalid rate format '{v}'. Expected: +0%, -10%, +50%, etc."
            )
        return v

    @field_validator("volume")
    @classmethod
    def validate_volume(cls, v: str) -> str:
        if not VOLUME_PATTERN.match(v):
            raise ValueError(
                f"Invalid volume format '{v}'. Expected: +0%, -50%, +100%, etc."
            )
        return v

    @field_validator("pitch")
    @classmethod
    def validate_pitch(cls, v: str) -> str:
        if not PITCH_PATTERN.match(v):
            raise ValueError(
                f"Invalid pitch format '{v}'. Expected: +0Hz, -50Hz, +100Hz, etc."
            )
        return v

    @field_validator("voice")
    @classmethod
    def validate_voice_format(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z]{2}-[A-Z]{2}-\w+$", v):
            raise ValueError(
                f"Invalid voice format '{v}'. Expected: xx-XX-NameNeural"
            )
        return v


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
    cached: bool = False
