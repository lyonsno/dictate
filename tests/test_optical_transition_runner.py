"""Contract tests for the shared optical-shell transition runner."""

from __future__ import annotations

import importlib
import sys

import pytest


def _import_command_overlay_with_fakes(mock_pyobjc):
    for name in list(sys.modules):
        if any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in ("objc", "Quartz", "Foundation", "AppKit", "PyObjCTools")
        ):
            sys.modules.pop(name, None)
    sys.modules.update(mock_pyobjc)
    sys.modules["Quartz.CoreGraphics"] = mock_pyobjc["Quartz"]
    sys.modules.pop("spoke.command_overlay", None)
    sys.modules.pop("spoke.optical_transition", None)
    spoke_pkg = sys.modules.get("spoke")
    if spoke_pkg is not None and hasattr(spoke_pkg, "optical_transition"):
        delattr(spoke_pkg, "optical_transition")
    return importlib.import_module("spoke.command_overlay")


def _base_shell() -> dict[str, float]:
    return {
        "center_x": 640.0,
        "center_y": 420.0,
        "content_width_points": 1200.0,
        "content_height_points": 208.0,
        "corner_radius_points": 32.0,
        "core_magnification": 14.0,
        "ring_amplitude_points": 30.0,
        "tail_amplitude_points": 8.0,
        "cleanup_blur_radius_points": 0.75,
    }


def test_command_overlay_consumes_shared_transition_runner_for_golden_path(
    mock_pyobjc,
):
    command_overlay = _import_command_overlay_with_fakes(mock_pyobjc)
    transition = importlib.import_module("spoke.optical_transition")

    assert (
        command_overlay._materialized_optical_shell_config
        is transition.materialized_shell_config
    )
    assert command_overlay._materialization_fill_state is transition.materialization_fill_state
    assert (
        command_overlay._dismiss_materialization_fill_state
        is transition.dismiss_materialization_fill_state
    )
    assert (
        command_overlay._dismiss_seam_latch_shell_config
        is transition.dismiss_seam_latch_shell_config
    )
    assert (
        command_overlay._dismiss_radial_pucker_shell_config
        is transition.dismiss_radial_pucker_shell_config
    )
    assert (
        command_overlay._hidden_dismiss_main_shell_config
        is transition.hidden_dismiss_main_shell_config
    )


def test_shared_transition_runner_preserves_assistant_golden_dismiss_identity():
    transition = importlib.import_module("spoke.optical_transition")

    seam = transition.dismiss_seam_latch_shell_config(_base_shell(), 0.20)
    radial = transition.dismiss_radial_pucker_shell_config(_base_shell(), 0.20)
    hidden = transition.hidden_dismiss_main_shell_config(_base_shell())

    assert seam["client_id"] == "assistant.command.dismiss_seam"
    assert seam["role"] == "assistant"
    assert seam["visible"] is True
    assert seam["z_index"] == 10
    assert seam["warp_mode"] == pytest.approx(1.0)
    assert seam["mip_blur_strength"] == pytest.approx(0.0)
    assert seam["cleanup_blur_radius_points"] == pytest.approx(0.0)
    assert seam["continuous_present"] is True
    assert seam["scar_amount"] > 0.0

    assert radial["client_id"] == "assistant.command.dismiss_radial_pucker"
    assert radial["role"] == "assistant"
    assert radial["visible"] is True
    assert radial["z_index"] == 9
    assert radial["warp_mode"] == pytest.approx(2.0)
    assert radial["mip_blur_strength"] == pytest.approx(0.0)
    assert radial["cleanup_blur_radius_points"] == pytest.approx(0.0)
    assert radial["continuous_present"] is True

    assert hidden["visible"] is False
    assert hidden["continuous_present"] is True
    assert hidden["mip_blur_strength"] == pytest.approx(0.0)
    assert hidden["cleanup_blur_radius_points"] == pytest.approx(0.0)


def test_shared_transition_runner_accepts_consumer_identity_without_private_assistant_ids():
    transition = importlib.import_module("spoke.optical_transition")

    seam = transition.dismiss_seam_latch_shell_config(
        _base_shell(),
        0.20,
        client_id="preview.overlay.dismiss_seam",
        role="preview",
        z_index=32,
    )
    radial = transition.dismiss_radial_pucker_shell_config(
        _base_shell(),
        0.20,
        client_id="preview.overlay.dismiss_radial",
        role="preview",
        z_index=31,
    )

    assert seam["client_id"] == "preview.overlay.dismiss_seam"
    assert seam["role"] == "preview"
    assert seam["z_index"] == 32
    assert seam["visible"] is True
    assert seam["continuous_present"] is True

    assert radial["client_id"] == "preview.overlay.dismiss_radial"
    assert radial["role"] == "preview"
    assert radial["z_index"] == 31
    assert radial["visible"] is True
    assert radial["continuous_present"] is True
