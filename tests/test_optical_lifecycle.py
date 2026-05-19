"""Tests for the optical lifecycle adapter.

These are pure decision-law tests — no AppKit, no mocks, no GUI runtime.
They verify the Slitgate invariants as extracted adapter contracts:

  1. Pre-body dismiss reversal re-enters from tiny seed (capped at MAG_SEED_FRAC).
  2. Post-body dismiss reversal never re-seeds full open (capped at BODY_READY).
  3. Pending alpha-zero entrance teardown does not strand a compositor.
  4. Text-plane restore fires when compositor fails.
  5. Transition table matches the landed CommandOverlay trajectory strings.
"""

import pytest

from spoke.optical_lifecycle import (
    BODY_READY_PROGRESS,
    MAG_SEED_FRAC,
    LifecycleEvent,
    LifecycleState,
    PendingEntranceTeardownDecision,
    RetargetDecision,
    TextPlaneRestoreDecision,
    next_state,
    retarget_progress_for_dismiss,
    should_restore_text_plane,
    should_teardown_pending_entrance,
)


# ── Retarget decision law ────────────────────────────────────────


class TestRetargetProgressForDismiss:
    """Pre-body dismiss reversal re-enters from tiny seed."""

    def test_pre_body_low_progress_caps_at_seed(self):
        """Very early dismiss (progress near 0) should retarget at MAG_SEED_FRAC."""
        result = retarget_progress_for_dismiss(0.02)
        assert result.should_retarget is True
        assert result.was_pre_body is True
        assert result.summon_start_progress == 0.02  # below seed frac, identity

    def test_pre_body_mid_progress_caps_at_seed(self):
        """Dismiss at 30% (pre-body) should cap retarget at MAG_SEED_FRAC."""
        result = retarget_progress_for_dismiss(0.30)
        assert result.should_retarget is True
        assert result.was_pre_body is True
        assert result.summon_start_progress == MAG_SEED_FRAC

    def test_pre_body_just_below_threshold(self):
        """Dismiss just below BODY_READY should still cap at MAG_SEED_FRAC."""
        result = retarget_progress_for_dismiss(BODY_READY_PROGRESS - 0.01)
        assert result.should_retarget is True
        assert result.was_pre_body is True
        assert result.summon_start_progress == MAG_SEED_FRAC

    def test_post_body_caps_at_body_ready(self):
        """Post-body dismiss should cap retarget at BODY_READY (never full-open flash)."""
        result = retarget_progress_for_dismiss(0.80)
        assert result.should_retarget is True
        assert result.was_pre_body is False
        assert result.summon_start_progress == BODY_READY_PROGRESS

    def test_post_body_at_threshold(self):
        """Dismiss exactly at BODY_READY is post-body."""
        result = retarget_progress_for_dismiss(BODY_READY_PROGRESS)
        assert result.should_retarget is True
        assert result.was_pre_body is False
        assert result.summon_start_progress == BODY_READY_PROGRESS

    def test_full_dismiss_near_zero(self):
        """Dismiss at progress 0.0 should retarget at 0.0."""
        result = retarget_progress_for_dismiss(0.0)
        assert result.should_retarget is True
        assert result.was_pre_body is True
        assert result.summon_start_progress == 0.0

    def test_full_dismiss_at_one(self):
        """Dismiss at progress 1.0 caps at BODY_READY."""
        result = retarget_progress_for_dismiss(1.0)
        assert result.should_retarget is True
        assert result.was_pre_body is False
        assert result.summon_start_progress == BODY_READY_PROGRESS

    def test_clamps_below_zero(self):
        result = retarget_progress_for_dismiss(-0.5)
        assert result.summon_start_progress == 0.0
        assert result.was_pre_body is True

    def test_clamps_above_one(self):
        result = retarget_progress_for_dismiss(1.5)
        assert result.summon_start_progress == BODY_READY_PROGRESS
        assert result.was_pre_body is False


# ── Constants match command_overlay.py ───────────────────────────


class TestConstantsParity:
    """Adapter constants must match the source-of-truth in command_overlay.py."""

    def test_body_ready_progress(self):
        from spoke import command_overlay as co
        assert BODY_READY_PROGRESS == co._OPTICAL_MATERIALIZATION_BODY_READY

    def test_mag_seed_frac(self):
        from spoke import command_overlay as co
        assert MAG_SEED_FRAC == co._OPTICAL_MATERIALIZATION_MAG_SEED_FRAC


