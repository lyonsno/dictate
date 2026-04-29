"""Tests for sticky routing with keyboard capture.

Lane K of ButterfingerFinalFuckers packet: sticky routing toggle,
keyboard capture while sticky, persistent glow visual, toggle off,
auto-route on release, per-recording override.
"""

import time
from unittest.mock import MagicMock, patch


class TestStickyToggleChord:
    """Space + Enter + route key from IDLE = toggle sticky routing."""

    def _make_detector(self, input_tap_module, hold_ms=400):
        """Create a detector with standard test wiring."""
        mod = input_tap_module
        on_start = MagicMock()
        on_end = MagicMock()
        det = mod.SpacebarHoldDetector.__new__(mod.SpacebarHoldDetector)
        det._on_hold_start = on_start
        det._on_hold_end = on_end
        det._hold_s = hold_ms / 1000.0
        det._state = mod._State.IDLE
        det._hold_timer = None
        det._safety_timer = None
        det._repeat_watchdog_timer = None
        det._last_space_keydown_monotonic = 0.0
        det._forwarding = False
        det._forwarding_timer = None
        det._tap = None
        det._tap_source = None
        det._awaiting_space_release = False
        det._enter_held = False
        det._enter_observed = False
        det._enter_latched = False
        det._enter_last_down_monotonic = 0.0
        det._suppress_enter_keyup = False
        det._suppress_delete_keyup = False
        det._shift_latched = False
        det._shift_at_press = False
        det._latched_space_down = False
        det._latched_space_released = False
        det._pending_release_active = False
        det._pending_release_shift_held = False
        det._space_keydown_timestamp_ns = None
        det.tray_active = False
        det.command_overlay_active = False
        det.approval_active = False
        det._tray_gesture_consumed = False
        det._shift_down_during_hold = False
        det._tray_last_shift_space_up = 0.0
        det._idle_shift_down = False
        det._idle_shift_interrupted = False
        det._release_decision_timer = None
        det._shift_single_tap_timer = None

        from spoke.route_keys import RouteKeySelector
        det._route_key_selector = RouteKeySelector()
        det._on_send_chord = None
        det._on_cancel_generation = None
        det._on_sticky_toggle = None
        return det, on_start, on_end

    def test_sticky_toggle_detected_space_enter_bracket(self, input_tap_module):
        """Space + Enter + ] should fire sticky toggle callback.

        Space puts the detector in WAITING. Enter is tracked as held.
        Route key completes the three-key chord.
        """
        det, _, _ = self._make_detector(input_tap_module)
        mod = input_tap_module

        on_toggle = MagicMock()
        det._on_sticky_toggle = on_toggle

        # Space is held -> WAITING state, Enter also held
        det._state = mod._State.WAITING
        det._enter_held = True
        det._enter_observed = True

        from spoke.route_keys import BRACKET_RIGHT_KEYCODE
        result = det.handle_sticky_toggle(BRACKET_RIGHT_KEYCODE)
        assert result is True, "Sticky toggle should be detected and suppress the key"
        on_toggle.assert_called_once_with(keycode=BRACKET_RIGHT_KEYCODE)
        # After toggle, state returns to IDLE
        assert det._state == mod._State.IDLE

    def test_sticky_toggle_works_with_number_row_key(self, input_tap_module):
        """Sticky toggle should work with any route key, not just ]."""
        det, _, _ = self._make_detector(input_tap_module)
        mod = input_tap_module

        on_toggle = MagicMock()
        det._on_sticky_toggle = on_toggle

        det._state = mod._State.WAITING
        det._enter_held = True
        det._enter_observed = True

        from spoke.route_keys import NUMBER_ROW_KEYCODES
        keycode = NUMBER_ROW_KEYCODES[0]  # key '6'
        result = det.handle_sticky_toggle(keycode)
        assert result is True
        on_toggle.assert_called_once_with(keycode=keycode)

    def test_sticky_toggle_does_not_fire_without_enter(self, input_tap_module):
        """Without Enter held, route key should not fire sticky toggle."""
        det, _, _ = self._make_detector(input_tap_module)
        mod = input_tap_module

        on_toggle = MagicMock()
        det._on_sticky_toggle = on_toggle
        det._state = mod._State.WAITING
        det._enter_held = False

        from spoke.route_keys import BRACKET_RIGHT_KEYCODE
        result = det.handle_sticky_toggle(BRACKET_RIGHT_KEYCODE)
        assert result is False
        on_toggle.assert_not_called()

    def test_sticky_toggle_does_not_fire_during_recording(self, input_tap_module):
        """Sticky toggle only fires from WAITING (space held), not RECORDING."""
        det, _, _ = self._make_detector(input_tap_module)
        mod = input_tap_module

        on_toggle = MagicMock()
        det._on_sticky_toggle = on_toggle
        det._enter_held = True
        det._enter_observed = True
        det._state = mod._State.RECORDING

        from spoke.route_keys import BRACKET_RIGHT_KEYCODE
        result = det.handle_sticky_toggle(BRACKET_RIGHT_KEYCODE)
        assert result is False
        on_toggle.assert_not_called()

    def test_sticky_toggle_does_not_fire_from_idle(self, input_tap_module):
        """From IDLE (no space held), Enter + route key is a send chord, not sticky toggle.

        The toggle chord requires Space to be held (WAITING state).
        """
        det, _, _ = self._make_detector(input_tap_module)
        mod = input_tap_module

        on_toggle = MagicMock()
        det._on_sticky_toggle = on_toggle

        det._enter_held = True
        det._enter_observed = True
        det._state = mod._State.IDLE

        from spoke.route_keys import BRACKET_RIGHT_KEYCODE
        result = det.handle_sticky_toggle(BRACKET_RIGHT_KEYCODE)
        assert result is False, "From IDLE, this should be a send chord, not sticky toggle"
        on_toggle.assert_not_called()


