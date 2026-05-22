import json
from datetime import datetime, timezone

from spoke.retina_lasso_witness import (
    build_cropped_filmstrips_from_manifest,
    build_filmstrip_from_manifest,
    build_launch_target_command,
    build_retina_lasso_command,
    capture_count_for_window,
    collect_trace_events,
    drive_hammer_toggles,
    drive_retarget_during_dismiss_pattern,
    resolve_trace_path,
    wait_for_trace_event,
    write_witness_index,
)


def test_capture_count_for_window_rounds_up():
    assert capture_count_for_window(2.1, 10.0) == 21
    assert capture_count_for_window(0.01, 10.0) == 1


def test_build_retina_lasso_command_preserves_custody_fields(tmp_path):
    command = build_retina_lasso_command(
        output_dir=tmp_path,
        count=3,
        interval_seconds=0.125,
        lane="warpstorm-pit-boss",
        diaulos="Warpstorm Pit Boss",
        source_app="Spoke",
        source_window="Command Overlay",
    )

    assert command[:3] == ["uv", "run", "perceptasia-screen-capture"]
    assert command[command.index("--output-dir") + 1] == str(tmp_path)
    assert command[command.index("--count") + 1] == "3"
    assert command[command.index("--interval") + 1] == "0.125000"
    assert command[command.index("--lane") + 1] == "warpstorm-pit-boss"
    assert command[command.index("--diaulos") + 1] == "Warpstorm Pit Boss"


def test_build_launch_target_command_uses_repo_script(tmp_path):
    command = build_launch_target_command(tmp_path, "habeas_target")

    assert command == [str(tmp_path / "scripts" / "launch-target.sh"), "habeas_target"]


def test_drive_hammer_toggles_posts_exact_count_without_trailing_sleep():
    calls = []
    sleeps = []

    def toggle_chord(**kwargs):
        calls.append(kwargs)

    drive_hammer_toggles(
        count=3,
        interval_seconds=0.2,
        key_pause_seconds=0.01,
        toggle_chord=toggle_chord,
        sleep=sleeps.append,
    )

    assert calls == [
        {"key_pause_seconds": 0.01},
        {"key_pause_seconds": 0.01},
        {"key_pause_seconds": 0.01},
    ]
    assert sleeps == [0.2, 0.2]


def test_drive_retarget_during_dismiss_pattern_hits_ordered_edges():
    calls = []
    sleeps = []

    def toggle_chord(**kwargs):
        calls.append(kwargs)

    drive_retarget_during_dismiss_pattern(
        repeats=2,
        open_dwell_seconds=0.7,
        dismiss_retarget_delay_seconds=0.08,
        reopen_dwell_seconds=0.6,
        cycle_pause_seconds=0.2,
        key_pause_seconds=0.01,
        toggle_chord=toggle_chord,
        sleep=sleeps.append,
    )

    assert calls == [{"key_pause_seconds": 0.01}] * 8
    assert sleeps == [0.7, 0.08, 0.6, 0.2, 0.7, 0.08, 0.6]


def test_collect_trace_events_filters_to_capture_window(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                json.dumps({"timestamp": "2026-05-22T00:00:00Z", "event": "before"}),
                json.dumps({"timestamp": "2026-05-22T00:00:02Z", "event": "overlay.show.begin"}),
                json.dumps({"timestamp": "2026-05-22T00:00:03-00:00", "event": "overlay.visual_ready.push"}),
                json.dumps({"timestamp": "2026-05-22T00:00:05Z", "event": "after"}),
                "not-json",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    events = collect_trace_events(
        trace_path,
        started_at=datetime(2026, 5, 22, 0, 0, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 5, 22, 0, 0, 4, tzinfo=timezone.utc),
    )

    assert [event["event"] for event in events] == [
        "overlay.show.begin",
        "overlay.visual_ready.push",
    ]
    assert [event["trace_line"] for event in events] == [2, 3]


def test_write_witness_index_links_manifest_and_trace_events(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"frames": [{"path": "a.png"}, {"path": "b.png"}]}),
        encoding="utf-8",
    )

    index_path = write_witness_index(
        output_dir=tmp_path,
        trace_path=tmp_path / "trace.jsonl",
        started_at=datetime(2026, 5, 22, 0, 0, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 5, 22, 0, 0, 2, tzinfo=timezone.utc),
        command=["uv", "run", "perceptasia-screen-capture"],
        trace_events=[{"event": "overlay.show.begin"}],
    )

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "spoke.retina_lasso_trace_witness.v1"
    assert payload["frame_count"] == 2
    assert payload["trace_event_count"] == 1
    assert payload["trace_events"][0]["event"] == "overlay.show.begin"


