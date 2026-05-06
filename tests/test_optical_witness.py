"""Optical Witness Mode capture policy and artifact tests."""

import json


def _rgb_frame(width: int, height: int, seed: int = 0) -> bytes:
    data = bytearray()
    for y in range(height):
        for x in range(width):
            data.extend(((x + seed) % 256, (y + seed) % 256, (x + y + seed) % 256))
    return bytes(data)


def test_witness_accumulates_bounded_frames_without_writing_until_drain(tmp_path):
    from spoke.optical_witness import (
        OpticalWitnessController,
        OpticalWitnessRGBFrame,
    )

    controller = OpticalWitnessController(enabled=True, output_dir=tmp_path, max_frames=2)
    event_id = controller.begin_lifecycle(
        overlay_kind="assistant",
        phase="summon",
        client_id="assistant.command",
        shell_config={
            "center_x": 5.0,
            "center_y": 4.0,
            "content_width_points": 6.0,
            "content_height_points": 4.0,
            "ring_amplitude_points": 12.5,
        },
        timestamp_monotonic=10.0,
        wall_time_iso="2026-05-06T21:30:00Z",
        source_ref={"branch": "cc/optical-witness-mode", "commit": "abc1234"},
    )

    assert event_id is not None
    for index in range(4):
        controller.observe_frame(
            OpticalWitnessRGBFrame(
                width=10,
                height=8,
                rgb=_rgb_frame(10, 8, seed=index),
                timestamp_monotonic=10.0 + index * 0.016,
                frame_index=index,
            )
        )

    assert list(tmp_path.iterdir()) == []
    job = controller.end_lifecycle(
        event_id,
        timestamp_monotonic=10.080,
        diagnostics={"skipped_frames": 1, "duplicate_frames": 2},
    )

    assert job is not None
    assert len(job.frames) == 2
    assert job.dropped_frame_count == 2
    assert list(tmp_path.iterdir()) == []

    bundle = controller.drain_ready()[0]
    manifest = json.loads((bundle / "manifest.json").read_text())

    assert manifest["overlay_kind"] == "assistant"
    assert manifest["phase"] == "summon"
    assert manifest["client_id"] == "assistant.command"
    assert manifest["frame_count"] == 2
    assert manifest["dropped_frame_count"] == 2
    assert manifest["diagnostics"]["skipped_frames"] == 1
    assert manifest["crop"]["x"] == 2
    assert manifest["crop"]["y"] == 2
    assert manifest["material"]["ring_amplitude_points"] == 12.5
    assert (bundle / "frames" / "frame_0000.ppm").exists()
    assert (bundle / "frames" / "frame_0001.ppm").exists()
    assert (bundle / "contact_sheet.ppm").exists()


def test_disabled_witness_ignores_lifecycle_and_frames(tmp_path):
    from spoke.optical_witness import OpticalWitnessController, OpticalWitnessRGBFrame

    controller = OpticalWitnessController(enabled=False, output_dir=tmp_path)

    event_id = controller.begin_lifecycle(
        overlay_kind="preview",
        phase="dismiss",
        client_id="preview.transcription",
        shell_config={"center_x": 5.0, "center_y": 5.0},
        timestamp_monotonic=1.0,
        wall_time_iso="2026-05-06T21:31:00Z",
        source_ref={},
    )
    controller.observe_frame(
        OpticalWitnessRGBFrame(
            width=2,
            height=2,
            rgb=_rgb_frame(2, 2),
            timestamp_monotonic=1.0,
            frame_index=0,
        )
    )

    assert event_id is None
    assert controller.drain_ready() == []
    assert list(tmp_path.iterdir()) == []

