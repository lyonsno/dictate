"""Tests for the shared fullscreen compositor adapter."""

from types import SimpleNamespace


def test_overlay_compositor_session_exposes_refresh_brightness():
    from spoke.fullscreen_compositor import _OverlayCompositorSession

    calls = []

    host = SimpleNamespace(
        refresh_brightness_for_client=lambda client_id: calls.append(client_id),
        sampled_brightness_for_client=lambda client_id: 0.73,
    )
    session = _OverlayCompositorSession(host, "overlay:123")

    session.refresh_brightness()

    assert calls == ["overlay:123"]
    assert session.sampled_brightness == 0.73
