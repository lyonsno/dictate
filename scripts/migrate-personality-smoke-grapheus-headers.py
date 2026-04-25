#!/usr/bin/env python3
"""Label legacy personality smoke Grapheus records with X-Spoke metadata."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

SMOKE_PATHWAY = "personality-skill-smoke"


@dataclass(frozen=True)
class MigrationResult:
    scanned: int
    changed: int
    path: Path


def _load_smoke_module() -> Any:
    script_path = Path(__file__).with_name("personality-skill-smoke.py")
    spec = importlib.util.spec_from_file_location("personality_skill_smoke", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _scenario_prompts() -> dict[str, str]:
    smoke = _load_smoke_module()
    return {scenario.prompt: scenario.id for scenario in smoke.DEFAULT_SCENARIOS}


def _last_user_message(entry: dict[str, Any]) -> str | None:
    request = entry.get("request")
    if not isinstance(request, dict):
        return None
    messages = request.get("messages")
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
    return None


def _summary_user_utterance(entry: dict[str, Any]) -> str | None:
    summary = entry.get("summary")
    if not isinstance(summary, dict):
        return None
    utterance = summary.get("user_utterance")
    return utterance if isinstance(utterance, str) else None


def _legacy_scenario_id(entry: dict[str, Any], prompts: dict[str, str]) -> str | None:
    if entry.get("spoke_metadata") is not None:
        return None
    utterance = _summary_user_utterance(entry)
    last_user = _last_user_message(entry)
    if last_user and last_user in prompts:
        if utterance and utterance != last_user:
            return None
        return prompts[last_user]
    return None


def migrate_entry(entry: dict[str, Any], prompts: dict[str, str] | None = None) -> bool:
    scenario_id = _legacy_scenario_id(entry, prompts or _scenario_prompts())
    if scenario_id is None:
        return False

    entry["spoke_metadata"] = {
        "pathway": SMOKE_PATHWAY,
        "utterance_id": scenario_id,
        "turn": "0",
        "smoke_harness": SMOKE_PATHWAY,
    }
    headers = entry.get("request_headers")
    if not isinstance(headers, dict):
        headers = {}
        entry["request_headers"] = headers
    headers["X-Spoke-Pathway"] = SMOKE_PATHWAY
    headers["X-Spoke-Utterance-ID"] = scenario_id
    headers["X-Spoke-Turn"] = "0"
    headers["X-Spoke-Smoke-Harness"] = SMOKE_PATHWAY
    return True


def migrate_log(path: Path, *, dry_run: bool = False) -> MigrationResult:
    prompts = _scenario_prompts()
    changed = 0
    scanned = 0
    output_lines: list[str] = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            output_lines.append(raw_line)
            continue
        scanned += 1
        entry = json.loads(raw_line)
        if migrate_entry(entry, prompts):
            changed += 1
        output_lines.append(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))

    if changed and not dry_run:
        path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    return MigrationResult(scanned=scanned, changed=changed, path=path)


def _default_log_path(log_dir: Path, log_date: str | None) -> Path:
    day = log_date or date.today().isoformat()
    return log_dir / f"grapheus-{day}.jsonl"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Add personality smoke X-Spoke metadata to legacy Grapheus JSONL entries.",
    )
    parser.add_argument("paths", nargs="*", type=Path, help="Grapheus JSONL files to migrate")
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path.home() / "dev" / "grapheus" / "logs",
        help="Default Grapheus log directory when no explicit path is supplied",
    )
    parser.add_argument(
        "--date",
        dest="log_date",
        help="Default Grapheus log date when no explicit path is supplied (YYYY-MM-DD)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    args = parser.parse_args(argv)

    paths = args.paths or [_default_log_path(args.log_dir, args.log_date)]
    total_changed = 0
    for path in paths:
        result = migrate_log(path, dry_run=args.dry_run)
        total_changed += result.changed
        action = "would update" if args.dry_run else "updated"
        print(f"{path}: {action} {result.changed} of {result.scanned} entries")
    return 0 if total_changed or args.dry_run else 0


if __name__ == "__main__":
    raise SystemExit(main())
