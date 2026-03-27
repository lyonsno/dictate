"""Contract tests for screen-edge glow tuning."""

import importlib
import sys
from unittest.mock import MagicMock

import pytest


class TestGlowTuning:
    """Keep the screen-edge glow restrained at peaks without flattening quiet response."""

    def _make_glow(self, mod):
        glow = mod.GlowOverlay.__new__(mod.GlowOverlay)
        glow._visible = False
        glow._window = MagicMock()
        glow._glow_layer = MagicMock()
        glow._glow_layer.opacity.return_value = 0.07
        glow._fade_in_until = 0.0
        glow._update_count = 0
        glow._noise_floor = 0.0
        glow._smoothed_amplitude = 0.0
        glow._cap_factor = 1.0
        glow._shadow_shape = MagicMock()
        glow._gradient_layers = []
        glow._screen = object()
        glow._hide_timer = None
        glow._hide_generation = 0
        glow._dim_layer = MagicMock()
        glow._dim_layer.opacity.return_value = 0.0
        return glow

    def test_screen_dim_fade_durations_are_shortened_for_dev_patch(self):
        """The temporary dimmer patch should keep fade timings short enough to avoid overlap."""
        sys.modules.pop("spoke.glow", None)
        mod = importlib.import_module("spoke.glow")
        try:
            assert mod._DIM_SHOW_FADE_S == pytest.approx(1.08)
            assert mod._DIM_HIDE_FADE_S == pytest.approx(2.4)
        finally:
            sys.modules.pop("spoke.glow", None)

    def test_show_invalidates_pending_hide_timer(self, mock_pyobjc, monkeypatch):
        """A new recording should cancel the prior teardown timer before restarting the glow."""
        sys.modules.pop("spoke.glow", None)
        mod = importlib.import_module("spoke.glow")
        try:
            glow = self._make_glow(mod)
            pending_timer = MagicMock()
            glow._hide_timer = pending_timer
            monkeypatch.setattr(mod, "_sample_screen_brightness", lambda screen: 0.5)

            glow.show()

            pending_timer.invalidate.assert_called_once_with()
            assert glow._hide_timer is None
        finally:
            sys.modules.pop("spoke.glow", None)

    def test_hide_schedules_window_teardown_after_dim_fade(self, mock_pyobjc):
        """The window should stay alive until the dim fade has had time to finish."""
        sys.modules.pop("spoke.glow", None)
        mod = importlib.import_module("spoke.glow")
        try:
            glow = self._make_glow(mod)
            presentation = MagicMock()
            presentation.opacity.return_value = 0.3
            glow._dim_layer.presentationLayer.return_value = presentation

            timer = MagicMock()
            mod.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_.return_value = timer

            glow.hide()

            call = mod.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_.call_args
            assert call.args[0] == pytest.approx(2.45)
            assert call.args[1] is glow
            assert call.args[2] == "hideWindowAfterFade:"
            assert call.args[3] == 1
            assert call.args[4] is False
            assert glow._hide_timer is timer
            assert glow._hide_generation == 1
        finally:
            sys.modules.pop("spoke.glow", None)

    def test_hide_uses_presentation_opacity_for_glow_fade_out(self, mock_pyobjc):
        """Hide should fade from the live on-screen glow opacity, not stale model state."""
        sys.modules.pop("spoke.glow", None)
        mod = importlib.import_module("spoke.glow")
        try:
            glow = self._make_glow(mod)
            glow._dim_layer = None
            glow_presentation = MagicMock()
            glow_presentation.opacity.return_value = 0.22
            glow._glow_layer.presentationLayer.return_value = glow_presentation

            glow.hide()

            anim = mod.CABasicAnimation.animationWithKeyPath_.return_value
            anim.setFromValue_.assert_called_with(0.22)
        finally:
            sys.modules.pop("spoke.glow", None)

    def test_hide_window_after_fade_ignores_stale_timer_generation(self, mock_pyobjc):
        """An older hide timer must not tear down a later recording cycle."""
        sys.modules.pop("spoke.glow", None)
        mod = importlib.import_module("spoke.glow")
        try:
            glow = self._make_glow(mod)
            glow._visible = False
            glow._hide_generation = 2

            stale_timer = MagicMock()
            stale_timer.userInfo.return_value = 1

            glow.hideWindowAfterFade_(stale_timer)

            glow._window.orderOut_.assert_not_called()
        finally:
            sys.modules.pop("spoke.glow", None)

    def test_hide_window_after_fade_orders_out_current_hide_generation(self, mock_pyobjc):
        """The active hide timer should still complete teardown once the fade finishes."""
        sys.modules.pop("spoke.glow", None)
        mod = importlib.import_module("spoke.glow")
        try:
            glow = self._make_glow(mod)
            glow._visible = False
            glow._hide_generation = 3

            timer = MagicMock()
            timer.userInfo.return_value = 3

            glow.hideWindowAfterFade_(timer)

            glow._window.orderOut_.assert_called_once_with(None)
        finally:
            sys.modules.pop("spoke.glow", None)

    def test_screen_glow_shadow_radius_is_doubled_for_softer_bloom(self, mock_pyobjc):
        """The edge glow should spread farther so lower peak opacity still reads as glow."""
        sys.modules.pop("spoke.glow", None)
        mod = importlib.import_module("spoke.glow")
        try:
            assert mod._GLOW_SHADOW_RADIUS == 60.0
        finally:
            sys.modules.pop("spoke.glow", None)

    def test_screen_glow_peak_is_softened_without_changing_quiet_levels(
        self, mock_pyobjc
    ):
        """Quiet and mid-level glow should stay intact while full-scale peaks get much dimmer."""
        sys.modules.pop("spoke.glow", None)
        mod = importlib.import_module("spoke.glow")
        try:
            assert mod._compress_screen_glow_peak(0.1) == pytest.approx(0.1)
            assert mod._compress_screen_glow_peak(mod._GLOW_PEAK_TARGET) == pytest.approx(
                mod._GLOW_PEAK_TARGET
            )
            assert mod._compress_screen_glow_peak(0.6) == pytest.approx(mod._GLOW_PEAK_TARGET)
            assert mod._compress_screen_glow_peak(0.81) == pytest.approx(mod._GLOW_PEAK_TARGET)

            peak_opacity = mod._compress_screen_glow_peak(1.0)
            assert peak_opacity == pytest.approx(mod._GLOW_PEAK_TARGET)
        finally:
            sys.modules.pop("spoke.glow", None)

    def test_screen_glow_countdown_scales_border_opacity_too(self, mock_pyobjc, monkeypatch):
        """The recording-cap countdown should dim the border glow, not just recolor it."""
        sys.modules.pop("spoke.glow", None)
        mod = importlib.import_module("spoke.glow")
        try:
            def _make_glow(cap_factor: float):
                glow = self._make_glow(mod)
                glow._visible = True
                glow._cap_factor = cap_factor
                return glow

            monkeypatch.setattr(mod.time, "monotonic", lambda: 1.0)

            uncapped = _make_glow(1.0)
            uncapped.update_amplitude(1.0)
            uncapped_opacity = uncapped._glow_layer.setOpacity_.call_args[0][0]

            capped = _make_glow(0.5)
            capped.update_amplitude(1.0)
            capped_opacity = capped._glow_layer.setOpacity_.call_args[0][0]

            assert capped_opacity < uncapped_opacity
        finally:
            sys.modules.pop("spoke.glow", None)
