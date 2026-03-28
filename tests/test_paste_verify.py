"""Tests for post-paste OCR verification."""

import importlib
import sys
from unittest.mock import patch


def _import_module():
    sys.modules.pop("spoke.paste_verify", None)
    return importlib.import_module("spoke.paste_verify")


class TestTextAppearsOnScreen:
    """Test the fuzzy matching logic (no OCR dependency needed)."""

    def test_exact_match(self):
        mod = _import_module()
        assert mod.text_appears_on_screen(
            "Hello world this is a test sentence",
            "Some UI chrome Hello world this is a test sentence more stuff"
        ) is True

    def test_partial_match_above_threshold(self):
        mod = _import_module()
        # OCR might miss a few characters but the bulk is there
        assert mod.text_appears_on_screen(
            "Hello world this is a test sentence",
            "Some chrome Hello world this is a test more stuff"
        ) is True

    def test_no_match(self):
        mod = _import_module()
        assert mod.text_appears_on_screen(
            "Hello world this is a test sentence",
            "Completely different text on screen about other things entirely"
        ) is False

    def test_short_text_always_passes(self):
        mod = _import_module()
        # Short texts skip verification to avoid false negatives
        assert mod.text_appears_on_screen("Hi", "Anything") is True

    def test_empty_expected_returns_false(self):
        mod = _import_module()
        assert mod.text_appears_on_screen("", "screen text") is False

    def test_empty_screen_returns_false(self):
        mod = _import_module()
        assert mod.text_appears_on_screen("some expected text here", "") is False

    def test_case_insensitive(self):
        mod = _import_module()
        assert mod.text_appears_on_screen(
            "Hello World This Is Important",
            "hello world this is important"
        ) is True

    def test_whitespace_normalized(self):
        mod = _import_module()
        assert mod.text_appears_on_screen(
            "Hello   world\nthis is\ta test sentence",
            "Hello world this is a test sentence"
        ) is True

    def test_threshold_boundary(self):
        mod = _import_module()
        # Exactly at the boundary — half the text matches
        expected = "abcdefghijklmnopqrstuvwxyz"
        screen = "abcdefghijklm totally different"
        result = mod.text_appears_on_screen(expected, screen)
        assert result is True  # 13/26 = 50% coverage

    def test_below_threshold(self):
        mod = _import_module()
        expected = "abcdefghijklmnopqrstuvwxyz"
        screen = "abcde totally completely different text here"
        result = mod.text_appears_on_screen(expected, screen)
        assert result is False  # 5/26 = ~19% coverage
