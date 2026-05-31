"""Autonomous visual witness harness for the Perceptasia Throughglass graft."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

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

    print(index_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