class TestStickyKeyboardCapture:
    """While sticky routing is active, keystrokes are intercepted."""

    def test_keystrokes_intercepted_while_sticky(self, input_tap_module):
        """When sticky routing is active, arbitrary keystrokes should be
        captured and forwarded to the hot route destination."""
        det, _, _ = TestStickyToggleChord()._make_detector(input_tap_module)
        mod = input_tap_module

        on_keystroke = MagicMock()
        det._on_sticky_keystroke = on_keystroke
        det.sticky_active = True
        det.sticky_keycode = 30  # locked on ]

        # Simulate a regular 'a' key (keycode 0) while sticky
        result = det.handle_sticky_keystroke(0)
        assert result is True, "Keystroke should be intercepted while sticky"
        on_keystroke.assert_called_once_with(keycode=0)

    def test_keystrokes_pass_through_when_not_sticky(self, input_tap_module):
        """When sticky is not active, keystrokes pass through normally."""
        det, _, _ = TestStickyToggleChord()._make_detector(input_tap_module)

        on_keystroke = MagicMock()
        det._on_sticky_keystroke = on_keystroke
        det.sticky_active = False

        result = det.handle_sticky_keystroke(0)
        assert result is False
        on_keystroke.assert_not_called()

    def test_space_not_captured_while_sticky(self, input_tap_module):
        """Spacebar should NOT be captured while sticky — it still controls
        recording. Keyboard capture is for non-control keys only."""
        det, _, _ = TestStickyToggleChord()._make_detector(input_tap_module)
        mod = input_tap_module

        on_keystroke = MagicMock()
        det._on_sticky_keystroke = on_keystroke
        det.sticky_active = True
        det.sticky_keycode = 30

        # Spacebar (keycode 49) should NOT be intercepted
        result = det.handle_sticky_keystroke(mod.SPACEBAR_KEYCODE)
        assert result is False, "Spacebar must not be captured — it controls recording"
        on_keystroke.assert_not_called()


