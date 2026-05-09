"""Fail-first witnesses for preview overlay as a pure House consumer.

These tests assert the contract boundary: preview owns semantic content
(transcript text, RMS signal, recording state) and desired-state emission.
House owns visual execution (animation clocks, alpha, positioning, fill).

Each test should FAIL on the current implementation because the preview
still owns its animation clock, fill layer opacity, and window alpha
directly.  The migration succeeds when all tests pass.
"""

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _make_rect(x, y, width, height):
    return SimpleNamespace(
        origin=SimpleNamespace(x=x, y=y),
        size=SimpleNamespace(width=width, height=height),
    )


class _FakeScreen:
    def __init__(self):
        self._frame = _make_rect(0.0, 0.0, 1440.0, 900.0)

    def frame(self):
        return self._frame

    def backingScaleFactor(self):
        return 2.0


class _FakeWindow:
    def __init__(self):
        self._frame = _make_rect(100.0, 60.0, 1040.0, 520.0)
        self.alpha_calls = []
        self.ordered_front = False
        self.ordered_out = False

    def frame(self):
        return self._frame

    def setFrame_display_animate_(self, frame, _display, _animate):
        self._frame = frame

    def windowNumber(self):
        return 701

    def setAlphaValue_(self, alpha):
        self.alpha_calls.append(alpha)

    def alphaValue(self):
        return self.alpha_calls[-1] if self.alpha_calls else 0.0

    def orderFrontRegardless(self):
        self.ordered_front = True

    def orderOut_(self, sender):
        self.ordered_out = True

    def setIgnoresMouseEvents_(self, v):
        pass


class _FakeLayer:
    def __init__(self, frame):
        self._frame = frame
        self._background_color = None
        self._opacity = None
        self.opacity_calls = []
        self.contents = None
        self.animations = []

    def setFrame_(self, frame):
        if isinstance(frame, tuple):
            origin, size = frame
            self._frame = _make_rect(origin[0], origin[1], size[0], size[1])
        else:
            self._frame = frame

    def frame(self):
        return self._frame

    def setBackgroundColor_(self, color):
        self._background_color = color

    def setOpacity_(self, opacity):
        self._opacity = opacity
        self.opacity_calls.append(opacity)

    def setContents_(self, contents):
        self.contents = contents

    def setCompositingFilter_(self, filter_name):
        self.compositing_filter = filter_name

    def addAnimation_forKey_(self, animation, key):
        self.animations.append((key, animation))


class _FakeView:
    def __init__(self, frame):
        self._frame = frame
        self._layer = _FakeLayer(frame)

    def frame(self):
        return self._frame

    def setFrame_(self, frame):
        self._frame = frame
        self._layer.setFrame_(frame)

    def layer(self):
        return self._layer


class _FakeTextView:
    def __init__(self, frame, text=""):
        self._frame = frame
        self._text = text
        self._container = SimpleNamespace(
            setContainerSize_=lambda s: None,
        )
        self._layout = SimpleNamespace(
            ensureLayoutForTextContainer_=lambda c: None,
            usedRectForTextContainer_=lambda c: _make_rect(0, 0, 0, 64.0),
        )
        self.scrolled_range = None

    def frame(self):
        return self._frame

    def setFrame_(self, frame):
        self._frame = frame

    def string(self):
        return self._text

    def setString_(self, text):
        self._text = text

    def textContainer(self):
        return self._container

    def layoutManager(self):
        return self._layout

    def textStorage(self):
        return None

    def scrollRangeToVisible_(self, visible_range):
        self.scrolled_range = visible_range


class _FakeScrollView:
    def __init__(self, frame, text_view):
        self._frame = frame
        self._text_view = text_view
        self._clip_view = SimpleNamespace(
            bounds=lambda: SimpleNamespace(origin=SimpleNamespace(x=0.0, y=0.0)),
            scrollToPoint_=lambda p: None,
        )
        self.hidden = False

    def frame(self):
        return self._frame

    def setFrame_(self, frame):
        self._frame = frame

    def contentView(self):
        return self._clip_view

    def reflectScrolledClipView_(self, clip_view):
        pass

    def setHidden_(self, hidden):
        self.hidden = hidden


class _FakeClient:
    def __init__(self, identity):
        self.identity = identity
        self.published = []
        self.release_calls = 0

    def publish(self, snapshot):
        self.published.append(snapshot)
        return True

    def release(self):
        self.release_calls += 1