# ── Retarget parity with command_overlay ────────────────────────


class TestRetargetParityWithOverlay:
    """Adapter retarget must agree with command_overlay for all sampled values."""

    @pytest.mark.parametrize("progress", [0.0, 0.01, 0.03, 0.04, 0.10, 0.30, 0.54, 0.55, 0.60, 0.80, 1.0])
    def test_retarget_matches_overlay_function(self, progress):
        from spoke import command_overlay as co
        expected = co._summon_retarget_progress_for_dismiss_progress(progress)
        result = retarget_progress_for_dismiss(progress)
        assert abs(result.summon_start_progress - expected) < 1e-12, (
            f"Mismatch at progress={progress}: adapter={result.summon_start_progress}, overlay={expected}"
        )


# ── Pending entrance teardown ────────────────────────────────────


class TestShouldTeardownPendingEntrance:
    """Pending alpha-zero entrance teardown must not strand a compositor."""

    def test_teardown_invisible_with_compositor(self):
        result = should_teardown_pending_entrance(
            has_compositor=True, window_alpha=0.0
        )
        assert result.should_teardown is True
        assert result.reason == "invisible_with_compositor"

    def test_no_teardown_when_visible(self):
        result = should_teardown_pending_entrance(
            has_compositor=True, window_alpha=0.5
        )
        assert result.should_teardown is False
        assert result.reason == "visible"

    def test_no_teardown_without_compositor(self):
        result = should_teardown_pending_entrance(
            has_compositor=False, window_alpha=0.0
        )
        assert result.should_teardown is False
        assert result.reason == "no_compositor"

    def test_boundary_alpha_just_above_threshold(self):
        result = should_teardown_pending_entrance(
            has_compositor=True, window_alpha=0.002
        )
        assert result.should_teardown is False

    def test_boundary_alpha_at_threshold(self):
        result = should_teardown_pending_entrance(
            has_compositor=True, window_alpha=0.001
        )
        assert result.should_teardown is True

    def test_boundary_alpha_just_below_threshold(self):
        result = should_teardown_pending_entrance(
            has_compositor=True, window_alpha=0.0005
        )
        assert result.should_teardown is True


# ── Text-plane restore ───────────────────────────────────────────


class TestShouldRestoreTextPlane:
    """Text-plane quarantine restores visibility when compositor fails."""

    def test_restore_when_compositor_failed(self):
        result = should_restore_text_plane(
            compositor_started=False, has_initial_content=False
        )
        assert result.should_restore is True
        assert result.reason == "compositor_failed"

    def test_restore_with_initial_content(self):
        result = should_restore_text_plane(
            compositor_started=False, has_initial_content=True
        )
        assert result.should_restore is True
        assert result.reason == "compositor_failed_with_content"

    def test_no_restore_when_compositor_owns(self):
        result = should_restore_text_plane(
            compositor_started=True, has_initial_content=False
        )
        assert result.should_restore is False
        assert result.reason == "compositor_owns_entrance"

    def test_no_restore_when_compositor_owns_with_content(self):
        result = should_restore_text_plane(
            compositor_started=True, has_initial_content=True
        )
        assert result.should_restore is False


# ── Transition table ─────────────────────────────────────────────


