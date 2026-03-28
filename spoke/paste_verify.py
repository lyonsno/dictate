"""Post-paste OCR verification.

After a synthetic Cmd+V, captures the screen and runs Vision OCR to
confirm the pasted text actually appeared. If the text is not found,
the caller can enter recovery mode.

Uses Apple's Vision framework (VNRecognizeTextRequest) which runs on
the Neural Engine — ~50ms for a full-screen OCR pass after warmup.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Minimum fuzzy match ratio to consider the paste successful.
# Generous because OCR may misread a few characters, and the pasted
# text might only be partially visible (scrolled, clipped, etc.).
_MATCH_THRESHOLD = 0.5

# Minimum length of pasted text to bother verifying — very short
# strings (1-2 words) are too likely to appear in UI chrome.
_MIN_VERIFY_LENGTH = 15


def capture_screen_text() -> str:
    """Capture the full screen and return all recognized text.

    Returns a single string with all OCR results concatenated.
    Returns empty string on any failure.
    """
    try:
        from Vision import VNRecognizeTextRequest, VNImageRequestHandler, VNRequestTextRecognitionLevelFast
        from Quartz import (
            CGWindowListCreateImage,
            kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID,
            CGRectInfinite,
        )

        image = CGWindowListCreateImage(
            CGRectInfinite, kCGWindowListOptionOnScreenOnly, kCGNullWindowID, 0
        )
        if image is None:
            logger.debug("Screen capture returned None")
            return ""

        handler = VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
        request = VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(VNRequestTextRecognitionLevelFast)
        request.setUsesLanguageCorrection_(False)

        success, error = handler.performRequests_error_([request], None)
        if not success:
            logger.debug("Vision OCR failed: %s", error)
            return ""

        results = request.results()
        if not results:
            return ""

        lines = []
        for observation in results:
            candidates = observation.topCandidates_(1)
            if candidates:
                lines.append(candidates[0].string())

        return " ".join(lines)
    except Exception:
        logger.debug("Screen OCR failed", exc_info=True)
        return ""


def text_appears_on_screen(expected: str, screen_text: str) -> bool:
    """Check whether the expected text appears in the OCR output.

    Uses a greedy fuzzy match — we know exactly what we're looking for,
    so even a partial match is high confidence.

    For very short texts (< _MIN_VERIFY_LENGTH chars), always returns
    True since short strings match UI chrome too easily and produce
    false negatives.
    """
    if not expected or not screen_text:
        return False

    if len(expected) < _MIN_VERIFY_LENGTH:
        # Too short to reliably verify — assume success
        logger.debug("Text too short to verify (%d chars), assuming success", len(expected))
        return True

    # Normalize whitespace for comparison
    expected_norm = " ".join(expected.split()).lower()
    screen_norm = " ".join(screen_text.split()).lower()

    # Check if a substantial substring of expected appears in screen text.
    # SequenceMatcher finds the longest common subsequence ratio.
    # We use it on the expected text against a sliding window of the
    # screen text to find the best local match.
    #
    # For efficiency, if the expected text appears as a literal substring
    # (common case), skip the fuzzy match.
    if expected_norm in screen_norm:
        logger.debug("Exact match found in screen text")
        return True

    # Fuzzy match: find the best ratio between expected and any
    # similarly-sized window of the screen text.
    ratio = SequenceMatcher(None, expected_norm, screen_norm).ratio()

    # The ratio is over the full screen text which dilutes the match.
    # Use find_longest_match to get the actual overlap quality.
    matcher = SequenceMatcher(None, expected_norm, screen_norm)
    match = matcher.find_longest_match(0, len(expected_norm), 0, len(screen_norm))
    if match.size == 0:
        logger.debug("No common subsequence found")
        return False

    # What fraction of the expected text was found as a contiguous match?
    coverage = match.size / len(expected_norm)
    logger.debug("Best contiguous match: %d/%d chars (%.0f%% coverage)",
                 match.size, len(expected_norm), coverage * 100)

    return coverage >= _MATCH_THRESHOLD