class _FakeHost:
    display_id = "display-42"

    def __init__(self):
        self.registered = []
        self.clients = {}

    def register_client(self, identity, *, window, content_view):
        self.registered.append((identity, window, content_view))
        client = self.clients.get(identity.client_id)
        if client is None:
            client = _FakeClient(identity)
            self.clients[identity.client_id] = client
        return client


class _FakeRegistry:
    def __init__(self, host):
        self.host = host

    def host_for_screen(self, screen):
        return self.host


def _import_overlay(mock_pyobjc):
    sys.modules.pop("spoke.overlay", None)
    sys.modules.pop("spoke.fullscreen_compositor", None)
    overlay_module = importlib.import_module("spoke.overlay")
    overlay_module._start_overlay_fill_worker = lambda work: work()
    return overlay_module


def _make_overlay(overlay_module, monkeypatch):
    monkeypatch.setattr(overlay_module, "NSMakeRect", _make_rect)
    overlay = overlay_module.TranscriptionOverlay.alloc().initWithScreen_(_FakeScreen())
    overlay._window = _FakeWindow()
    overlay._content_view = _FakeView(_make_rect(220.0, 220.0, 600.0, 80.0))
    overlay._text_view = _FakeTextView(_make_rect(0.0, 0.0, 576.0, 64.0))
    overlay._scroll_view = _FakeScrollView(
        _make_rect(12.0, 8.0, 576.0, 64.0),
        overlay._text_view,
    )
    overlay._fill_layer = _FakeLayer(_make_rect(0.0, 0.0, 1040.0, 520.0))
    overlay._brightness = 0.37
    overlay._brightness_target = 0.37
    return overlay


# ── Test: show() must not start a consumer-owned fade timer ──────────


def test_show_does_not_start_consumer_owned_fade_timer(mock_pyobjc, monkeypatch):
    """Preview show() must emit a materialize request to House but must NOT
    start its own NSTimer-based fade animation.  House owns the visual clock.

    This test SHOULD FAIL on the current implementation because show()
    currently starts a 12-step fade timer driving setAlphaValue_() directly.
    """
    overlay_module = _import_overlay(mock_pyobjc)
    overlay = _make_overlay(overlay_module, monkeypatch)
    host = _FakeHost()
    overlay.set_compositor_registry(_FakeRegistry(host))

    monkeypatch.setattr(
        overlay_module,
        "_fill_field_to_image",
        lambda _a, _r, _g, _b: ("img", b"payload"),
    )

    overlay.show()

    # Consumer must NOT have started a fade timer
    assert overlay._fade_timer is None, (
        "preview must not own a fade animation timer — House owns the visual clock"
    )


# ── Test: show() must not call setAlphaValue_ to zero before materialize ──


def test_show_does_not_drive_window_alpha_directly(mock_pyobjc, monkeypatch):
    """Preview show() must not set window alpha to 0.0 and then animate it
    up with a consumer-owned timer.  The window should stay fully present
    (alpha 1.0) while House/compositor owns the visual lifecycle envelope.

    This test SHOULD FAIL because show() currently calls setAlphaValue_(0.0)
    and then uses a stepped timer to fade from 0 to 1.
    """
    overlay_module = _import_overlay(mock_pyobjc)
    overlay = _make_overlay(overlay_module, monkeypatch)
    host = _FakeHost()
    overlay.set_compositor_registry(_FakeRegistry(host))

    monkeypatch.setattr(
        overlay_module,
        "_fill_field_to_image",
        lambda _a, _r, _g, _b: ("img", b"payload"),
    )

    overlay.show()

    # The window must not have been set to alpha 0.0 — consumer does not
    # own the visual lifecycle.  If any alpha calls were made, none should
    # be 0.0 (the "start invisible, fade in" pattern).
    zero_alpha_calls = [a for a in overlay._window.alpha_calls if a == 0.0]
    assert len(zero_alpha_calls) == 0, (
        "preview must not set window alpha to 0.0 — "
        "House owns the materialize envelope, not the consumer"
    )


# ── Test: hide() must not start a consumer-owned fade-out timer ──────


def test_hide_does_not_start_consumer_owned_fade_timer(mock_pyobjc, monkeypatch):
    """Preview hide() must emit a dismiss request to House but must NOT
    start its own fade-out animation timer.

    This test SHOULD FAIL because hide() currently calls _start_fade_out()
    which creates a 12-step NSTimer driving setAlphaValue_() to 0.
    """
    overlay_module = _import_overlay(mock_pyobjc)
    overlay = _make_overlay(overlay_module, monkeypatch)
    host = _FakeHost()
    overlay.set_compositor_registry(_FakeRegistry(host))

    monkeypatch.setattr(
        overlay_module,
        "_fill_field_to_image",
        lambda _a, _r, _g, _b: ("img", b"payload"),
    )

    # Show first, then hide
    overlay.show()
    overlay._fade_timer = None  # clear any show timer to isolate hide behavior
    overlay._window.alpha_calls.clear()

    overlay.hide()

    assert overlay._fade_timer is None, (
        "preview must not own a fade-out animation timer — House owns the dismiss envelope"
    )


