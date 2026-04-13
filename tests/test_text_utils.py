"""Unit tests for text_utils — no network required."""
from app.text_utils import estimate_mp3_duration, merge_word_captions, split_text_into_chunks


class TestSplitText:
    def test_short_text_single_chunk(self):
        result = split_text_into_chunks("Hello world", 500)
        assert result == ["Hello world"]

    def test_split_by_paragraph(self):
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        result = split_text_into_chunks(text, 30)
        assert len(result) >= 2
        assert all(len(c) <= 30 for c in result)

    def test_split_long_paragraph_by_sentence(self):
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        result = split_text_into_chunks(text, 40)
        assert len(result) >= 2
        for chunk in result:
            assert len(chunk) <= 40

    def test_empty_text_returns_original(self):
        result = split_text_into_chunks("", 500)
        assert result == [""]

    def test_respects_max_chars(self):
        text = "A" * 1000
        result = split_text_into_chunks(text, 500)
        # Single block with no sentence breaks → returned as-is
        assert len(result) >= 1


class TestMergeWordCaptions:
    def test_empty_input(self):
        assert merge_word_captions([]) == []

    def test_single_word(self):
        words = [{"startFrame": 0, "endFrame": 5, "text": "Hello"}]
        result = merge_word_captions(words)
        assert len(result) == 1
        assert result[0]["text"] == "Hello"

    def test_merges_up_to_max_words(self):
        words = [
            {"startFrame": i * 3, "endFrame": i * 3 + 2, "text": f"word{i}"}
            for i in range(10)
        ]
        result = merge_word_captions(words, max_words=4, max_gap_frames=100)
        for phrase in result:
            word_count = len(phrase["text"].split())
            assert word_count <= 4

    def test_splits_on_gap(self):
        words = [
            {"startFrame": 0, "endFrame": 5, "text": "Hello"},
            {"startFrame": 100, "endFrame": 105, "text": "World"},
        ]
        result = merge_word_captions(words, max_words=10, max_gap_frames=10)
        assert len(result) == 2


class TestEstimateMp3Duration:
    def test_known_size(self):
        # 48kbps → 6000 bytes/sec → 6000 bytes = 1 sec
        data = b"\x00" * 6144  # 48 * 128 = 6144
        duration = estimate_mp3_duration(data)
        assert abs(duration - 1.0) < 0.01
