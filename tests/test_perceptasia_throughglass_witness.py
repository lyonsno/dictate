from __future__ import annotations

from pathlib import Path

from spoke import perceptasia_throughglass_witness as witness


def test_default_output_dir_is_throughglass_named(tmp_path, monkeypatch):
    monkeypatch.setattr(witness, "_timestamp_slug", lambda: "20260531T000000Z")

    assert witness.default_output_dir(tmp_path) == tmp_path / "throughglass-autowitness-20260531T000000Z"


def test_throughglass_witness_defaults_to_passive_capture(tmp_path, monkeypatch, capsys):
    calls = []

    def run_witness_window(**kwargs):
        calls.append(kwargs)
        index = Path(kwargs["output_dir"]) / "witness-index.json"
        index.parent.mkdir(parents=True)
        index.write_text(
            '{"throughglass_contract":{"passed":true,"content_verified":true}}\n',
            encoding="utf-8",
        )
        return index

    monkeypatch.setattr(witness, "_timestamp_slug", lambda: "20260531T010203Z")
    monkeypatch.setattr(witness, "run_witness_window", run_witness_window)

    assert witness.main(["--output-root", str(tmp_path), "--duration", "1.25"]) == 0

    assert calls[0]["output_dir"] == tmp_path / "throughglass-autowitness-20260531T010203Z"
    assert calls[0]["duration_seconds"] == 1.25
    assert calls[0]["capture_profile"] == "low_perturbation"
    assert calls[0]["lane"] == "perceptasia-throughglass-graft"
    assert calls[0]["diaulos"] == "Warpstorm Pit Boss"
    assert calls[0]["source_window"] == "Perceptasia Throughglass / Assistant Overlay"
    assert calls[0]["stimulus"] == {"mode": "passive-throughglass"}
    assert "witness-index.json" in capsys.readouterr().out


def test_throughglass_witness_launch_mode_uses_selected_target_contract(tmp_path, monkeypatch):
    calls = []

    def run_autonomous_hammer_witness(**kwargs):
        calls.append(kwargs)
        index = Path(kwargs["output_dir"]) / "witness-index.json"
        index.parent.mkdir(parents=True)
        index.write_text(
            '{"throughglass_contract":{"passed":true,"content_verified":true}}\n',
            encoding="utf-8",
        )
        return index

    monkeypatch.setattr(witness, "run_autonomous_hammer_witness", run_autonomous_hammer_witness)

    assert witness.main(["--launch", "--output-dir", str(tmp_path / "out"), "--duration", "2"]) == 0

    assert calls[0]["output_dir"] == tmp_path / "out"
    assert calls[0]["capture_profile"] == "stress"
    assert calls[0]["launch_target"] == "perceptasia_throughglass_graft"
    assert calls[0]["hammer_toggles"] == 0
    assert calls[0]["source_app"] == "Spoke"


def test_throughglass_witness_fails_when_capture_lacks_content_proof(tmp_path, monkeypatch):
    def run_witness_window(**kwargs):
        index = Path(kwargs["output_dir"]) / "witness-index.json"
        index.parent.mkdir(parents=True)
        index.write_text('{"frame_count":96}\n', encoding="utf-8")
        return index

    monkeypatch.setattr(witness, "_timestamp_slug", lambda: "20260531T010203Z")
    monkeypatch.setattr(witness, "run_witness_window", run_witness_window)

    assert witness.main(["--output-root", str(tmp_path), "--duration", "1.25"]) == 2
