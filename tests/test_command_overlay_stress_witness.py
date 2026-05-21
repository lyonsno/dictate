import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "command-overlay-stress-witness.py"


def _load_witness_module():
    spec = importlib.util.spec_from_file_location("command_overlay_stress_witness", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _trace_event(**overrides):
    event = {
        "event": "overlay.visual_ready.hard_deadline",
        "presentation_generation": 7,
        "presentation_requested_state": "opening",
        "presentation_publisher_state": "opening",
        "presentation_config_generation": 6,
        "presentation_config_identity": "stale-body-config",
        "presentation_window_visible": True,
        "presentation_window_ordered": True,
        "presentation_window_alpha": 1.0,
        "presentation_text_state": "visible",
        "presentation_body_state": "materializing",
        "presentation_mask_state": "clear",
        "presentation_ack_generation": 6,
        "presentation_acknowledged": False,
    }
    event.update(overrides)
    return event


def test_visible_text_body_split_without_current_ack_is_machine_classified():
    witness = _load_witness_module()

    result = witness.analyze_events([_trace_event()])

    assert result.has_violations is True
    assert result.violations[0]["reason"] == "visible_text_without_presented_body_generation"
    assert result.violations[0]["presentation_generation"] == 7
    assert result.violations[0]["presentation_config_generation"] == 6
    assert result.violations[0]["presentation_ack_generation"] == 6


def test_lawful_current_generation_receipts_pass():
    witness = _load_witness_module()

    result = witness.analyze_events(
        [
            _trace_event(
                event="overlay.visual_ready.push",
                presentation_config_generation=7,
                presentation_ack_generation=7,
                presentation_acknowledged=True,
                presentation_body_state="body_ready",
            )
        ]
    )

    assert result.has_violations is False
    assert result.checked_events == 1


def test_visible_trace_without_generation_receipts_is_not_eyeball_clean():
    witness = _load_witness_module()
    event = _trace_event()
    for key in (
        "presentation_generation",
        "presentation_config_generation",
        "presentation_ack_generation",
        "presentation_acknowledged",
    ):
        event.pop(key)

    result = witness.analyze_events([event])

    assert result.has_violations is True
    assert result.violations[0]["reason"] == "visible_frame_missing_generation_receipts"


def test_cli_exits_nonzero_for_unlawful_trace(tmp_path):
    trace_path = tmp_path / "command-overlay-trace.jsonl"
    trace_path.write_text(json.dumps(_trace_event()) + "\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(trace_path), "--json"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["has_violations"] is True
    assert payload["violations"][0]["reason"] == "visible_text_without_presented_body_generation"
