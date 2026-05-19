"""Optical lifecycle adapter: pure state/transition vocabulary for the operator overlay.

This module extracts the lifecycle decision law from CommandOverlay's private
state into a testable, consumable adapter.  The adapter owns:

  - lifecycle state and event vocabulary (enums)
  - retarget-progress decision: when summon arrives during dismiss, what
    progress to re-enter at
  - pending-entrance teardown decision: whether an alpha-zero entrance can
    be torn down without playing dismiss
  - text-plane restore contract shape

It does NOT own:
  - Metal/compositor rendering, SDF fill, or visual tuning
  - AppKit timer management
  - any mutable CommandOverlay state
"""

from __future__ import annotations

import enum
from typing import NamedTuple


# ── Lifecycle vocabulary ────────────────────────────────────────────


class LifecycleState(enum.Enum):
    """Observable lifecycle states of the operator overlay."""

    IDLE_CLOSED = "idle_closed"
    SUMMONING = "summoning"
    IDLE_OPEN = "idle_open"
    DISMISSING = "dismissing"
    DISMISSING_PUCKER = "dismissing_pucker"


class LifecycleEvent(enum.Enum):
    """Events that drive lifecycle transitions."""

    SUMMON = "summon"
    DISMISS = "dismiss"
    MATERIALIZATION_COMPLETE = "materialization_complete"
    PUCKER_COMPLETE = "pucker_complete"


# ── Retarget decision ──────────────────────────────────────────────

# These constants must match command_overlay.py exactly.  They are
# duplicated here so the adapter can be tested without importing the
# 5000-line overlay module.  If they drift, the integration call-site
# will fail because the adapter and overlay will disagree on thresholds.
BODY_READY_PROGRESS = 0.55
MAG_SEED_FRAC = 0.04


class RetargetDecision(NamedTuple):
    """Result of evaluating a summon-during-dismiss retarget."""

    should_retarget: bool
    summon_start_progress: float
    was_pre_body: bool


def retarget_progress_for_dismiss(dismiss_progress: float) -> RetargetDecision:
    """Decide the lawful summon re-entry point for a dismiss-in-flight.

    Implements the same law as ``_summon_retarget_progress_for_dismiss_progress``
    in ``command_overlay.py``:

    - Pre-body dismiss (progress < BODY_READY): retarget from tiny seed,
      clamped to MAG_SEED_FRAC.
    - Post-body dismiss (progress >= BODY_READY): retarget capped at
      BODY_READY so the full-open flash is never re-seeded.

    Returns a RetargetDecision so the caller knows both the numeric
    re-entry point and whether the reversal was pre-body.
    """
    p = max(0.0, min(1.0, dismiss_progress))
    if p < BODY_READY_PROGRESS:
        return RetargetDecision(
            should_retarget=True,
            summon_start_progress=min(p, MAG_SEED_FRAC),
            was_pre_body=True,
        )
    return RetargetDecision(
        should_retarget=True,
        summon_start_progress=min(p, BODY_READY_PROGRESS),
        was_pre_body=False,
    )


# ── Pending entrance teardown ──────────────────────────────────────


class PendingEntranceTeardownDecision(NamedTuple):
    """Result of evaluating whether a pending entrance can be torn down."""

    should_teardown: bool
    reason: str


def should_teardown_pending_entrance(
    *,
    has_compositor: bool,
    window_alpha: float,
) -> PendingEntranceTeardownDecision:
    """Decide whether an alpha-zero optical entrance can be silently torn down.

    Implements the gate logic from ``_cancel_pending_optical_entrance_if_invisible``:
    teardown is safe only when a compositor exists and the window is effectively
    invisible (alpha <= 0.001).
    """
    if not has_compositor:
        return PendingEntranceTeardownDecision(
            should_teardown=False,
            reason="no_compositor",
        )
    if window_alpha > 0.001:
        return PendingEntranceTeardownDecision(
            should_teardown=False,
            reason="visible",
        )
    return PendingEntranceTeardownDecision(
        should_teardown=True,
        reason="invisible_with_compositor",
    )


# ── Text-plane restore contract ───────────────────────────────────


class TextPlaneRestoreDecision(NamedTuple):
    """Whether the text plane needs restoration after an entrance bypass."""

    should_restore: bool
    reason: str


def should_restore_text_plane(
    *,
    compositor_started: bool,
    has_initial_content: bool,
) -> TextPlaneRestoreDecision:
    """Decide whether to restore the text plane after a failed compositor start.

    When the fullscreen compositor fails to start during show(), the AppKit
    local shell must restore the scroll/text layer.  If the caller started
    with known content (initial transcript), the text punchthrough must also
    be disabled.
    """
    if compositor_started:
        return TextPlaneRestoreDecision(
            should_restore=False,
            reason="compositor_owns_entrance",
        )
    return TextPlaneRestoreDecision(
        should_restore=True,
        reason="compositor_failed_with_content" if has_initial_content else "compositor_failed",
    )


# ── Transition table ──────────────────────────────────────────────


def next_state(current: LifecycleState, event: LifecycleEvent) -> LifecycleState:
    """Pure transition function for the overlay lifecycle.

    Returns the next state given the current state and an event.
    Raises ValueError for illegal transitions.
    """
    _TABLE = {
        (LifecycleState.IDLE_CLOSED, LifecycleEvent.SUMMON): LifecycleState.SUMMONING,
        (LifecycleState.SUMMONING, LifecycleEvent.MATERIALIZATION_COMPLETE): LifecycleState.IDLE_OPEN,
        (LifecycleState.SUMMONING, LifecycleEvent.DISMISS): LifecycleState.DISMISSING,
        (LifecycleState.IDLE_OPEN, LifecycleEvent.DISMISS): LifecycleState.DISMISSING,
        (LifecycleState.DISMISSING, LifecycleEvent.SUMMON): LifecycleState.SUMMONING,
        (LifecycleState.DISMISSING, LifecycleEvent.MATERIALIZATION_COMPLETE): LifecycleState.DISMISSING_PUCKER,
        (LifecycleState.DISMISSING_PUCKER, LifecycleEvent.SUMMON): LifecycleState.SUMMONING,
        (LifecycleState.DISMISSING_PUCKER, LifecycleEvent.PUCKER_COMPLETE): LifecycleState.IDLE_CLOSED,
    }
    key = (current, event)
    if key not in _TABLE:
        raise ValueError(
            f"Illegal lifecycle transition: {current.value} + {event.value}"
        )
    return _TABLE[key]
