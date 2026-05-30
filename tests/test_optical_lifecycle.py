"""Pure tests for the House optical lifecycle adapter seam."""

import pytest


def test_retarget_progress_caps_body_ready_dismiss_to_slit_reentry():
    from spoke.optical_lifecycle import (
        OPTICAL_SLIT_REENTRY_PROGRESS,
        retarget_progress_for_dismiss,
    )

    decision = retarget_progress_for_dismiss(0.72)

    assert decision.should_retarget is True
    assert decision.start_progress == pytest.approx(OPTICAL_SLIT_REENTRY_PROGRESS)
    assert decision.start_progress < 0.72


def test_trace_backed_early_dismiss_retarget_stays_below_text_release():
    from spoke.optical_lifecycle import (
        OPTICAL_BODY_READY_PROGRESS,
        OPTICAL_SLIT_REENTRY_PROGRESS,
        retarget_progress_for_dismiss,
    )

    decision = retarget_progress_for_dismiss(0.7998328110364075)

    assert decision.should_retarget is True
    assert decision.start_progress == pytest.approx(OPTICAL_SLIT_REENTRY_PROGRESS)
    assert decision.start_progress < OPTICAL_BODY_READY_PROGRESS


def test_retarget_progress_restarts_pre_body_dismiss_from_tiny_seed():
    from spoke.optical_lifecycle import (
        OPTICAL_MAG_SEED_PROGRESS,
        retarget_progress_for_dismiss,
    )

    decision = retarget_progress_for_dismiss(0.306)

    assert decision.should_retarget is True
    assert decision.start_progress == pytest.approx(OPTICAL_MAG_SEED_PROGRESS)
    assert decision.start_progress < 0.306


def test_retarget_progress_preserves_closed_slit_reentry():
    from spoke.optical_lifecycle import retarget_progress_for_dismiss

    decision = retarget_progress_for_dismiss(0.0)

    assert decision.should_retarget is True
    assert decision.start_progress == pytest.approx(0.0)
