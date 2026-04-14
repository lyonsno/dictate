import json
import types
import wave

import numpy as np

from spoke.wakeword_samples import WakewordSampleSpec, load_phrase_lines, write_sample_batch


def test_load_phrase_lines_ignores_blanks_and_comments(tmp_path):
    phrases = tmp_path / "phrases.txt"
    phrases.write_text("\n# comment\n\ntessera\n  alpha  \n")

    assert load_phrase_lines(phrases) == ["tessera", "alpha"]


def test_write_sample_batch_writes_wavs_and_manifest(tmp_path):
    calls = []

    def synthesize(spec: WakewordSampleSpec):
        calls.append((spec.text, spec.voice, spec.backend, spec.model))
        return types.SimpleNamespace(
            audio=np.array([[0.1], [-0.1], [0.05]], dtype=np.float32),
            sample_rate=16000,
        )

    specs = [
        WakewordSampleSpec(
            text="tessera",
            backend="local",
            model="local-model",
            voice="casual_female",
        ),
        WakewordSampleSpec(
            text="tessera",
            backend="cloud",
            model="gemini-2.5-flash-preview-tts",
            voice="Aoede",
        ),
    ]

    records = write_sample_batch(specs, tmp_path, synthesize)

    assert calls == [
        ("tessera", "casual_female", "local", "local-model"),
        ("tessera", "Aoede", "cloud", "gemini-2.5-flash-preview-tts"),
    ]
    assert len(records) == 2

    manifest_path = tmp_path / "manifest.jsonl"
    manifest_rows = [json.loads(line) for line in manifest_path.read_text().splitlines()]
    assert [row["voice"] for row in manifest_rows] == ["casual_female", "Aoede"]
    assert manifest_rows[0]["backend"] == "local"
    assert manifest_rows[1]["backend"] == "cloud"

    for row in manifest_rows:
        wav_path = tmp_path / row["relative_path"]
        assert wav_path.exists()
        with wave.open(str(wav_path), "rb") as wav_file:
            assert wav_file.getframerate() == 16000
            assert wav_file.getnchannels() == 1
            assert wav_file.getnframes() == 3