# ── Test: amplitude updates must not drive fill layer opacity directly ──


def test_amplitude_does_not_drive_fill_layer_opacity(mock_pyobjc, monkeypatch):
    """The preview consumer may provide RMS amplitude as a signal to House,
    but must not call _fill_layer.setOpacity_() directly.  Fill material
    is House-owned.

    This test SHOULD FAIL because update_text_amplitude() currently
    computes fill_opacity from amplitude and calls _fill_layer.setOpacity_().
    """
    overlay_module = _import_overlay(mock_pyobjc)
    overlay = _make_overlay(overlay_module, monkeypatch)
    host = _FakeHost()
    overlay.set_compositor_registry(_FakeRegistry(host))
    overlay._visible = True

    # Clear any existing opacity calls from setup
    overlay._fill_layer.opacity_calls.clear()

    # Simulate a series of amplitude updates
    for amp in [0.1, 0.3, 0.5, 0.2, 0.0]:
        overlay.update_text_amplitude(amp)

    # Consumer must not have directly driven fill layer opacity
    assert len(overlay._fill_layer.opacity_calls) == 0, (
        "preview must not call _fill_layer.setOpacity_() directly — "
        "fill material opacity is House-owned; consumer provides RMS as a signal"
    )


# ── Test: amplitude updates must not trigger CPU fill image rebuilds ──


def test_amplitude_does_not_trigger_fill_image_rebuild(mock_pyobjc, monkeypatch):
    """When brightness changes during amplitude updates, the preview must not
    rebuild SDF fill images on the CPU.  Fill/SDF generation is House-owned.

    This test SHOULD FAIL because update_text_amplitude() currently calls
    _apply_ridge_masks() when brightness drifts enough.
    """
    overlay_module = _import_overlay(mock_pyobjc)
    overlay = _make_overlay(overlay_module, monkeypatch)
    overlay._visible = True
    overlay._brightness_target = 0.8  # big brightness change to trigger rebuild

    ridge_mask_calls = []
    original_apply = overlay._apply_ridge_masks

    def _tracking_apply(*args, **kwargs):
        ridge_mask_calls.append(args)
        return original_apply(*args, **kwargs)

    overlay._apply_ridge_masks = _tracking_apply

    # Simulate amplitude ticks that would cause brightness to chase target
    for _ in range(30):
        overlay.update_text_amplitude(0.3)

    assert len(ridge_mask_calls) == 0, (
        "preview must not rebuild SDF fill images during amplitude updates — "
        "fill/SDF generation is House-owned"
    )


# ── Test: materialize snapshot must carry audio_rms signal name ──────


def test_preview_snapshot_carries_audio_rms_signal(mock_pyobjc, monkeypatch):
    """When preview publishes a compositor snapshot with live audio, the
    optical field request should carry an audio_rms signal rather than
    the consumer directly driving fill opacity.

    This test will fail until the contract adds audio_rms as a signal
    and the preview consumer emits it.
    """
    overlay_module = _import_overlay(mock_pyobjc)
    overlay = _make_overlay(overlay_module, monkeypatch)
    host = _FakeHost()
    overlay.set_compositor_registry(_FakeRegistry(host))

    monkeypatch.setattr(
        overlay_module,
        "_fill_field_to_image",
        lambda _a, _r, _g, _b: ("img", b"payload"),
    )

    overlay.show()
    overlay._text_amplitude = 0.5  # simulate active audio

    # Publish a rest snapshot with live audio
    overlay._publish_preview_compositor_snapshot(visible=True, state="rest")

    snapshot = host.clients["preview.transcription"].published[-1]
    optical_field = dict(snapshot.optical_field)

    # The optical field should carry signal metadata for audio_rms
    signals = optical_field.get("signals", ())
    signal_names = {s.get("name") if isinstance(s, dict) else getattr(s, "name", None)
                    for s in signals}
    assert "audio_rms" in signal_names, (
        "preview optical field must carry an audio_rms signal — "
        "consumer provides amplitude data, House owns how it maps to fill/material"
    )
