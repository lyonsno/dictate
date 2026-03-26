"""Monkey-patch mlx-qwen3-asr streaming merge to fix false word overlaps.

The upstream ``_append_chunk_text`` greedily matches suffix-prefix overlaps
at the single-word level.  Common words like "the" or "and" trigger false
overlaps that silently eat content at chunk boundaries.  Requiring a minimum
overlap of 2 words (or 3 characters for CJK) eliminates the false positives
while preserving legitimate decoder re-transcription merges.

Import this module once before any streaming call::

    import spoke.patch_qwen3_streaming  # noqa: F401

The patch is idempotent — repeated imports are harmless.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PATCHED = False


def _append_chunk_text_fixed(current: str, addition: str, language: str) -> str:
    """Merge chunk text with min-overlap guard against false word matches."""
    from mlx_qwen3_asr.streaming import _CJK_LANG_ALIASES, _split_text_units

    curr = str(current or "").strip()
    add = str(addition or "").strip()
    if not add:
        return curr
    if not curr:
        return add
    if curr == add or curr.endswith(add):
        return curr
    if add.startswith(curr):
        return add

    lang = (language or "").strip().lower()
    joiner = "" if lang in _CJK_LANG_ALIASES else " "
    if joiner == " ":
        curr_units = curr.split()
        add_units = add.split()
    else:
        curr_units = list(curr)
        add_units = list(add)

    # Prefix-superset check: if addition rewrites from the same start and is
    # at least as long, prefer it (handles full-rewrite decoder behavior).
    prefix_check = 3 if joiner == " " else 6
    pref_n = min(prefix_check, len(curr_units), len(add_units))
    if pref_n > 0 and curr_units[:pref_n] == add_units[:pref_n]:
        if len(add_units) >= len(curr_units):
            return add

    # Overlap merge — require >=2 word overlap (>=3 chars for CJK) to avoid
    # false positives on common single words like "the", "and", "a".
    min_overlap = 2 if joiner == " " else 3
    max_overlap = min(len(curr_units), len(add_units))
    overlap = 0
    for k in range(max_overlap, min_overlap - 1, -1):
        if curr_units[-k:] == add_units[:k]:
            overlap = k
            break

    if overlap > 0:
        merged_units = curr_units + add_units[overlap:]
        return joiner.join(merged_units)

    return f"{curr}{joiner}{add}"


def apply():
    """Apply the patch. Idempotent."""
    global _PATCHED
    if _PATCHED:
        return

    try:
        import mlx_qwen3_asr.streaming as _mod

        _mod._append_chunk_text = _append_chunk_text_fixed
        _PATCHED = True
        logger.debug("Patched mlx_qwen3_asr._append_chunk_text (min-overlap guard)")
    except ImportError:
        logger.debug("mlx-qwen3-asr not installed; streaming patch skipped")


apply()
