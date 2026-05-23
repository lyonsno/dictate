import json

from spoke.command_overlay_trace import (
    flush_command_overlay_trace,
    record_command_overlay_trace,
)


def test_command_overlay_trace_writes_jsonl_when_path_is_set(monkeypatch, tmp_path):
    path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SPOKE_COMMAND_OVERLAY_TRACE_PATH", str(path))

    record_command_overlay_trace("gesture.test", visible=True, ignored=None)
    flush_command_overlay_trace()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["event"] == "gesture.test"
    assert payload["visible"] is True
    assert "ignored" not in payload
    assert isinstance(payload["pid"], int)


def test_command_overlay_trace_is_noop_without_path(monkeypatch, tmp_path):
    monkeypatch.delenv("SPOKE_COMMAND_OVERLAY_TRACE_PATH", raising=False)

    record_command_overlay_trace("gesture.test", path=str(tmp_path / "unused.jsonl"))
    flush_command_overlay_trace()

    assert not (tmp_path / "unused.jsonl").exists()


def test_command_overlay_trace_does_not_write_on_caller_thread(monkeypatch, tmp_path):
    import spoke.command_overlay_trace as trace

    path = tmp_path / "trace.jsonl"
    writes = []

    monkeypatch.setenv("SPOKE_COMMAND_OVERLAY_TRACE_PATH", str(path))
    monkeypatch.setattr(
        trace,
        "_write_trace_payload",
        lambda path_text, payload: writes.append((path_text, payload, payload["thread"])),
    )

    record_command_overlay_trace("gesture.hot_path")

    assert writes == []
    flush_command_overlay_trace()
    assert writes
    assert writes[0][1]["event"] == "gesture.hot_path"
