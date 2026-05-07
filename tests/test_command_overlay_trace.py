import json

from spoke.command_overlay_trace import (
    main,
    record_command_overlay_trace,
    summarize_command_overlay_trace,
)


def test_command_overlay_trace_writes_jsonl_when_path_is_set(monkeypatch, tmp_path):
    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SPOKE_COMMAND_OVERLAY_TRACE_PATH", str(path))

    record_command_overlay_trace("gesture.test", visible=True, ignored=None)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["event"] == "gesture.test"
    assert payload["visible"] is True
    assert "ignored" not in payload
    assert isinstance(payload["pid"], int)


def test_command_overlay_trace_is_noop_without_path(monkeypatch, tmp_path):
    monkeypatch.delenv("SPOKE_COMMAND_OVERLAY_TRACE_PATH", raising=False)

    record_command_overlay_trace("gesture.test", path=str(tmp_path / "unused.jsonl"))

    assert not (tmp_path / "unused.jsonl").exists()


def test_command_overlay_trace_summary_flags_gpu_cpu_fallback_and_alpha_zero(tmp_path):
    path = tmp_path / "trace.jsonl"
    events = [
        {
            "event": "overlay.show.end",
            "visible": True,
            "window_alpha": 0.0,
            "gpu_material_enabled": False,
        },
        {
            "event": "overlay.gpu_material.signal",
            "gpu_material_enabled": True,
            "gpu_material_brightness": 0.42,
        },
        {
            "event": "overlay.cpu_fill.rebuild.requested",
            "gpu_material_enabled": True,
            "width": 624.0,
            "height": 120.0,
        },
    ]
    path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
    )

    summary = summarize_command_overlay_trace(path)

    assert summary["event_count"] == 3
    assert summary["event_counts"]["overlay.show.end"] == 1
    assert summary["gpu_material_observed"] is True
    assert summary["cpu_fallback_under_gpu_material"] is True
    assert summary["visible_alpha_zero"] is True
    assert summary["ready_for_gpu_material_claim"] is False
    assert summary["cpu_fallback_events"][0]["event"] == "overlay.cpu_fill.rebuild.requested"
    assert summary["visible_alpha_zero_events"][0]["event"] == "overlay.show.end"


def test_command_overlay_trace_summary_accepts_clean_gpu_material_trace(tmp_path):
    path = tmp_path / "trace.jsonl"
    events = [
        {"event": "overlay.show.begin", "visible": False},
        {
            "event": "overlay.gpu_material.signal",
            "gpu_material_enabled": True,
            "gpu_material_opacity": 1.0,
        },
        {"event": "overlay.show.end", "visible": True, "window_alpha": 1.0},
    ]
    path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
    )

    summary = summarize_command_overlay_trace(path)

    assert summary["gpu_material_observed"] is True
    assert summary["cpu_fallback_under_gpu_material"] is False
    assert summary["visible_alpha_zero"] is False
    assert summary["ready_for_gpu_material_claim"] is True


def test_command_overlay_trace_cli_prints_summary_json(tmp_path, capsys):
    path = tmp_path / "trace.jsonl"
    path.write_text(
        json.dumps({"event": "overlay.gpu_material.signal", "gpu_material_enabled": True})
        + "\n",
        encoding="utf-8",
    )

    assert main(["summary", str(path)]) == 0

    printed = json.loads(capsys.readouterr().out)
    assert printed["gpu_material_observed"] is True
