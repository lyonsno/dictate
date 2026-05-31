"""Autonomous visual witness harness for the Perceptasia Throughglass graft."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import re

from .retina_lasso_witness import (
    DEFAULT_PASSIVE_CAPTURE_PROFILE,
    DEFAULT_STRESS_CAPTURE_PROFILE,
    _capture_profile_from_cli,
    run_autonomous_hammer_witness,
    run_witness_window,
)

DEFAULT_TRACE_PATH = Path("/tmp/spoke-perceptasia-throughglass-graft-command-overlay-trace.jsonl")
DEFAULT_OUTPUT_ROOT = Path("/tmp/spoke-perceptasia-throughglass-autowitnesses")
DEFAULT_LAUNCH_TARGET = "perceptasia_throughglass_graft"
DEFAULT_LANE = "perceptasia-throughglass-graft"
DEFAULT_DIAULOS = "Warpstorm Pit Boss"
DEFAULT_SOURCE_APP = "Spoke"
DEFAULT_SOURCE_WINDOW = "Perceptasia Throughglass / Assistant Overlay"
DEFAULT_LOG_PATHS = (
    Path.home() / "Library" / "Logs" / "spoke-main-launch.log",
    Path.home() / "Library" / "Logs" / "spoke-launch-target.log",
)


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def default_output_dir(root: str | Path = DEFAULT_OUTPUT_ROOT) -> Path:
    return Path(root).expanduser() / f"throughglass-autowitness-{_timestamp_slug()}"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture a Retina Lasso witness for the Perceptasia Throughglass graft. "
            "By default this is passive and does not relaunch Spoke."
        )
    )
    parser.add_argument("--trace", default=str(DEFAULT_TRACE_PATH))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--output-dir", help="Exact output directory; overrides --output-root.")
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--fps", type=float)
    parser.add_argument(
        "--capture-profile",
        choices=("low-perturbation", "stress"),
        help="Defaults to low-perturbation unless launch/stimulus mode is enabled.",
    )
    parser.add_argument("--lane", default=DEFAULT_LANE)
    parser.add_argument("--diaulos", default=DEFAULT_DIAULOS)
    parser.add_argument("--source-app", default=DEFAULT_SOURCE_APP)
    parser.add_argument("--source-window", default=DEFAULT_SOURCE_WINDOW)
    parser.add_argument("--capture-command")
    parser.add_argument(
        "--allow-unproven",
        action="store_true",
        help="Write the witness index but return success even if Throughglass content proof is absent.",
    )
    parser.add_argument(
        "--log-path",
        action="append",
        dest="log_paths",
        help="Spoke runtime log to inspect for Throughglass content-proof receipts.",
    )
    parser.add_argument("--perceptasia-root", help=argparse.SUPPRESS)
    parser.add_argument("--watch-trace", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--watch-timeout", type=float, default=7200.0, help=argparse.SUPPRESS)
    parser.add_argument("--event-capture-duration", type=float, default=1.5, help=argparse.SUPPRESS)
    parser.add_argument("--watch-max-captures", type=int, default=96, help=argparse.SUPPRESS)
    parser.add_argument("--max-trigger-lag", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument("--open-ready-timeout", type=float, default=2.0, help=argparse.SUPPRESS)
    parser.add_argument("--open-ready-poll-interval", type=float, default=0.025, help=argparse.SUPPRESS)
    parser.add_argument(
        "--launch",
        action="store_true",
        help="Launch the Throughglass target before capture; this may replace the current live Spoke process.",
    )
    parser.add_argument("--launch-target", default=DEFAULT_LAUNCH_TARGET)
    parser.add_argument("--launch-wait", type=float, default=3.0)
    parser.add_argument("--hammer-toggles", type=int, default=0)
    parser.add_argument("--toggle-interval", type=float, default=0.18)
    parser.add_argument("--pre-hammer-delay", type=float, default=0.35)
    parser.add_argument("--retarget-during-dismiss-repeats", type=int, default=0)
    parser.add_argument("--open-dwell", type=float, default=0.75)
    parser.add_argument("--dismiss-retarget-delay", type=float, default=0.08)
    parser.add_argument("--reopen-dwell", type=float, default=0.75)
    parser.add_argument("--cycle-pause", type=float, default=0.2)
    return parser


def _load_index(index_path: Path) -> dict:
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_index(index_path: Path, payload: dict) -> None:
    index_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _runtime_log_contract(log_paths: list[Path]) -> dict:
    for path in log_paths:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        latest_setup = -1
        latest_url = None
        for index, line in enumerate(lines):
            match = re.search(r"Perceptasia Throughglass: setup begin url=([^\s]+)", line)
            if match:
                latest_setup = index
                latest_url = match.group(1)
        if latest_setup < 0:
            continue
        scoped = lines[latest_setup:]
        content_verified = any("Perceptasia Throughglass: content verified" in line for line in scoped)
        webview_loaded = any("Perceptasia Throughglass: WKWebView request loaded" in line for line in scoped)
        fallback_seen = any(
            marker in line
            for line in scoped
            for marker in (
                "WKWebView unavailable",
                "provider unavailable",
                "content verification failed",
            )
        )
        return {
            "latest_setup_seen": True,
            "log_path": str(path),
            "provider_url": latest_url,
            "webview_loaded": webview_loaded,
            "content_verified": content_verified,
            "fallback_seen": fallback_seen,
            "passed": bool(content_verified and webview_loaded and not fallback_seen),
        }
    return {
        "latest_setup_seen": False,
        "provider_url": None,
        "webview_loaded": False,
        "content_verified": False,
        "fallback_seen": False,
        "passed": False,
    }


def annotate_throughglass_contract(index_path: Path, *, log_paths: list[Path]) -> dict:
    payload = _load_index(index_path)
    existing = payload.get("throughglass_contract")
    if isinstance(existing, dict) and existing.get("passed") is True:
        return existing
    contract = _runtime_log_contract(log_paths)
    frame_count = payload.get("frame_count")
    if isinstance(frame_count, int):
        contract["frame_count"] = frame_count
    payload["throughglass_contract"] = contract
    _write_index(index_path, payload)
    return contract


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else default_output_dir(args.output_root)
    stimulus_mode = bool(args.launch or args.hammer_toggles or args.retarget_during_dismiss_repeats)
    capture_profile = _capture_profile_from_cli(
        args.capture_profile or (DEFAULT_STRESS_CAPTURE_PROFILE if stimulus_mode else DEFAULT_PASSIVE_CAPTURE_PROFILE)
    )

    if stimulus_mode:
        index_path = run_autonomous_hammer_witness(
            trace_path=args.trace,
            output_dir=output_dir,
            repo_root=Path(__file__).resolve().parents[1],
            duration_seconds=args.duration,
            fps=args.fps,
            capture_profile=capture_profile,
            hammer_toggles=args.hammer_toggles,
            toggle_interval_seconds=args.toggle_interval,
            pre_hammer_delay_seconds=args.pre_hammer_delay,
            retarget_during_dismiss_repeats=args.retarget_during_dismiss_repeats,
            open_dwell_seconds=args.open_dwell,
            dismiss_retarget_delay_seconds=args.dismiss_retarget_delay,
            reopen_dwell_seconds=args.reopen_dwell,
            cycle_pause_seconds=args.cycle_pause,
            lane=args.lane,
            diaulos=args.diaulos,
            source_app=args.source_app,
            source_window=args.source_window,
            capture_command=args.capture_command,
            launch_target=args.launch_target if args.launch else None,
            launch_wait_seconds=args.launch_wait,
        )
    else:
        index_path = run_witness_window(
            trace_path=args.trace,
            output_dir=output_dir,
            duration_seconds=args.duration,
            fps=args.fps,
            capture_profile=capture_profile,
            lane=args.lane,
            diaulos=args.diaulos,
            source_app=args.source_app,
            source_window=args.source_window,
            capture_command=args.capture_command,
            stimulus={"mode": "passive-throughglass"},
        )

    log_paths = [Path(path).expanduser() for path in args.log_paths] if args.log_paths else list(DEFAULT_LOG_PATHS)
    contract = annotate_throughglass_contract(Path(index_path), log_paths=log_paths)
    print(index_path)
    return 0 if args.allow_unproven or contract.get("passed") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
