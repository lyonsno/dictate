"""Opt-in trace breadcrumbs and summaries for assistant overlay proof runs."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import threading
from collections.abc import Iterable


_CPU_FALLBACK_PREFIXES = (
    "overlay.cpu_",
)


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) != 0.0
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off", "none"}
    return bool(value)


def _float_or_none(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    try:
        path = Path(path_text).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    except Exception:
        return


def load_command_overlay_trace(path: str | os.PathLike[str]) -> list[dict]:
    events: list[dict] = []
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
    return events


def summarize_command_overlay_events(
    events: Iterable[dict],
    *,
    source_path: str | None = None,
) -> dict:
    event_list = [event for event in events if isinstance(event, dict)]
    event_counts: dict[str, int] = {}
    cpu_fallback_events: list[dict] = []
    visible_alpha_zero_events: list[dict] = []
    gpu_material_observed = False
    gpu_material_active = False
    cpu_fallback_under_gpu_material = False
    material_signal_count = 0
    lifecycle_event_count = 0

    for payload in event_list:
        event_name = str(payload.get("event", ""))
        event_counts[event_name] = event_counts.get(event_name, 0) + 1

        if event_name.startswith("overlay.gpu_material"):
            gpu_material_observed = True
            material_signal_count += 1
        if "gpu_material_enabled" in payload:
            enabled = _truthy(payload.get("gpu_material_enabled"))
            gpu_material_observed = gpu_material_observed or enabled
            gpu_material_active = enabled

        if event_name.startswith("overlay.show") or event_name.startswith(
            "overlay.cancel_dismiss"
        ):
            lifecycle_event_count += 1

        if (
            _truthy(payload.get("visible"))
            and (alpha := _float_or_none(payload.get("window_alpha"))) is not None
            and alpha <= 0.001
        ):
            visible_alpha_zero_events.append(dict(payload))

        is_cpu_fallback = _truthy(payload.get("cpu_fallback")) or any(
            event_name.startswith(prefix) for prefix in _CPU_FALLBACK_PREFIXES
        )
        if is_cpu_fallback:
            cpu_fallback_events.append(dict(payload))
            if _truthy(payload.get("gpu_material_enabled")) or gpu_material_active:
                cpu_fallback_under_gpu_material = True

    visible_alpha_zero = bool(visible_alpha_zero_events)
    return {
        "source_path": source_path,
        "event_count": len(event_list),
        "event_counts": event_counts,
        "gpu_material_observed": gpu_material_observed,
        "cpu_fallback_under_gpu_material": cpu_fallback_under_gpu_material,
        "visible_alpha_zero": visible_alpha_zero,
        "ready_for_gpu_material_claim": (
            gpu_material_observed
            and not cpu_fallback_under_gpu_material
            and not visible_alpha_zero
        ),
        "cpu_fallback_event_count": len(cpu_fallback_events),
        "cpu_fallback_events": cpu_fallback_events,
        "visible_alpha_zero_event_count": len(visible_alpha_zero_events),
        "visible_alpha_zero_events": visible_alpha_zero_events,
        "material_signal_event_count": material_signal_count,
        "lifecycle_event_count": lifecycle_event_count,
    }


def summarize_command_overlay_trace(path: str | os.PathLike[str]) -> dict:
    trace_path = Path(path).expanduser()
    return summarize_command_overlay_events(
        load_command_overlay_trace(trace_path),
        source_path=str(trace_path),
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize opt-in assistant overlay trace JSONL files."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    summary = subparsers.add_parser("summary", help="print a machine-readable trace verdict")
    summary.add_argument("path", help="path to SPOKE_COMMAND_OVERLAY_TRACE_PATH JSONL output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "summary":
        print(json.dumps(summarize_command_overlay_trace(args.path), sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
