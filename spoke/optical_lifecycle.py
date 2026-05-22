"""Lifecycle decisions for House optical surfaces.

This module owns small, AppKit-free transition decisions that consumers should
share instead of copying ``CommandOverlay`` timer and compositor internals.
"""

from __future__ import annotations

from typing import NamedTuple


OPTICAL_BODY_READY_PROGRESS = 0.55
OPTICAL_MAG_SEED_PROGRESS = 0.04


class RetargetDecision(NamedTuple):
    should_retarget: bool
    start_progress: float


def _clamp01(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def retarget_progress_for_dismiss(progress: float) -> RetargetDecision:
    """Map dismiss-local body progress onto a lawful summon re-entry point."""
    p = _clamp01(progress)
    if p < OPTICAL_BODY_READY_PROGRESS:
        start_progress = min(p, OPTICAL_MAG_SEED_PROGRESS)
    else:
        start_progress = min(p, OPTICAL_BODY_READY_PROGRESS)
    return RetargetDecision(should_retarget=True, start_progress=start_progress)