class TestStickyAutoRoute:
    """While sticky is active, recordings auto-route to the locked destination."""

    def test_recording_uses_sticky_destination_when_no_route_key_tapped(
        self, input_tap_module
    ):
        """When sticky routing is active and no per-recording route key was
        tapped, the recording should route to the sticky destination."""
        det, _, _ = TestStickyToggleChord()._make_detector(input_tap_module)

        det.sticky_active = True
        det.sticky_keycode = 30  # locked on ]

        # After recording ends with no per-recording route key tap,
        # the route key selector should still report the sticky keycode
        selector = det._route_key_selector
        assert selector.active_keycode is None, "No per-recording tap"

        # The sticky destination should be used when selector has no active key
        effective_keycode = (
            selector.active_keycode
            if selector.active_keycode is not None
            else det.sticky_keycode
        )
        assert effective_keycode == 30

    def test_per_recording_override_while_sticky(self, input_tap_module):
        """Tapping a different route key during recording should override
        the sticky destination for that recording only."""
        det, _, _ = TestStickyToggleChord()._make_detector(input_tap_module)

        det.sticky_active = True
        det.sticky_keycode = 30  # locked on ]

        # During recording, user taps key '7' (keycode 26)
        from spoke.route_keys import NUMBER_ROW_KEYCODES
        selector = det._route_key_selector
        selector.tap(26)  # select key 7

        # Per-recording selection overrides sticky
        effective_keycode = (
            selector.active_keycode
            if selector.active_keycode is not None
            else det.sticky_keycode
        )
        assert effective_keycode == 26, "Per-recording tap should override sticky"

    def test_sticky_persists_after_route_key_reset(self, input_tap_module):
        """After recording ends and route keys reset, the sticky keycode
        should still be available for the next recording."""
        det, _, _ = TestStickyToggleChord()._make_detector(input_tap_module)

        det.sticky_active = True
        det.sticky_keycode = 30

        selector = det._route_key_selector
        # Simulate a recording cycle: tap, then reset
        selector.tap(26)  # override during recording
        selector.reset()  # recording ended

        # After reset, sticky keycode is still there
        assert det.sticky_active is True
        assert det.sticky_keycode == 30
        assert selector.active_keycode is None  # per-recording state cleared


class TestStickyToggleOff:
    """Same toggle chord again deactivates sticky routing."""

    def test_toggle_off_fires_same_callback(self, input_tap_module):
        """Pressing Space + Enter + same route key while sticky = toggle off.

        The detector always fires the toggle callback; the delegate is
        responsible for deciding whether to activate or deactivate.
        """
        det, _, _ = TestStickyToggleChord()._make_detector(input_tap_module)
        mod = input_tap_module

        # Start with sticky active on ]
        det.sticky_active = True
        det.sticky_keycode = 30

        on_toggle = MagicMock()
        det._on_sticky_toggle = on_toggle

        det._enter_held = True
        det._enter_observed = True
        det._state = mod._State.WAITING  # Space held

        from spoke.route_keys import BRACKET_RIGHT_KEYCODE
        result = det.handle_sticky_toggle(BRACKET_RIGHT_KEYCODE)
        assert result is True
        # The callback fires with the keycode; the delegate decides toggle semantics
        on_toggle.assert_called_once_with(keycode=BRACKET_RIGHT_KEYCODE)


