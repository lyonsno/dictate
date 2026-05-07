from __future__ import annotations

from dataclasses import fields

import pytest

from spoke.optical_field import (
    OpticalFieldBounds,
    OpticalFieldCoordinateContext,
    OpticalFieldDisturbance,
    OpticalFieldMotionIntent,
    OpticalFieldPlaceholderBackend,
    OpticalFieldProfileRef,
    OpticalFieldRequest,
    OpticalFieldSignal,
    OpticalFieldSlotOverride,
    compile_placeholder_shell_config,
    normalize_optical_field_bounds,
)


def test_placeholder_backend_preserves_contract_identity_and_profile_slot_metadata():
    backend = OpticalFieldPlaceholderBackend()
    request = OpticalFieldRequest(
        caller_id="agent.card.codex-1",
        bounds=OpticalFieldBounds(x=40.0, y=80.0, width=320.0, height=96.0),
        role="agent_card",
        state="rest",
        profile=OpticalFieldProfileRef(
            base="agent_card",
            slots={
                "rest": OpticalFieldSlotOverride(params={"core_magnification": 1.08}),
                "dismiss": OpticalFieldSlotOverride(params={"mip_blur_strength": 0.0}),
            },
        ),
        disturbances=(
            OpticalFieldDisturbance(
                disturbance_id="ready-pulse",
                kind="readiness_pulse",
                mode="ephemeral",
                strength=0.35,
            ),
        ),
        z_index=7,
    )

    backend.upsert(request)

    (shell_config,) = backend.compile_shell_configs()
    assert shell_config["client_id"] == "agent.card.codex-1"
    assert shell_config["role"] == "agent_card"
    assert shell_config["z_index"] == 7
    assert shell_config["content_width_points"] == pytest.approx(320.0)
    assert shell_config["content_height_points"] == pytest.approx(96.0)
    assert shell_config["center_x"] == pytest.approx(200.0)
    assert shell_config["center_y"] == pytest.approx(128.0)
    assert shell_config["core_magnification"] == pytest.approx(1.08)
    assert shell_config["optical_field"]["caller_id"] == "agent.card.codex-1"
    assert shell_config["optical_field"]["profile"] == "agent_card"
    assert shell_config["optical_field"]["state"] == "rest"
    assert shell_config["optical_field"]["slot"] == "rest"
    assert shell_config["optical_field"]["disturbances"] == ("ready-pulse",)


def test_profile_slots_override_independently_without_leaking_between_lifecycle_states():
    backend = OpticalFieldPlaceholderBackend()
    profile = OpticalFieldProfileRef(
        base="assistant_shell",
        slots={
            "materialize": OpticalFieldSlotOverride(
                params={"ring_amplitude_frac": 0.20, "mip_blur_strength": 0.25}
            ),
            "dismiss": OpticalFieldSlotOverride(
                params={"ring_amplitude_frac": 0.04, "mip_blur_strength": 0.0}
            ),
        },
    )
    bounds = OpticalFieldBounds(x=10.0, y=20.0, width=600.0, height=180.0)

    backend.upsert(
        OpticalFieldRequest(
            caller_id="assistant",
            bounds=bounds,
            role="assistant",
            state="materialize",
            profile=profile,
        )
    )
    materialize = backend.compile_shell_configs()[0]

    backend.upsert(
        OpticalFieldRequest(
            caller_id="assistant",
            bounds=bounds,
            role="assistant",
            state="dismiss",
            profile=profile,
        )
    )
    dismiss = backend.compile_shell_configs()[0]

    assert materialize["ring_amplitude_points"] == pytest.approx(36.0)
    assert materialize["mip_blur_strength"] == pytest.approx(0.25)
    assert dismiss["ring_amplitude_points"] == pytest.approx(7.2)
    assert dismiss["mip_blur_strength"] == pytest.approx(0.0)


def test_normalized_profile_values_scale_with_geometry_not_raw_preview_tuning():
    backend = OpticalFieldPlaceholderBackend()
    profile = OpticalFieldProfileRef(base="agent_card")

    backend.upsert(
        OpticalFieldRequest(
            caller_id="small",
            bounds=OpticalFieldBounds(x=0.0, y=0.0, width=240.0, height=80.0),
            role="agent_card",
            state="rest",
            profile=profile,
        )
    )
    backend.upsert(
        OpticalFieldRequest(
            caller_id="large",
            bounds=OpticalFieldBounds(x=0.0, y=0.0, width=960.0, height=320.0),
            role="agent_card",
            state="rest",
            profile=profile,
        )
    )

    small, large = backend.compile_shell_configs()
    assert large["ring_amplitude_points"] / small["ring_amplitude_points"] == pytest.approx(4.0)
    assert large["band_width_points"] / small["band_width_points"] == pytest.approx(4.0)
    assert large["corner_radius_points"] / small["corner_radius_points"] == pytest.approx(4.0)


