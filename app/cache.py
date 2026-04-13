"""Simple LRU cache for TTS results."""
from __future__ import annotations

import hashlib
from collections import OrderedDict


class LRUCache:
    """In-memory LRU cache keyed by (text, voice, rate)."""

    def __init__(self, maxsize: int):
        self._maxsize = maxsize
        self._cache: OrderedDict[str, tuple] = OrderedDict()

    def get(self, key: str):
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, value: tuple):
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)
        self._cache[key] = value

    def clear(self):
        self._cache.clear()

    def __len__(self):
        return len(self._cache)


def cache_key(text: str, voice: str, rate: str, volume: str = "+0%", pitch: str = "+0Hz") -> str:
    raw = f"{text}|{voice}|{rate}|{volume}|{pitch}"
    return hashlib.sha256(raw.encode()).hexdigest()
