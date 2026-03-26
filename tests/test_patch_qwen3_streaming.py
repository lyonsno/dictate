"""Tests for the mlx-qwen3-asr streaming merge monkey-patch."""

import pytest

from spoke.patch_qwen3_streaming import _append_chunk_text_fixed as merge


class TestSingleWordFalseOverlap:
    """The core bug: single common words causing false overlaps."""

    def test_the_at_boundary(self):
        result = merge(
            "I went to the store and bought the",
            "the quick brown fox jumped over",
            "en",
        )
        assert "bought the the quick" in result

    def test_and_at_boundary(self):
        result = merge(
            "cats and",
            "and dogs are great",
            "en",
        )
        assert result == "cats and and dogs are great"

    def test_a_at_boundary(self):
        result = merge(
            "this is a",
            "a very long sentence",
            "en",
        )
        assert result == "this is a a very long sentence"


class TestLegitimateOverlap:
    """Real decoder re-transcription overlaps should still merge."""

    def test_three_word_overlap(self):
        result = merge(
            "I went to the store and bought the apples",
            "bought the apples and then went home",
            "en",
        )
        assert result == "I went to the store and bought the apples and then went home"

    def test_two_word_overlap(self):
        result = merge(
            "the store and the apples",
            "the apples were on sale",
            "en",
        )
        assert result == "the store and the apples were on sale"

    def test_long_overlap(self):
        result = merge(
            "one two three four five",
            "three four five six seven",
            "en",
        )
        assert result == "one two three four five six seven"


class TestEdgeCases:
    """Empty, identical, subset, and superset inputs."""

    def test_empty_addition(self):
        assert merge("hello", "", "en") == "hello"

    def test_empty_current(self):
        assert merge("", "hello", "en") == "hello"

    def test_both_empty(self):
        assert merge("", "", "en") == ""

    def test_identical(self):
        assert merge("hello world", "hello world", "en") == "hello world"

    def test_addition_is_suffix(self):
        assert merge("hello world", "world", "en") == "hello world"

    def test_addition_is_superset(self):
        assert merge("hello", "hello world", "en") == "hello world"

    def test_no_overlap_concatenates(self):
        assert merge("hello world", "foo bar baz", "en") == "hello world foo bar baz"

    def test_prefix_rewrite_superset(self):
        result = merge("Hello world today", "Hello world today is great", "en")
        assert result == "Hello world today is great"


class TestCJK:
    """CJK languages use character-level units with min_overlap=3."""

    def test_single_char_no_false_overlap(self):
        result = merge("我去了商店买了", "了一些苹果", "zh")
        # Single char "了" should NOT trigger overlap — concatenates with duplication
        assert result == "我去了商店买了了一些苹果"

    def test_two_char_no_false_overlap(self):
        result = merge("我去了商店买了苹", "了苹果很好吃", "zh")
        # Two char overlap "了苹" should NOT trigger (min is 3)
        assert result == "我去了商店买了苹了苹果很好吃"

    def test_three_char_overlap_merges(self):
        result = merge("我去了商店买了苹果", "买了苹果很好吃", "zh")
        # Three char overlap "买了苹" should merge (but actually "买了苹果" is 4)
        assert "我去了商店买了苹果很好吃" == result


class TestPatchApplied:
    """Verify the monkey-patch actually replaces the upstream function."""

    def test_module_is_patched(self):
        import spoke.patch_qwen3_streaming as patch_mod

        assert patch_mod._PATCHED is True

    def test_upstream_function_replaced(self):
        import mlx_qwen3_asr.streaming as mod

        assert mod._append_chunk_text.__name__ == "_append_chunk_text_fixed"
