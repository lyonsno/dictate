#!/usr/bin/env python3
"""Classify command-overlay presentation-generation trace receipts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any


VISIBLE_TEXT_STATES = {"visible"}
UNPRESENTED_BODY_STATES = {"slit", "materializing"}
REQUIRED_RECEIPT_FIELDS = (
    "presentation_generation",
    "presentation_config_generation",
    "presentation_ack_generation",
    "presentation_acknowledged",
)


@dataclass(frozen=True)
class AnalysisResult:
    checked_events: int
    violations: list[dict[str, Any]]

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_events": self.checked_events,
            "has_violations": self.has_violations,
            "violations": self.violations,
        }


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _visible_to_human(event: dict[str, Any]) -> bool:
    if _boolish(event.get("presentation_window_ordered")):
        return True
    if _boolish(event.get("presentation_window_visible")):
        alpha = event.get("presentation_window_alpha")
        try:
            return alpha is None or float(alpha) > 0.0
        except (TypeError, ValueError):
            return True
    return False


def _copy_receipts(event: dict[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = {
        "event": event.get("event"),
        "timestamp": event.get("timestamp"),
    }
    for key in (
        "presentation_generation",
        "presentation_requested_state",
        "presentation_publisher_state",
        "presentation_config_generation",
        "presentation_config_identity",
        "presentation_window_visible",
        "presentation_window_ordered",
        "presentation_window_alpha",
        "presentation_text_state",
        "presentation_body_state",
        "presentation_mask_state",
        "presentation_ack_generation",
        "presentation_acknowledged",
    ):
        if key in event:
            copied[key] = event[key]
    return copied


def _violation(reason: str, index: int, event: dict[str, Any]) -> dict[str, Any]:
    payload = {"reason": reason, "index": index}
    payload.update(_copy_receipts(event))
    return payload


def analyze_events(events: list[dict[str, Any]]) -> AnalysisResult:
    checked = 0
    violations: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if not any(key.startswith("presentation_") for key in event):
            continue
        checked += 1
        if not _visible_to_human(event):
            continue

        missing = [field for field in REQUIRED_RECEIPT_FIELDS if field not in event]
        if missing:
            violation = _violation(
                "visible_frame_missing_generation_receipts",
                index,
                event,
            )
            violation["missing_fields"] = missing
            violations.append(violation)
            continue

        text_state = str(event.get("presentation_text_state", "unknown"))
        body_state = str(event.get("presentation_body_state", "unknown"))
        acked = _boolish(event.get("presentation_acknowledged"))
        generation = event.get("presentation_generation")
        config_generation = event.get("presentation_config_generation")
        ack_generation = event.get("presentation_ack_generation")
        current_generation_acked = (
            acked
            and generation is not None
            and config_generation == generation
            and ack_generation == generation
        )

        if (
            text_state in VISIBLE_TEXT_STATES
            and body_state in UNPRESENTED_BODY_STATES
            and not current_generation_acked
        ):
            violations.append(
                _violation(
                    "visible_text_without_presented_body_generation",
                    index,
                    event,
                )
            )
            continue

        if body_state not in {"absent", "slit"} and not current_generation_acked:
            violations.append(
                _violation(
                    "visible_body_without_current_generation_ack",
                    index,
                    event,
                )
            )

    return AnalysisResult(checked_events=checked, violations=violations)


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if isinstance(payload, dict):
                events.append(payload)
    return events


def _format_text(result: AnalysisResult) -> str:
    lines = [
        f"checked_events: {result.checked_events}",
        f"has_violations: {str(result.has_violations).lower()}",
    ]
    for violation in result.violations:
        lines.append(
            "violation: "
            f"{violation['reason']} "
            f"index={violation['index']} "
            f"generation={violation.get('presentation_generation')} "
            f"config={violation.get('presentation_config_generation')} "
            f"ack={violation.get('presentation_ack_generation')} "
            f"text={violation.get('presentation_text_state')} "
            f"body={violation.get('presentation_body_state')}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Classify command overlay presentation-generation trace receipts. "
            "If TRACE_PATH is omitted, SPOKE_COMMAND_OVERLAY_TRACE_PATH is used."
        )
    )
    parser.add_argument("trace_path", nargs="?", help="JSONL command overlay trace path")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    trace_path_text = args.trace_path or os.environ.get("SPOKE_COMMAND_OVERLAY_TRACE_PATH")
    if not trace_path_text:
        raise SystemExit("trace path required or SPOKE_COMMAND_OVERLAY_TRACE_PATH must be set")

    result = analyze_events(load_events(Path(trace_path_text).expanduser()))
    if args.json:
        print(json.dumps(result.to_dict(), sort_keys=True))
    else:
        print(_format_text(result))
    return 1 if result.has_violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
