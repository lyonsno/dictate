"""Opt-in trace breadcrumbs for assistant overlay gesture debugging."""

from __future__ import annotations

import atexit
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import threading

_TRACE_QUEUE: queue.Queue[tuple[str, dict] | None] = queue.Queue()
_TRACE_WRITER_STARTED = False
_TRACE_WRITER_LOCK = threading.Lock()


def _write_trace_payload(path_text: str, payload: dict) -> None:
    try:
        path = Path(path_text).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    except Exception:
        return


def _trace_writer_loop() -> None:
    while True:
        item = _TRACE_QUEUE.get()
        try:
            if item is None:
                return
            path_text, payload = item
            _write_trace_payload(path_text, payload)
        finally:
            _TRACE_QUEUE.task_done()


def _ensure_trace_writer_started() -> None:
    global _TRACE_WRITER_STARTED
    if _TRACE_WRITER_STARTED:
        return
    with _TRACE_WRITER_LOCK:
        if _TRACE_WRITER_STARTED:
            return
        thread = threading.Thread(
            target=_trace_writer_loop,
            name="SpokeCommandOverlayTraceWriter",
            daemon=True,
        )
        thread.start()
        _TRACE_WRITER_STARTED = True


def flush_command_overlay_trace() -> None:
    """Block until queued trace payloads have reached disk."""
    _TRACE_QUEUE.join()


def record_command_overlay_trace(event: str, **details) -> None:
    path_text = os.environ.get("SPOKE_COMMAND_OVERLAY_TRACE_PATH", "").strip()
    if not path_text:
        return
    payload = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "event": event,
        "pid": os.getpid(),
        "thread": threading.current_thread().name,
    }
    payload.update({key: value for key, value in details.items() if value is not None})
    _ensure_trace_writer_started()
    _TRACE_QUEUE.put((path_text, payload))


atexit.register(flush_command_overlay_trace)