def test_backend_upsert_and_remove_are_stable_by_caller_id():
    backend = OpticalFieldPlaceholderBackend()
    backend.upsert(
        OpticalFieldRequest(
            caller_id="preview",
            bounds=OpticalFieldBounds(x=0.0, y=0.0, width=180.0, height=42.0),
            role="preview",
            state="rest",
        )
    )
    backend.upsert(
        OpticalFieldRequest(
            caller_id="preview",
            bounds=OpticalFieldBounds(x=10.0, y=20.0, width=240.0, height=64.0),
            role="preview",
            state="rest",
        )
    )

    (updated,) = backend.compile_shell_configs()
    assert updated["center_x"] == pytest.approx(130.0)
    assert updated["center_y"] == pytest.approx(52.0)

    assert backend.remove("preview") is True
    assert backend.compile_shell_configs() == ()
    assert backend.remove("preview") is False


def test_placeholder_configs_survive_fullscreen_compositor_snapshot_round_trip():
    from spoke.fullscreen_compositor import (
        OverlayClientIdentity,
        _snapshot_from_shell_config,
        _snapshot_to_shell_config,
    )

    backend = OpticalFieldPlaceholderBackend()
    backend.upsert(
        OpticalFieldRequest(
            caller_id="agent.card.codex-1",
            bounds=OpticalFieldBounds(x=40.0, y=80.0, width=320.0, height=96.0),
            role="agent_card",
            state="rest",
            profile=OpticalFieldProfileRef(base="agent_card"),
        )
    )
    (shell_config,) = backend.compile_shell_configs()

    snapshot = _snapshot_from_shell_config(
        OverlayClientIdentity(
            client_id="agent.card.codex-1",
            display_id=1,
            role="preview",
        ),
        shell_config,
        generation=3,
    )
    round_tripped = _snapshot_to_shell_config(snapshot)

    assert round_tripped["optical_field"] == shell_config["optical_field"]


def test_public_consumer_contract_round_trips_coordinate_content_motion_and_freshness():
    request = OpticalFieldRequest(
        caller_id="semantic.assistant",
        continuity_key="thread.codex-123",
        bounds=OpticalFieldBounds(x=100.0, y=140.0, width=640.0, height=220.0),
        content_frame=OpticalFieldBounds(x=124.0, y=164.0, width=592.0, height=172.0),
        coordinate_space="screen_points",
        display_epoch="display-main:42",
        source_epoch="capture:vlm:17",
        freshness_epoch="request:99",
        role="assistant_shell",
        state="retarget",
        presentation_layer="assistant",
        layout_recipe="semantic-placement-candidate",
        motion=OpticalFieldMotionIntent(
            strategy="auto",
            urgency="normal",
            latency_mask="pending_resolution",
            params={"overlap_threshold": 0.50},
        ),
        continuity="preserve_identity",
        signals=(
            OpticalFieldSignal(
                name="audio_rms",
                value=0.42,
                freshness_epoch="audio:5",
                params={"window_ms": 80.0},
            ),
            OpticalFieldSignal(
                name="pending_resolution",
                value=True,
                freshness_epoch="vlm:pending",
            ),
        ),
        provisional=True,
        confidence=0.76,
        z_index=9,
    )

    shell_config = compile_placeholder_shell_config(request)
    optical_field = shell_config["optical_field"]

    assert optical_field["caller_id"] == "semantic.assistant"
    assert optical_field["continuity_key"] == "thread.codex-123"
    assert optical_field["lifecycle"] == "retarget"
    assert optical_field["bounds"] == {
        "x": 100.0,
        "y": 140.0,
        "width": 640.0,
        "height": 220.0,
    }
    assert optical_field["content_frame"] == {
        "x": 124.0,
        "y": 164.0,
        "width": 592.0,
        "height": 172.0,
    }
    assert optical_field["coordinate_space"] == "screen_points"
    assert optical_field["display_epoch"] == "display-main:42"
    assert optical_field["source_epoch"] == "capture:vlm:17"
    assert optical_field["freshness_epoch"] == "request:99"
    assert optical_field["presentation_layer"] == "assistant"
    assert optical_field["layout_recipe"] == "semantic-placement-candidate"
    assert optical_field["motion"] == {
        "strategy": "auto",
        "urgency": "normal",
        "latency_mask": "pending_resolution",
        "params": {"overlap_threshold": 0.50},
    }
    assert optical_field["continuity"] == "preserve_identity"
    assert optical_field["signals"] == (
        {
            "name": "audio_rms",
            "value": 0.42,
            "freshness_epoch": "audio:5",
            "params": {"window_ms": 80.0},
        },
        {
            "name": "pending_resolution",
            "value": True,
            "freshness_epoch": "vlm:pending",
            "params": {},
        },
    )
    assert optical_field["provisional"] is True
    assert optical_field["final"] is False
    assert optical_field["confidence"] == pytest.approx(0.76)