def test_write_witness_index_records_filmstrip_path(tmp_path):
    index_path = write_witness_index(
        output_dir=tmp_path,
        trace_path=tmp_path / "trace.jsonl",
        started_at=datetime(2026, 5, 22, 0, 0, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 5, 22, 0, 0, 2, tzinfo=timezone.utc),
        command=["uv", "run", "perceptasia-screen-capture"],
        trace_events=[],
        filmstrip_path=tmp_path / "filmstrip.png",
    )

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["filmstrip"] == str(tmp_path / "filmstrip.png")


def test_build_filmstrip_from_manifest_samples_capture_frames(tmp_path):
    from PIL import Image

    frames = []
    for idx in range(5):
        path = tmp_path / f"frame-{idx}.png"
        Image.new("RGB", (80, 40), (idx * 30, idx * 20, idx * 10)).save(path)
        frames.append({"path": path.name})
    (tmp_path / "manifest.json").write_text(
        json.dumps({"frames": frames}),
        encoding="utf-8",
    )

    filmstrip = build_filmstrip_from_manifest(
        output_dir=tmp_path,
        max_frames=3,
        columns=3,
        thumb_width=40,
        gutter=2,
        label_height=0,
    )

    assert filmstrip == tmp_path / "filmstrip.png"
    assert filmstrip.exists()
    with Image.open(filmstrip) as image:
        assert image.width == 3 * 40 + 4 * 2
        assert image.height == 20 + 2 * 2


def test_wait_for_trace_event_ignores_old_lines_and_returns_new_event(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        json.dumps({"timestamp": "2026-05-22T00:00:00Z", "event": "overlay.show.begin"})
        + "\n",
        encoding="utf-8",
    )
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        trace_path.write_text(
            trace_path.read_text(encoding="utf-8")
            + json.dumps(
                {
                    "timestamp": "2026-05-22T00:00:02Z",
                    "event": "overlay.show.begin",
                    "presentation_generation": 12,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    event = wait_for_trace_event(
        trace_path,
        event_name="overlay.show.begin",
        start_line=1,
        timeout_seconds=1.0,
        poll_seconds=0.1,
        sleep=sleep,
    )

    assert event["presentation_generation"] == 12
    assert event["trace_line"] == 2
    assert sleeps == [0.1]


def test_resolve_trace_path_auto_selects_newest_candidate(tmp_path):
    old = tmp_path / "old-command-overlay-trace.jsonl"
    new = tmp_path / "new-command-overlay-trace.jsonl"
    old.write_text("", encoding="utf-8")
    new.write_text("", encoding="utf-8")

    assert resolve_trace_path("auto", candidates=[old, new]) == new


def test_build_cropped_filmstrips_from_manifest_emits_overlay_and_corner_strips(tmp_path):
    from PIL import Image

    frames = []
    for idx in range(4):
        path = tmp_path / f"frame-{idx}.png"
        Image.new("RGB", (800, 500), (20, 20, 20)).save(path)
        frames.append({"path": path.name})
    (tmp_path / "manifest.json").write_text(json.dumps({"frames": frames}), encoding="utf-8")

    strips = build_cropped_filmstrips_from_manifest(
        output_dir=tmp_path,
        trace_events=[
            {
                "event": "overlay.enforce_window_order",
                "comp_shell_config": "cx=400,cy=300,w=500,h=7,mag=1.0",
                "comp_window_frame": "400x250",
            }
        ],
        max_frames=4,
        columns=2,
        overlay_thumb_width=300,
        corner_thumb_width=220,
        label_height=0,
    )

    assert set(strips) == {"full", "overlay", "top_left_corner"}
    for path in strips.values():
        assert path.exists()
    with Image.open(strips["overlay"]) as image:
        assert image.width == 2 * 300 + 3 * 8
    with Image.open(strips["top_left_corner"]) as image:
        assert image.width == 2 * 220 + 3 * 8
