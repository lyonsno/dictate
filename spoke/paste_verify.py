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
    if expected_norm in screen_norm:
        logger.info("Paste verify: exact substring match found")
        return True

    # Fuzzy match using SequenceMatcher ratio over the full texts.
    # This accounts for OCR errors, line breaks splitting words,
    # and partial visibility at screen edges.
    matcher = SequenceMatcher(None, expected_norm, screen_norm)

    # get_matching_blocks returns all matching subsequences, not just
    # the longest one. Sum their lengths for total character coverage.
    blocks = matcher.get_matching_blocks()
    total_matched = sum(b.size for b in blocks)
    coverage = total_matched / len(expected_norm) if expected_norm else 0

    logger.info(
        "Paste verify: %d/%d chars matched (%.0f%% coverage, %d blocks, threshold %.0f%%)",
        total_matched, len(expected_norm), coverage * 100,
        len(blocks) - 1,  # last block is always (len_a, len_b, 0)
        _MATCH_THRESHOLD * 100,
    )
    if logger.isEnabledFor(logging.DEBUG):
        # Show the first 100 chars of expected and a sample of screen text
        logger.debug("  expected: %r", expected_norm[:100])
        # Find the region of screen text near the best match
        best = max(blocks[:-1], key=lambda b: b.size) if len(blocks) > 1 else None
        if best:
            start = max(0, best.b - 20)
            end = min(len(screen_norm), best.b + best.size + 20)
            logger.debug("  best match region: %r", screen_norm[start:end])

    return coverage >= _MATCH_THRESHOLD
