"""Unit tests for cache and models — no network required."""
import pytest
from pydantic import ValidationError

from app.cache import LRUCache, cache_key
from app.models import TTSRequest


class TestLRUCache:
    def test_put_and_get(self):
        cache = LRUCache(3)
        cache.put("a", (b"audio", [], 1.0, 1))
        assert cache.get("a") == (b"audio", [], 1.0, 1)

    def test_evicts_oldest(self):
        cache = LRUCache(2)
        cache.put("a", (1,))
        cache.put("b", (2,))
        cache.put("c", (3,))  # evicts "a"
        assert cache.get("a") is None
        assert cache.get("b") == (2,)
        assert cache.get("c") == (3,)

    def test_access_refreshes_order(self):
        cache = LRUCache(2)
        cache.put("a", (1,))
        cache.put("b", (2,))
        cache.get("a")  # refresh "a"
        cache.put("c", (3,))  # evicts "b" (oldest)
        assert cache.get("a") == (1,)
        assert cache.get("b") is None

    def test_len(self):
        cache = LRUCache(5)
        assert len(cache) == 0
        cache.put("x", (1,))
        assert len(cache) == 1

    def test_clear(self):
        cache = LRUCache(5)
        cache.put("x", (1,))
        cache.clear()
        assert len(cache) == 0


class TestCacheKey:
    def test_deterministic(self):
        k1 = cache_key("hello", "vi-VN-HoaiMyNeural", "+0%")
        k2 = cache_key("hello", "vi-VN-HoaiMyNeural", "+0%")
        assert k1 == k2

    def test_different_for_different_inputs(self):
        k1 = cache_key("hello", "vi-VN-HoaiMyNeural", "+0%")
        k2 = cache_key("hello", "vi-VN-HoaiMyNeural", "+10%")
        assert k1 != k2

    def test_different_for_different_volume(self):
        k1 = cache_key("hello", "vi-VN-HoaiMyNeural", "+0%", "+0%")
        k2 = cache_key("hello", "vi-VN-HoaiMyNeural", "+0%", "+50%")
        assert k1 != k2

    def test_different_for_different_pitch(self):
        k1 = cache_key("hello", "vi-VN-HoaiMyNeural", "+0%", "+0%", "+0Hz")
        k2 = cache_key("hello", "vi-VN-HoaiMyNeural", "+0%", "+0%", "+50Hz")
        assert k1 != k2


class TestTTSRequestValidation:
    def test_valid_defaults(self):
        req = TTSRequest(text="Hello")
        assert req.voice == "vi-VN-HoaiMyNeural"
        assert req.rate == "+0%"
        assert req.volume == "+0%"
        assert req.pitch == "+0Hz"

    def test_valid_rate_formats(self):
        for rate in ["+0%", "-10%", "+50%", "-100%"]:
            req = TTSRequest(text="Hello", rate=rate)
            assert req.rate == rate

    def test_invalid_rate_format(self):
        with pytest.raises(ValidationError):
            TTSRequest(text="Hello", rate="fast")

    def test_valid_volume_formats(self):
        for vol in ["+0%", "-50%", "+100%"]:
            req = TTSRequest(text="Hello", volume=vol)
            assert req.volume == vol

    def test_invalid_volume_format(self):
        with pytest.raises(ValidationError):
            TTSRequest(text="Hello", volume="loud")

    def test_valid_pitch_formats(self):
        for pitch in ["+0Hz", "-50Hz", "+100Hz"]:
            req = TTSRequest(text="Hello", pitch=pitch)
            assert req.pitch == pitch

    def test_invalid_pitch_format(self):
        with pytest.raises(ValidationError):
            TTSRequest(text="Hello", pitch="high")

    def test_invalid_voice_format(self):
        with pytest.raises(ValidationError):
            TTSRequest(text="Hello", voice="invalid-voice")

    def test_valid_voice(self):
        req = TTSRequest(text="Hello", voice="en-US-GuyNeural")
        assert req.voice == "en-US-GuyNeural"
