import json
from datetime import datetime, timezone

import spoke.retina_lasso_witness as witness
from spoke.retina_lasso_witness import (
    build_evidence_split,
    build_launch_target_command,
    build_retina_lasso_command,
    capture_count_for_window,
    collect_trace_events,
    default_fps_for_capture_profile,
    drive_hammer_toggles,
    drive_retarget_during_dismiss_pattern,
    write_witness_index,
)


def test_capture_count_for_window_rounds_up():
    assert capture_count_for_window(2.1, 10.0) == 21
    assert capture_count_for_window(0.01, 10.0) == 1


def test_capture_profile_defaults_separate_passive_and_stress_pressure():
    assert default_fps_for_capture_profile("low_perturbation") == 6.0
    assert default_fps_for_capture_profile("stress") == 15.0


def test_build_retina_lasso_command_prefers_global_capture_custody(tmp_path):
    command = build_retina_lasso_command(
        output_dir=tmp_path,
        count=3,
        interval_seconds=0.125,
        lane="warpstorm-pit-boss",
        diaulos="Warpstorm Pit Boss",
        source_app="Spoke",
        source_window="Command Overlay",
        trace_path=tmp_path / "trace.jsonl",
        capture_profile="low_perturbation",
        capture_command="/usr/local/bin/global-witness-capture",
    )

    assert command[0] == "/usr/local/bin/global-witness-capture"
    assert command[command.index("--output-dir") + 1] == str(tmp_path)
    assert command[command.index("--count") + 1] == "3"
    assert command[command.index("--interval") + 1] == "0.125000"
    assert command[command.index("--capture-profile") + 1] == "low-perturbation"
    assert command[command.index("--lane") + 1] == "warpstorm-pit-boss"
    assert command[command.index("--diaulos") + 1] == "Warpstorm Pit Boss"
    assert command[command.index("--source-app") + 1] == "Spoke"
    assert command[command.index("--source-window") + 1] == "Command Overlay"
    assert command[command.index("--trace-path") + 1] == str(tmp_path / "trace.jsonl")


def test_build_retina_lasso_command_uses_healthy_global_capture_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(witness.shutil, "which", lambda name: "/usr/local/bin/global-witness-capture")
    monkeypatch.setattr(witness, "_global_capture_command_is_healthy", lambda command: True)

    command = build_retina_lasso_command(
        output_dir=tmp_path,
        count=1,
        interval_seconds=1.0,
        lane="warpstorm-pit-boss",
        diaulos="Warpstorm Pit Boss",
        source_app="Spoke",
        source_window="Command Overlay",
    )

    assert command[0] == "/usr/local/bin/global-witness-capture"


def test_build_retina_lasso_command_skips_unhealthy_global_capture(tmp_path, monkeypatch):
    monkeypatch.setenv("UV_BIN", "/opt/homebrew/bin/uv")
    monkeypatch.setattr(witness.shutil, "which", lambda name: "/usr/local/bin/global-witness-capture")
    monkeypatch.setattr(witness, "_global_capture_command_is_healthy", lambda command: False)
    monkeypatch.setattr(witness.Path, "home", staticmethod(lambda: tmp_path))

    command = build_retina_lasso_command(
        output_dir=tmp_path,
        count=1,
        interval_seconds=1.0,
        lane="warpstorm-pit-boss",
        diaulos="Warpstorm Pit Boss",
        source_app="Spoke",
        source_window="Command Overlay",
    )

    assert command[:3] == ["/opt/homebrew/bin/uv", "run", "perceptasia-screen-capture"]


def test_build_retina_lasso_command_uses_absolute_uv_from_env(tmp_path, monkeypatch):
    monkeypatch.setattr(witness, "_default_global_capture_command", lambda: None)
    monkeypatch.setenv("UV_BIN", "/opt/homebrew/bin/uv")

    command = build_retina_lasso_command(
        output_dir=tmp_path,
        count=1,
        interval_seconds=1.0,
        lane="warpstorm-pit-boss",
        diaulos="Warpstorm Pit Boss",
        source_app="Spoke",
        source_window="Command Overlay",
    )

    assert command[:3] == ["/opt/homebrew/bin/uv", "run", "perceptasia-screen-capture"]


def test_build_retina_lasso_command_uses_common_uv_path_without_shell_path(tmp_path, monkeypatch):
    monkeypatch.setattr(witness, "_default_global_capture_command", lambda: None)
    monkeypatch.delenv("UV_BIN", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(witness.shutil, "which", lambda name: None)
    monkeypatch.setattr(witness.Path, "home", staticmethod(lambda: tmp_path))
    local_uv = tmp_path / ".local" / "bin" / "uv"
    local_uv.parent.mkdir(parents=True)
    local_uv.write_text("#!/bin/sh\n", encoding="utf-8")
    local_uv.chmod(0o755)

    command = build_retina_lasso_command(
        output_dir=tmp_path,
        count=1,
        interval_seconds=1.0,
        lane="warpstorm-pit-boss",
        diaulos="Warpstorm Pit Boss",
        source_app="Spoke",
        source_window="Command Overlay",
    )

    assert command[:3] == [str(local_uv), "run", "perceptasia-screen-capture"]


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


def test_build_evidence_split_keeps_witness_and_lifecycle_roles_separate():
    split = build_evidence_split(
        manifest_loaded=True,
        frame_count=4,
        trace_event_count=7,
        capture_profile="stress",
    )

    assert split["visual_witness"]["role"] == "perturbing_visual_stress_witness"
    assert split["visual_witness"]["can_prove_absence"] is False
    assert split["visual_witness"]["can_raise_candidate_bad_frame"] is True
    assert split["visual_witness"]["capture_profile"] == "stress"
    assert split["visual_witness"]["known_capture_artifact_signatures"][0]["signature"] == (
        "horizontal_tear_or_phase_split"
    )
    assert split["lifecycle_trace"]["role"] == "generation_lifecycle_receipts"
    assert split["lifecycle_trace"]["required_for_extraction_clearance"] is True
    assert split["classification_rule"]["witness_clean"] == "not_clearance"
    assert split["classification_rule"]["trace_unlawful_publication"] == "primitive_lifecycle_blocker"
    assert split["classification_rule"]["known_capture_artifact_without_trace_violation"] == (
        "not_a_primitive_blocker_by_itself"
    )


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
        capture_profile="low_perturbation",
    )

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "spoke.retina_lasso_trace_witness.v1"
    assert payload["frame_count"] == 2
    assert payload["trace_event_count"] == 1
    assert payload["trace_events"][0]["event"] == "overlay.show.begin"
    assert payload["evidence_split"]["visual_witness"]["frame_count"] == 2
    assert payload["capture_profile"] == "low_perturbation"
    assert payload["evidence_split"]["visual_witness"]["capture_profile"] == "low_perturbation"
    assert payload["evidence_split"]["lifecycle_trace"]["trace_event_count"] == 1
    assert payload["evidence_split"]["classification_rule"]["witness_bad_frame"] == (
        "candidate_violation_until_trace_correlated"
    )
