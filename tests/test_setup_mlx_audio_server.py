from __future__ import annotations

import subprocess
from pathlib import Path


def _make_fake_python(tmp_path: Path) -> tuple[Path, Path]:
    log_path = tmp_path / "python.log"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    fake_python = tmp_path / "python"
    fake_python.write_text(
        f"""#!/bin/bash
set -euo pipefail
LOG_PATH={str(log_path)!r}
STATE_DIR={str(state_dir)!r}
printf '%s\\n' "$*" >> "$LOG_PATH"

if [[ "$#" -ge 3 && "$1" == "-m" && "$2" == "pip" && "$3" == "--version" ]]; then
  [[ -f "$STATE_DIR/pip_ready" ]]
  exit $?
fi

if [[ "$#" -ge 3 && "$1" == "-m" && "$2" == "ensurepip" && "$3" == "--upgrade" ]]; then
  touch "$STATE_DIR/pip_ready"
  exit 0
fi

if [[ "$#" -ge 2 && "$1" == "-c" && "$2" == "import en_core_web_sm" ]]; then
  [[ -f "$STATE_DIR/model_ready" ]]
  exit $?
fi

if [[ "$#" -ge 3 && "$1" == "-m" && "$2" == "pip" && "$3" == "install" ]]; then
  touch "$STATE_DIR/model_ready"
  exit 0
fi

exit 0
"""
    )
    fake_python.chmod(0o755)
    return fake_python, log_path


def test_ensure_kokoro_runtime_deps_bootstraps_pip_and_model(tmp_path):
    fake_python, log_path = _make_fake_python(tmp_path)
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "setup-mlx-audio-server.sh"

    result = subprocess.run(
        [
            "bash",
            "-lc",
            f"source {script_path} && ensure_kokoro_runtime_deps {fake_python}",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert log_path.read_text().splitlines() == [
        "-m pip --version",
        "-m ensurepip --upgrade",
        "-c import en_core_web_sm",
        "-m pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl",
    ]


def test_ensure_kokoro_runtime_deps_skips_installs_when_ready(tmp_path):
    fake_python, log_path = _make_fake_python(tmp_path)
    state_dir = tmp_path / "state"
    (state_dir / "pip_ready").write_text("")
    (state_dir / "model_ready").write_text("")
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "setup-mlx-audio-server.sh"

    result = subprocess.run(
        [
            "bash",
            "-lc",
            f"source {script_path} && ensure_kokoro_runtime_deps {fake_python}",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert log_path.read_text().splitlines() == [
        "-m pip --version",
        "-c import en_core_web_sm",
    ]
