#!/bin/bash
# Launch spoke dev build. Bind to a hotkey via macOS Shortcuts or Automator.
# Kills any existing instance first.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="${HOME}/Library/Logs"
LOG_FILE="${LOG_DIR}/spoke-dev-launch.log"

pkill -TERM -f "python.*spoke" 2>/dev/null
sleep 0.5
rm -f ~/Library/Logs/.spoke.lock
mkdir -p "$LOG_DIR"

{
  printf '\n=== %s ===\n' "$(date '+%Y-%m-%d %H:%M:%S')"
  printf 'Launching Spoke from %s\n' "$REPO_ROOT"
} >>"$LOG_FILE"

export REPO_ROOT LOG_FILE
unset SPOKE_PREVIEW_MODEL
unset SPOKE_TRANSCRIPTION_MODEL
unset SPOKE_WHISPER_MODEL

"$REPO_ROOT/.venv/bin/python" - <<'PY'
import os
import subprocess
import traceback
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
log_file = Path(os.environ["LOG_FILE"])
python_exe = repo_root / ".venv" / "bin" / "python"
child_env = os.environ.copy()
child_env.pop("SPOKE_PREVIEW_MODEL", None)
child_env.pop("SPOKE_TRANSCRIPTION_MODEL", None)
child_env.pop("SPOKE_WHISPER_MODEL", None)

with log_file.open("a", encoding="utf-8") as log:
    try:
        subprocess.Popen(
            [str(python_exe), "-m", "spoke"],
            cwd=repo_root,
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    except Exception:
        traceback.print_exc(file=log)
        log.flush()
        raise SystemExit(1)
PY
