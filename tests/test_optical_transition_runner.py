"""Contract tests for shared optical-shell transition choreography."""

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


def test_command_overlay_consumes_shared_transition_primitives(mock_pyobjc):
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


def test_transition_runner_materialize_frames_reveal_from_pressure_slit():
    transition = importlib.import_module("spoke.optical_transition")
    runner = transition.OpticalTransitionRunner(_base_shell(), direction=1)

    seed = runner.frame_at(0.0)
    body = runner.frame_at(transition.OPTICAL_MATERIALIZATION_S * 0.60)
    done = runner.frame_at(transition.OPTICAL_MATERIALIZATION_S * 1.20)

    assert seed.progress == pytest.approx(0.0)
    assert seed.main_config["content_width_points"] < 1200.0 * 0.20
    assert seed.main_config["content_height_points"] < 208.0 * 0.035
    assert not seed.body_ready
    assert body.body_ready
    assert done.complete
    assert done.progress == pytest.approx(1.0)
    assert done.main_config == pytest.approx(_base_shell())


def test_transition_runner_dismiss_frames_include_seam_and_radial_sidecars():
    transition = importlib.import_module("spoke.optical_transition")
    runner = transition.OpticalTransitionRunner(
        _base_shell(),
        direction=-1,
        client_id="preview.overlay",
        role="preview",
        z_index=32,
    )

    early = runner.frame_at(0.0)
    seam = runner.frame_at(transition.OPTICAL_MATERIALIZATION_DISMISS_S * 0.85)

    assert early.progress == pytest.approx(1.0)
    assert early.seam_config is None
    assert seam.progress < transition.OPTICAL_MATERIALIZATION_SEAM_OVERLAP_START_PROGRESS
    assert seam.seam_config is not None
    assert seam.seam_config["client_id"] == "preview.overlay.dismiss_seam"
    assert seam.seam_config["role"] == "preview"
    assert seam.seam_config["z_index"] == 42
    assert seam.radial_config is not None
    assert seam.radial_config["client_id"] == "preview.overlay.dismiss_radial_pucker"
    assert seam.radial_config["role"] == "preview"
    assert seam.radial_config["z_index"] == 41


def test_transition_tail_frame_hides_main_client_while_radial_releases():
    transition = importlib.import_module("spoke.optical_transition")

    frame = transition.dismiss_tail_frame(
        _base_shell(),
        progress=0.25,
        client_id="agent.card.1",
        role="agent_card",
        z_index=20,
    )

    assert frame.main_config["visible"] is False
    assert frame.radial_config["visible"] is True
    assert frame.radial_config["client_id"] == "agent.card.1.dismiss_radial_pucker"
    assert frame.radial_config["role"] == "agent_card"
    assert frame.radial_config["z_index"] == 29