class TestGhostIndicatorPersistentGlow:
    """Ghost indicator should distinguish sticky glow from transient sharpening."""

    def test_ghost_has_distinct_sticky_alpha(self, mock_pyobjc):
        """A locked/sticky route key ghost should have a different (higher)
        alpha than the transient active alpha, distinguishing the two states."""
        import importlib
        import sys

        sys.modules.pop("spoke.overlay", None)
        sys.modules.pop("spoke.route_keys", None)
        sys.modules.pop("spoke.dedup", None)

        # Provide a minimal fake dedup module
        import types
        fake_dedup = types.ModuleType("spoke.dedup")
        fake_dedup.ontology_term_spans = MagicMock(return_value=[])
        sys.modules["spoke.dedup"] = fake_dedup

        overlay_mod = importlib.import_module("spoke.overlay")
        from spoke.route_keys import default_bindings, BRACKET_RIGHT_KEYCODE

        ghost = overlay_mod.GhostIndicatorLayer(default_bindings())

        # Transient active state
        ghost.set_active(BRACKET_RIGHT_KEYCODE)
        transient_alpha = ghost.ghost_alpha(BRACKET_RIGHT_KEYCODE)

        # Sticky/locked state should produce a visually distinct alpha
        ghost.set_sticky(BRACKET_RIGHT_KEYCODE)
        sticky_alpha = ghost.ghost_alpha(BRACKET_RIGHT_KEYCODE)

        assert sticky_alpha != transient_alpha, (
            f"Sticky glow alpha ({sticky_alpha}) must differ from transient "
            f"sharpening alpha ({transient_alpha})"
        )
        assert sticky_alpha > transient_alpha, (
            "Sticky glow should be more prominent than transient sharpening"
        )

        sys.modules.pop("spoke.overlay", None)
        sys.modules.pop("spoke.dedup", None)

    def test_ghost_sticky_alpha_survives_deselect(self, mock_pyobjc):
        """Clearing the transient active keycode should not clear the sticky
        glow — sticky persists until explicitly toggled off."""
        import importlib
        import sys
        import types

        sys.modules.pop("spoke.overlay", None)
        sys.modules.pop("spoke.route_keys", None)
        sys.modules.pop("spoke.dedup", None)

        fake_dedup = types.ModuleType("spoke.dedup")
        fake_dedup.ontology_term_spans = MagicMock(return_value=[])
        sys.modules["spoke.dedup"] = fake_dedup

        overlay_mod = importlib.import_module("spoke.overlay")
        from spoke.route_keys import default_bindings, BRACKET_RIGHT_KEYCODE

        ghost = overlay_mod.GhostIndicatorLayer(default_bindings())

        ghost.set_sticky(BRACKET_RIGHT_KEYCODE)
        ghost.set_active(None)  # clear transient selection

        # Sticky glow should still render
        alpha = ghost.ghost_alpha(BRACKET_RIGHT_KEYCODE)
        faint_alpha = ghost.ghost_alpha(22)  # some other key, not sticky

        assert alpha > faint_alpha, (
            "Sticky key should still glow even after transient active is cleared"
        )

        sys.modules.pop("spoke.overlay", None)
        sys.modules.pop("spoke.dedup", None)

    def test_clear_sticky_returns_to_faint(self, mock_pyobjc):
        """Clearing sticky state should return the ghost to faint alpha."""
        import importlib
        import sys
        import types

        sys.modules.pop("spoke.overlay", None)
        sys.modules.pop("spoke.route_keys", None)
        sys.modules.pop("spoke.dedup", None)

        fake_dedup = types.ModuleType("spoke.dedup")
        fake_dedup.ontology_term_spans = MagicMock(return_value=[])
        sys.modules["spoke.dedup"] = fake_dedup

        overlay_mod = importlib.import_module("spoke.overlay")
        from spoke.route_keys import default_bindings, BRACKET_RIGHT_KEYCODE

        ghost = overlay_mod.GhostIndicatorLayer(default_bindings())

        ghost.set_sticky(BRACKET_RIGHT_KEYCODE)
        ghost.set_sticky(None)  # clear sticky

        alpha = ghost.ghost_alpha(BRACKET_RIGHT_KEYCODE)
        faint_alpha = overlay_mod._GHOST_FAINT_ALPHA

        assert alpha == faint_alpha, (
            f"After clearing sticky, alpha ({alpha}) should return to faint ({faint_alpha})"
        )

        sys.modules.pop("spoke.overlay", None)
        sys.modules.pop("spoke.dedup", None)