def test_production_consumer_request_schema_excludes_progress_and_phase_custody():
    request_field_names = {field.name for field in fields(OpticalFieldRequest)}
    disturbance_field_names = {field.name for field in fields(OpticalFieldDisturbance)}
    signal_field_names = {field.name for field in fields(OpticalFieldSignal)}

    assert "progress" not in request_field_names
    assert "phase" not in request_field_names
    assert "progress" not in disturbance_field_names
    assert "phase" not in disturbance_field_names
    assert "progress" not in signal_field_names
    assert "phase" not in signal_field_names

    kwargs = {
        "caller_id": "preview",
        "bounds": OpticalFieldBounds(x=0.0, y=0.0, width=180.0, height=42.0),
        "role": "preview",
    }
    with pytest.raises(TypeError):
        OpticalFieldRequest(**kwargs, progress=0.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        OpticalFieldRequest(**kwargs, phase=0.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="consumer-authored progress/phase"):
        OpticalFieldSignal(name="progress", value=0.5)
    with pytest.raises(ValueError, match="consumer-authored progress/phase"):
        OpticalFieldSignal(name="transition.phase", value=0.5)


def test_legacy_minimal_requests_compile_with_explicit_public_contract_defaults():
    request = OpticalFieldRequest(
        caller_id="assistant",
        bounds=OpticalFieldBounds(x=16.0, y=24.0, width=640.0, height=180.0),
        role="assistant_shell",
    )

    optical_field = compile_placeholder_shell_config(request)["optical_field"]

    assert optical_field["continuity_key"] == "assistant"
    assert optical_field["lifecycle"] == "rest"
    assert optical_field["bounds"] == optical_field["content_frame"]
    assert optical_field["coordinate_space"] == "display_local"
    assert optical_field["display_epoch"] is None
    assert optical_field["source_epoch"] is None
    assert optical_field["freshness_epoch"] is None
    assert optical_field["presentation_layer"] == "default"
    assert optical_field["layout_recipe"] == "direct_positioned"
    assert optical_field["motion"]["strategy"] == "auto"
    assert optical_field["continuity"] == "preserve_identity"
    assert optical_field["signals"] == ()
    assert optical_field["provisional"] is False
    assert optical_field["final"] is True
    assert optical_field["confidence"] is None


def test_backing_pixel_bounds_normalize_to_display_points_with_scale_and_epoch_metadata():
    bounds = OpticalFieldBounds(x=200.0, y=100.0, width=640.0, height=192.0)
    context = OpticalFieldCoordinateContext(
        coordinate_space="backing_pixels",
        display_id="main-display",
        display_epoch="display-7",
        source_epoch="capture-3",
        backing_scale=2.0,
    )

    normalized = normalize_optical_field_bounds(bounds, context)

    assert normalized == OpticalFieldBounds(x=100.0, y=50.0, width=320.0, height=96.0)

    backend = OpticalFieldPlaceholderBackend(display_epochs={"main-display": "display-7"})
    backend.upsert(
        OpticalFieldRequest(
            caller_id="agent.card.pixel-space",
            bounds=bounds,
            role="agent_card",
            coordinate_context=context,
        )
    )
    (shell_config,) = backend.compile_shell_configs()

    assert shell_config["center_x"] == pytest.approx(260.0)
    assert shell_config["center_y"] == pytest.approx(98.0)
    assert shell_config["optical_field"]["coordinate_space"] == "display_points"
    assert shell_config["optical_field"]["source_coordinate_space"] == "backing_pixels"
    assert shell_config["optical_field"]["display_id"] == "main-display"
    assert shell_config["optical_field"]["display_epoch"] == "display-7"
    assert shell_config["optical_field"]["source_epoch"] == "capture-3"
    assert shell_config["optical_field"]["backing_scale"] == pytest.approx(2.0)


def test_backing_pixel_bounds_without_scale_fail_loudly_instead_of_impersonating_points():
    context = OpticalFieldCoordinateContext(
        coordinate_space="backing_pixels",
        display_id="main-display",
        display_epoch="display-7",
    )

    with pytest.raises(ValueError, match="backing_scale"):
        normalize_optical_field_bounds(
            OpticalFieldBounds(x=200.0, y=100.0, width=640.0, height=192.0),
            context,
        )


def test_parent_local_optical_bounds_and_content_frame_compile_as_distinct_display_rects():
    backend = OpticalFieldPlaceholderBackend(display_epochs={"main-display": "display-7"})
    backend.upsert(
        OpticalFieldRequest(
            caller_id="agent.card.parent-local",
            bounds=OpticalFieldBounds(x=20.0, y=10.0, width=320.0, height=96.0),
            content_frame=OpticalFieldBounds(x=36.0, y=22.0, width=260.0, height=52.0),
            role="agent_card",
            coordinate_context=OpticalFieldCoordinateContext(
                coordinate_space="parent_points",
                display_id="main-display",
                display_epoch="display-7",
                parent_origin=(100.0, 200.0),
            ),
            content_coordinate_context=OpticalFieldCoordinateContext(
                coordinate_space="content_points",
                display_id="main-display",
                display_epoch="display-7",
                content_origin=(120.0, 214.0),
            ),
        )
    )

    (shell_config,) = backend.compile_shell_configs()

    assert shell_config["center_x"] == pytest.approx(280.0)
    assert shell_config["center_y"] == pytest.approx(258.0)
    assert shell_config["content_width_points"] == pytest.approx(320.0)
    assert shell_config["content_height_points"] == pytest.approx(96.0)
    assert shell_config["optical_field"]["bounds"] == {
        "x": 120.0,
        "y": 210.0,
        "width": 320.0,
        "height": 96.0,
    }
    assert shell_config["optical_field"]["content_frame"] == {
        "x": 156.0,
        "y": 236.0,
        "width": 260.0,
        "height": 52.0,
    }


def test_backend_rejects_stale_display_and_capture_epochs_before_compiling_geometry():
    backend = OpticalFieldPlaceholderBackend(
        display_epochs={"main-display": "display-7"},
        source_epochs={"main-display": "capture-3"},
    )

    with pytest.raises(ValueError, match="stale display_epoch"):
        backend.upsert(
            OpticalFieldRequest(
                caller_id="agent.card.old-display",
                bounds=OpticalFieldBounds(x=0.0, y=0.0, width=100.0, height=40.0),
                role="agent_card",
                coordinate_context=OpticalFieldCoordinateContext(
                    coordinate_space="display_points",
                    display_id="main-display",
                    display_epoch="display-6",
                    source_epoch="capture-3",
                ),
            )
        )

    with pytest.raises(ValueError, match="stale source_epoch"):
        backend.upsert(
            OpticalFieldRequest(
                caller_id="agent.card.old-capture",
                bounds=OpticalFieldBounds(x=0.0, y=0.0, width=100.0, height=40.0),
                role="agent_card",
                coordinate_context=OpticalFieldCoordinateContext(
                    coordinate_space="display_points",
                    display_id="main-display",
                    display_epoch="display-7",
                    source_epoch="capture-2",
                ),
            )
        )


def test_material_signals_compile_as_finite_material_basis_not_shader_knobs():
    backend = OpticalFieldPlaceholderBackend()
    backend.upsert(
        OpticalFieldRequest(
            caller_id="assistant.command",
            bounds=OpticalFieldBounds(x=10.0, y=20.0, width=600.0, height=160.0),
            role="assistant_shell",
            state="rest",
            profile=OpticalFieldProfileRef(base="assistant_shell"),
            signals=(
                OpticalFieldSignal(name="background_luminance", value=0.78),
                OpticalFieldSignal(name="text_contrast_bias", value=0.64),
                OpticalFieldSignal(name="ridge_emphasis", value=0.35),
            ),
        )
    )

    (shell_config,) = backend.compile_shell_configs()

    assert shell_config["gpu_material_enabled"] == pytest.approx(1.0)
    assert shell_config["gpu_material_brightness"] == pytest.approx(0.78)
    assert shell_config["gpu_material_text_contrast_bias"] == pytest.approx(0.64)
    assert shell_config["gpu_material_ridge_emphasis"] == pytest.approx(0.35)
    assert shell_config["optical_field"]["signals"] == (
        {"name": "background_luminance", "value": 0.78, "freshness_epoch": None, "params": {}},
        {"name": "text_contrast_bias", "value": 0.64, "freshness_epoch": None, "params": {}},
        {"name": "ridge_emphasis", "value": 0.35, "freshness_epoch": None, "params": {}},
    )
    assert "shader_params" not in shell_config["optical_field"]


def test_unknown_signals_do_not_compile_into_gpu_material_knobs():
    shell_config = compile_placeholder_shell_config(
        OpticalFieldRequest(
            caller_id="assistant.command",
            bounds=OpticalFieldBounds(x=10.0, y=20.0, width=600.0, height=160.0),
            role="assistant_shell",
            signals=(OpticalFieldSignal(name="fragment_shader_uniform", value=0.5),),
        )
    )

    assert "gpu_material_enabled" not in shell_config
    assert shell_config["optical_field"]["signals"] == (
        {"name": "fragment_shader_uniform", "value": 0.5, "freshness_epoch": None, "params": {}},
    )
