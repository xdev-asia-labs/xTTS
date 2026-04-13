"""
Centralized configuration via pydantic-settings.
Reads from environment variables (or .env file).
"""
from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server
    port: int = 3099
    log_level: str = "info"

    # TTS
    tts_max_chunk: int = 500
    tts_max_retries: int = 3
    tts_max_text_length: int = 20000
    tts_default_voice: str = "vi-VN-HoaiMyNeural"
    tts_default_rate: str = "+0%"
    tts_concurrency: int = 2

    # Cache
    tts_cache_size: int = 100

    # CORS
    tts_cors_origins: str = "*"

    # Rate limiting (POST endpoints only)
    rate_limit_max: int = 30
    rate_limit_window: int = 60

    # Auth (optional — leave empty to disable)
    api_key: str = ""

    # TTS timeout per chunk (seconds)
    tts_timeout: int = 30

    # Captions
    fps: int = 30
    caption_max_words: int = 6
    caption_max_gap_frames: int = 10

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.tts_cors_origins.split(",")]


settings = Settings()
