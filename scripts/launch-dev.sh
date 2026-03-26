#!/bin/bash
# Launch spoke dev build. Bind to a hotkey via macOS Shortcuts or Automator.
# Kills any existing instance first.

pkill -TERM -f "python.*spoke" 2>/dev/null
sleep 0.5
rm -f ~/Library/Logs/.donttype.lock

nohup env -C /Users/noahlyons/dev/donttype \
  SPOKE_WHISPER_MODEL="${SPOKE_WHISPER_MODEL:-mlx-community/whisper-medium.en-mlx-8bit}" \
  /Users/noahlyons/dev/donttype/.venv/bin/python -m spoke \
  </dev/null >/dev/null 2>&1 &