class TestNextState:
    """Transition table matches landed CommandOverlay trajectory strings."""

    def test_summon_from_closed(self):
        assert next_state(LifecycleState.IDLE_CLOSED, LifecycleEvent.SUMMON) == LifecycleState.SUMMONING

    def test_materialization_complete_from_summoning(self):
        assert next_state(LifecycleState.SUMMONING, LifecycleEvent.MATERIALIZATION_COMPLETE) == LifecycleState.IDLE_OPEN

    def test_dismiss_from_open(self):
        assert next_state(LifecycleState.IDLE_OPEN, LifecycleEvent.DISMISS) == LifecycleState.DISMISSING

    def test_dismiss_from_summoning(self):
        """Dismiss during summon is legal (e.g. rapid toggle)."""
        assert next_state(LifecycleState.SUMMONING, LifecycleEvent.DISMISS) == LifecycleState.DISMISSING

    def test_summon_retargets_dismiss(self):
        """Summon during dismiss retargets back to summoning."""
        assert next_state(LifecycleState.DISMISSING, LifecycleEvent.SUMMON) == LifecycleState.SUMMONING

    def test_dismiss_completes_to_pucker(self):
        assert next_state(LifecycleState.DISMISSING, LifecycleEvent.MATERIALIZATION_COMPLETE) == LifecycleState.DISMISSING_PUCKER

    def test_pucker_completes_to_closed(self):
        assert next_state(LifecycleState.DISMISSING_PUCKER, LifecycleEvent.PUCKER_COMPLETE) == LifecycleState.IDLE_CLOSED

    def test_summon_during_pucker(self):
        """Summon during pucker retargets back to summoning."""
        assert next_state(LifecycleState.DISMISSING_PUCKER, LifecycleEvent.SUMMON) == LifecycleState.SUMMONING

    def test_illegal_dismiss_from_closed(self):
        with pytest.raises(ValueError, match="Illegal lifecycle transition"):
            next_state(LifecycleState.IDLE_CLOSED, LifecycleEvent.DISMISS)

    def test_illegal_pucker_complete_from_open(self):
        with pytest.raises(ValueError, match="Illegal lifecycle transition"):
            next_state(LifecycleState.IDLE_OPEN, LifecycleEvent.PUCKER_COMPLETE)

    def test_illegal_double_summon(self):
        with pytest.raises(ValueError, match="Illegal lifecycle transition"):
            next_state(LifecycleState.SUMMONING, LifecycleEvent.SUMMON)


# ── Full hammer-toggle cycle ─────────────────────────────────────


class TestHammerToggleCycle:
    """Simulate rapid summon/dismiss hammer-toggling through the adapter."""

    def test_full_cycle(self):
        """idle_closed -> summon -> open -> dismiss -> pucker -> closed."""
        s = LifecycleState.IDLE_CLOSED
        s = next_state(s, LifecycleEvent.SUMMON)
        assert s == LifecycleState.SUMMONING
        s = next_state(s, LifecycleEvent.MATERIALIZATION_COMPLETE)
        assert s == LifecycleState.IDLE_OPEN
        s = next_state(s, LifecycleEvent.DISMISS)
        assert s == LifecycleState.DISMISSING
        s = next_state(s, LifecycleEvent.MATERIALIZATION_COMPLETE)
        assert s == LifecycleState.DISMISSING_PUCKER
        s = next_state(s, LifecycleEvent.PUCKER_COMPLETE)
        assert s == LifecycleState.IDLE_CLOSED

    def test_rapid_retarget_cycle(self):
        """Summon -> dismiss -> retarget summon -> complete."""
        s = LifecycleState.IDLE_CLOSED
        s = next_state(s, LifecycleEvent.SUMMON)
        s = next_state(s, LifecycleEvent.DISMISS)
        assert s == LifecycleState.DISMISSING
        # Retarget
        s = next_state(s, LifecycleEvent.SUMMON)
        assert s == LifecycleState.SUMMONING
        s = next_state(s, LifecycleEvent.MATERIALIZATION_COMPLETE)
        assert s == LifecycleState.IDLE_OPEN

    def test_pucker_retarget(self):
        """Summon during pucker tail retargets to summoning."""
        s = LifecycleState.IDLE_CLOSED
        s = next_state(s, LifecycleEvent.SUMMON)
        s = next_state(s, LifecycleEvent.MATERIALIZATION_COMPLETE)
        s = next_state(s, LifecycleEvent.DISMISS)
        s = next_state(s, LifecycleEvent.MATERIALIZATION_COMPLETE)
        assert s == LifecycleState.DISMISSING_PUCKER
        s = next_state(s, LifecycleEvent.SUMMON)
        assert s == LifecycleState.SUMMONING


# ── Trajectory string parity ─────────────────────────────────────


class TestTrajectoryStringParity:
    """LifecycleState.value matches the string used in CommandOverlay._optical_lifecycle_trajectory."""

    def test_idle_closed(self):
        assert LifecycleState.IDLE_CLOSED.value == "idle_closed"

    def test_idle_open(self):
        assert LifecycleState.IDLE_OPEN.value == "idle_open"

    def test_summoning(self):
        assert LifecycleState.SUMMONING.value == "summoning"

    def test_dismissing(self):
        assert LifecycleState.DISMISSING.value == "dismissing"

    def test_dismissing_pucker(self):
        assert LifecycleState.DISMISSING_PUCKER.value == "dismissing_pucker"
