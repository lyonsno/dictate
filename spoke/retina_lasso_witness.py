"""Trace-aligned Retina Lasso smoke witness for visible Spoke UI states."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PERCEPTASIA_ROOT = Path("/private/tmp/perceptasia-codex-screen-slice-smoke-loop-0521")
DEFAULT_LANE = "warpstorm-pit-boss"
DEFAULT_DIAULOS = "Warpstorm Pit Boss"
DEFAULT_SOURCE_APP = "Spoke"
DEFAULT_SOURCE_WINDOW = "Command Overlay"
INDEX_NAME = "witness-index.json"
SPACEBAR_KEYCODE = 49
RETURN_KEYCODE = 36
SUPPORTED_CAPTURE_PROFILES = {"low_perturbation", "stress"}
DEFAULT_PASSIVE_CAPTURE_PROFILE = "low_perturbation"
DEFAULT_STRESS_CAPTURE_PROFILE = "stress"
CAPTURE_PROFILE_FPS = {
    "low_perturbation": 6.0,
    "stress": 15.0,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_trace_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_instant(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def capture_count_for_window(duration_seconds: float, fps: float) -> int:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if fps <= 0:
        raise ValueError("fps must be positive")
    return max(1, int(math.ceil(duration_seconds * fps)))


def capture_interval_for_fps(fps: float) -> float:
    if fps <= 0:
        raise ValueError("fps must be positive")
    return 1.0 / fps


def _capture_profile_from_cli(value: str) -> str:
    return value.replace("-", "_")


def default_fps_for_capture_profile(capture_profile: str) -> float:
    if capture_profile not in SUPPORTED_CAPTURE_PROFILES:
        raise ValueError(f"unsupported capture profile: {capture_profile}")
    return CAPTURE_PROFILE_FPS[capture_profile]


def collect_trace_events(
    trace_path: str | Path,
    *,
    started_at: datetime,
    ended_at: datetime,
    interesting_events: set[str] | None = None,
) -> list[dict[str, Any]]:
    path = Path(trace_path).expanduser()
    if not path.exists():
        return []
    start = started_at.astimezone(timezone.utc)
    end = ended_at.astimezone(timezone.utc)
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            event = json.loads(line)
            event_time = _parse_trace_timestamp(str(event["timestamp"]))
        except Exception:
            continue
        if event_time < start or event_time > end:
            continue
        event_name = str(event.get("event", ""))
        if interesting_events is not None and event_name not in interesting_events:
            continue
        event = dict(event)
        event["trace_line"] = line_number
        events.append(event)
    return events


def build_retina_lasso_command(
    *,
    output_dir: str | Path,
    count: int,
    interval_seconds: float,
    lane: str,
    diaulos: str,
    source_app: str,
    source_window: str,
) -> list[str]:
    return [
        "uv",
        "run",
        "perceptasia-screen-capture",
        "--output-dir",
        str(Path(output_dir).expanduser()),
        "--count",
        str(count),
        "--interval",
        f"{interval_seconds:.6f}",
        "--lane",
        lane,
        "--diaulos",
        diaulos,
        "--source-app",
        source_app,
        "--source-window",
        source_window,
    ]


def build_launch_target_command(repo_root: str | Path, target_id: str) -> list[str]:
    return [str(Path(repo_root).expanduser() / "scripts" / "launch-target.sh"), target_id]


def post_key_event(keycode: int, is_down: bool) -> None:
    from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap

    event = CGEventCreateKeyboardEvent(None, int(keycode), bool(is_down))
    CGEventPost(kCGHIDEventTap, event)


def post_space_enter_toggle_chord(*, key_pause_seconds: float = 0.035) -> None:
    """Synthesize the same space-first Enter chord the operator uses."""
    post_key_event(SPACEBAR_KEYCODE, True)
    time.sleep(key_pause_seconds)
    post_key_event(RETURN_KEYCODE, True)
    time.sleep(key_pause_seconds)
    post_key_event(RETURN_KEYCODE, False)
    time.sleep(key_pause_seconds)
    post_key_event(SPACEBAR_KEYCODE, False)


def drive_hammer_toggles(
    *,
    count: int,
    interval_seconds: float,
    key_pause_seconds: float = 0.035,
    toggle_chord: Callable[..., None] = post_space_enter_toggle_chord,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    if count < 0:
        raise ValueError("count must be non-negative")
    if interval_seconds < 0:
        raise ValueError("interval_seconds must be non-negative")
    for index in range(count):
        toggle_chord(key_pause_seconds=key_pause_seconds)
        if index < count - 1:
            sleep(interval_seconds)


def drive_retarget_during_dismiss_pattern(
    *,
    repeats: int,
    open_dwell_seconds: float,
    dismiss_retarget_delay_seconds: float,
    reopen_dwell_seconds: float,
    cycle_pause_seconds: float = 0.2,
    key_pause_seconds: float = 0.035,
    toggle_chord: Callable[..., None] = post_space_enter_toggle_chord,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    if repeats < 0:
        raise ValueError("repeats must be non-negative")
    for index in range(repeats):
        toggle_chord(key_pause_seconds=key_pause_seconds)
        sleep(open_dwell_seconds)
        toggle_chord(key_pause_seconds=key_pause_seconds)
        sleep(dismiss_retarget_delay_seconds)
        toggle_chord(key_pause_seconds=key_pause_seconds)
        sleep(reopen_dwell_seconds)
        toggle_chord(key_pause_seconds=key_pause_seconds)
        if index < repeats - 1:
            sleep(cycle_pause_seconds)


def build_evidence_split(
    *,
    manifest_loaded: bool,
    frame_count: int,
    trace_event_count: int,
    capture_profile: str,
) -> dict[str, Any]:
    """Describe what the witness can and cannot prove."""
    if capture_profile not in SUPPORTED_CAPTURE_PROFILES:
        raise ValueError(f"unsupported capture profile: {capture_profile}")
    return {
        "schema": "spoke.retina_lasso_evidence_split.v1",
        "visual_witness": {
            "role": "perturbing_visual_stress_witness",
            "manifest_loaded": manifest_loaded,
            "frame_count": frame_count,
            "capture_profile": capture_profile,
            "can_prove_absence": False,
            "can_raise_candidate_bad_frame": True,
            "known_perturbations": [
                "WindowServer/SCK capture pressure",
                "GPU pressure",
                "frame-cadence sampling gaps",
                "capture-path visual artifacts",
            ],
            "known_capture_artifact_signatures": [
                {
                    "signature": "horizontal_tear_or_phase_split",
                    "description": (
                        "A horizontal or banded discontinuity where one screen slice appears "
                        "one display phase older than another."
                    ),
                    "classification_without_trace": "witness_contamination_candidate",
                },
                {
                    "signature": "stale_slice_or_partial_frame_composite",
                    "description": (
                        "A still frame that appears composited from two different capture instants "
                        "while the live UI later lands in a lawful state."
                    ),
                    "classification_without_trace": "witness_contamination_candidate",
                },
            ],
        },
        "lifecycle_trace": {
            "role": "generation_lifecycle_receipts",
            "trace_event_count": trace_event_count,
            "required_for_extraction_clearance": True,
            "can_adjudicate_publication_law": True,
        },
        "classification_rule": {
            "witness_clean": "not_clearance",
            "witness_bad_frame": "candidate_violation_until_trace_correlated",
            "trace_unlawful_publication": "primitive_lifecycle_blocker",
            "trace_lawful_with_visual_artifact": "witness_reliability_or_capture_artifact",
            "known_capture_artifact_without_trace_violation": "not_a_primitive_blocker_by_itself",
        },
    }


def write_witness_index(
    *,
    output_dir: str | Path,
    trace_path: str | Path,
    started_at: datetime,
    ended_at: datetime,
    command: Sequence[str],
    trace_events: list[dict[str, Any]],
    manifest_name: str = "manifest.json",
    stimulus: dict[str, Any] | None = None,
    capture_profile: str = DEFAULT_PASSIVE_CAPTURE_PROFILE,
) -> Path:
    output = Path(output_dir).expanduser()
    manifest_path = output / manifest_name
    manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_loaded = manifest is not None
    frame_count = len((manifest or {}).get("frames", []))
    trace_event_count = len(trace_events)
    payload = {
        "schema": "spoke.retina_lasso_trace_witness.v1",
        "started_at": _format_instant(started_at),
        "ended_at": _format_instant(ended_at),
        "trace_path": str(Path(trace_path).expanduser()),
        "retina_lasso_manifest": str(manifest_path),
        "retina_lasso_manifest_loaded": manifest_loaded,
        "frame_count": frame_count,
        "trace_event_count": trace_event_count,
        "trace_events": trace_events,
        "evidence_split": build_evidence_split(
            manifest_loaded=manifest_loaded,
            frame_count=frame_count,
            trace_event_count=trace_event_count,
            capture_profile=capture_profile,
        ),
        "command": list(command),
        "stimulus": stimulus or {},
        "capture_profile": capture_profile,
        "uncertainty": [
            "Retina Lasso stills are visual evidence, not operator approval.",
            "Retina Lasso stills are perturbing stress evidence, not an absence oracle.",
            "Known Retina Lasso capture artifacts include horizontal tear/phase split and stale-slice composites.",
            "Still-frame cadence can miss a single display-refresh flash; use trace events to narrow the gap.",
            "Trace alignment is wall-clock based and does not prove exact compositor frame identity.",
        ],
    }
    index_path = output / INDEX_NAME
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return index_path


def run_autonomous_hammer_witness(
    *,
    trace_path: str | Path,
    output_dir: str | Path,
    repo_root: str | Path,
    perceptasia_root: str | Path = DEFAULT_PERCEPTASIA_ROOT,
    duration_seconds: float = 8.0,
    fps: float | None = None,
    capture_profile: str = DEFAULT_STRESS_CAPTURE_PROFILE,
    hammer_toggles: int = 0,
    toggle_interval_seconds: float = 0.18,
    pre_hammer_delay_seconds: float = 0.35,
    retarget_during_dismiss_repeats: int = 0,
    open_dwell_seconds: float = 0.75,
    dismiss_retarget_delay_seconds: float = 0.08,
    reopen_dwell_seconds: float = 0.75,
    cycle_pause_seconds: float = 0.2,
    lane: str = DEFAULT_LANE,
    diaulos: str = DEFAULT_DIAULOS,
    source_app: str = DEFAULT_SOURCE_APP,
    source_window: str = DEFAULT_SOURCE_WINDOW,
    launch_target: str | None = None,
    launch_wait_seconds: float = 3.0,
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
    popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    now: Callable[[], datetime] = _utc_now,
    sleep: Callable[[float], None] = time.sleep,
    hammer_driver: Callable[..., None] = drive_hammer_toggles,
    retarget_driver: Callable[..., None] = drive_retarget_during_dismiss_pattern,
) -> Path:
    if fps is None:
        fps = default_fps_for_capture_profile(capture_profile)
    if launch_target:
        runner(build_launch_target_command(repo_root, launch_target), check=True)
        sleep(launch_wait_seconds)

    count = capture_count_for_window(duration_seconds, fps)
    interval = capture_interval_for_fps(fps)
    command = build_retina_lasso_command(
        output_dir=output_dir,
        count=count,
        interval_seconds=interval,
        lane=lane,
        diaulos=diaulos,
        source_app=source_app,
        source_window=source_window,
    )
    started_at = now()
    capture = popen(command, cwd=Path(perceptasia_root).expanduser())
    try:
        sleep(pre_hammer_delay_seconds)
        if retarget_during_dismiss_repeats:
            retarget_driver(
                repeats=retarget_during_dismiss_repeats,
                open_dwell_seconds=open_dwell_seconds,
                dismiss_retarget_delay_seconds=dismiss_retarget_delay_seconds,
                reopen_dwell_seconds=reopen_dwell_seconds,
                cycle_pause_seconds=cycle_pause_seconds,
            )
            stimulus = {
                "mode": "retarget-during-dismiss",
                "repeats": retarget_during_dismiss_repeats,
                "open_dwell_seconds": open_dwell_seconds,
                "dismiss_retarget_delay_seconds": dismiss_retarget_delay_seconds,
                "reopen_dwell_seconds": reopen_dwell_seconds,
                "cycle_pause_seconds": cycle_pause_seconds,
            }
        else:
            hammer_driver(
                count=hammer_toggles,
                interval_seconds=toggle_interval_seconds,
            )
            stimulus = {
                "mode": "hammer",
                "toggle_count": hammer_toggles,
                "toggle_interval_seconds": toggle_interval_seconds,
            }
        return_code = capture.wait()
    except BaseException:
        capture.terminate()
        raise
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command)
    ended_at = now()
    trace_events = collect_trace_events(trace_path, started_at=started_at, ended_at=ended_at)
    return write_witness_index(
        output_dir=output_dir,
        trace_path=trace_path,
        started_at=started_at,
        ended_at=ended_at,
        command=command,
        trace_events=trace_events,
        stimulus=stimulus,
        capture_profile=capture_profile,
    )


def run_witness_window(
    *,
    trace_path: str | Path,
    output_dir: str | Path,
    perceptasia_root: str | Path = DEFAULT_PERCEPTASIA_ROOT,
    duration_seconds: float = 8.0,
    fps: float | None = None,
    capture_profile: str = DEFAULT_PASSIVE_CAPTURE_PROFILE,
    lane: str = DEFAULT_LANE,
    diaulos: str = DEFAULT_DIAULOS,
    source_app: str = DEFAULT_SOURCE_APP,
    source_window: str = DEFAULT_SOURCE_WINDOW,
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
    now: Callable[[], datetime] = _utc_now,
) -> Path:
    if fps is None:
        fps = default_fps_for_capture_profile(capture_profile)
    count = capture_count_for_window(duration_seconds, fps)
    interval = capture_interval_for_fps(fps)
    command = build_retina_lasso_command(
        output_dir=output_dir,
        count=count,
        interval_seconds=interval,
        lane=lane,
        diaulos=diaulos,
        source_app=source_app,
        source_window=source_window,
    )
    started_at = now()
    runner(command, cwd=Path(perceptasia_root).expanduser(), check=True)
    ended_at = now()
    trace_events = collect_trace_events(trace_path, started_at=started_at, ended_at=ended_at)
    return write_witness_index(
        output_dir=output_dir,
        trace_path=trace_path,
        started_at=started_at,
        ended_at=ended_at,
        command=command,
        trace_events=trace_events,
        capture_profile=capture_profile,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a Retina Lasso capture window and index it against a Spoke trace."
    )
    parser.add_argument("--trace", required=True, help="Command overlay JSONL trace to align with captures.")
    parser.add_argument("--output-dir", required=True, help="Directory for Retina Lasso frames and witness index.")
    parser.add_argument("--perceptasia-root", default=str(DEFAULT_PERCEPTASIA_ROOT))
    parser.add_argument("--duration", type=float, default=8.0, help="Capture window length in seconds.")
    parser.add_argument(
        "--fps",
        type=float,
        help=(
            "Requested still capture cadence. Defaults to the selected capture profile "
            "(6fps low-perturbation, 15fps stress)."
        ),
    )
    parser.add_argument(
        "--capture-profile",
        choices=("low-perturbation", "stress"),
        default=None,
        help=(
            "Witness pressure profile. Passive/manual windows default to low-perturbation; "
            "hammer or launch-driven windows default to stress."
        ),
    )
    parser.add_argument("--lane", default=DEFAULT_LANE)
    parser.add_argument("--diaulos", default=DEFAULT_DIAULOS)
    parser.add_argument("--source-app", default=DEFAULT_SOURCE_APP)
    parser.add_argument("--source-window", default=DEFAULT_SOURCE_WINDOW)
    parser.add_argument(
        "--hammer-toggles",
        type=int,
        default=0,
        help="If greater than zero, start capture and synthesize this many Spoke toggle chords.",
    )
    parser.add_argument(
        "--toggle-interval",
        type=float,
        default=0.18,
        help="Seconds between synthesized toggle chords in hammer mode.",
    )
    parser.add_argument(
        "--pre-hammer-delay",
        type=float,
        default=0.35,
        help="Seconds after capture starts before hammer-mode input begins.",
    )
    parser.add_argument(
        "--retarget-during-dismiss-repeats",
        type=int,
        default=0,
        help="Run a deterministic open/dismiss/reopen-during-dismiss pattern this many times.",
    )
    parser.add_argument(
        "--open-dwell",
        type=float,
        default=0.75,
        help="Seconds to hold the opened state before dismissing in retarget-during-dismiss mode.",
    )
    parser.add_argument(
        "--dismiss-retarget-delay",
        type=float,
        default=0.08,
        help="Seconds after dismiss begins before sending the reopen chord in retarget-during-dismiss mode.",
    )
    parser.add_argument(
        "--reopen-dwell",
        type=float,
        default=0.75,
        help="Seconds to hold the reopened state before final dismiss in retarget-during-dismiss mode.",
    )
    parser.add_argument(
        "--cycle-pause",
        type=float,
        default=0.2,
        help="Seconds between retarget-during-dismiss cycles.",
    )
    parser.add_argument(
        "--launch-target",
        help=(
            "Optional explicit Spoke launcher target to start before capture. "
            "This uses scripts/launch-target.sh and may replace the current live Spoke process."
        ),
    )
    parser.add_argument("--launch-wait", type=float, default=3.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    stimulus_mode = bool(args.hammer_toggles or args.retarget_during_dismiss_repeats or args.launch_target)
    capture_profile = _capture_profile_from_cli(
        args.capture_profile
        or (DEFAULT_STRESS_CAPTURE_PROFILE if stimulus_mode else DEFAULT_PASSIVE_CAPTURE_PROFILE)
    )
    if stimulus_mode:
        index_path = run_autonomous_hammer_witness(
            trace_path=args.trace,
            output_dir=args.output_dir,
            repo_root=Path(__file__).resolve().parents[1],
            perceptasia_root=args.perceptasia_root,
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
            launch_target=args.launch_target,
            launch_wait_seconds=args.launch_wait,
        )
    else:
        index_path = run_witness_window(
            trace_path=args.trace,
            output_dir=args.output_dir,
            perceptasia_root=args.perceptasia_root,
            duration_seconds=args.duration,
            fps=args.fps,
            capture_profile=capture_profile,
            lane=args.lane,
            diaulos=args.diaulos,
            source_app=args.source_app,
            source_window=args.source_window,
        )
    print(index_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
