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
FILMSTRIP_NAME = "filmstrip.png"
TRACE_AUTO = "auto"
SPACEBAR_KEYCODE = 49
RETURN_KEYCODE = 36


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


def resolve_trace_path(
    trace_path: str | Path | None,
    *,
    candidates: Sequence[Path] | None = None,
) -> Path:
    if trace_path is not None and str(trace_path) != TRACE_AUTO:
        return Path(trace_path).expanduser()
    paths = list(candidates) if candidates is not None else list(Path("/tmp").glob("*command-overlay-trace*.jsonl"))
    existing = [
        (path.stat().st_mtime_ns, index, path)
        for index, path in enumerate(paths)
        if path.exists()
    ]
    if not existing:
        raise FileNotFoundError("No command overlay trace files found for auto trace resolution")
    return max(existing)[2]


def trace_line_count(trace_path: str | Path) -> int:
    path = Path(trace_path).expanduser()
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def wait_for_trace_event(
    trace_path: str | Path,
    *,
    event_name: str,
    start_line: int = 0,
    timeout_seconds: float = 30.0,
    poll_seconds: float = 0.05,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    deadline = time.monotonic() + timeout_seconds
    path = Path(trace_path).expanduser()
    while True:
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            for line_number, line in enumerate(lines[start_line:], start=start_line + 1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event") == event_name:
                    event = dict(event)
                    event["trace_line"] = line_number
                    return event
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for {event_name} in {path}")
        sleep(poll_seconds)


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
    filmstrip_path: str | Path | None = None,
    filmstrip_paths: dict[str, Path] | None = None,
) -> Path:
    output = Path(output_dir).expanduser()
    manifest_path = output / manifest_name
    manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = {
        "schema": "spoke.retina_lasso_trace_witness.v1",
        "started_at": _format_instant(started_at),
        "ended_at": _format_instant(ended_at),
        "trace_path": str(Path(trace_path).expanduser()),
        "retina_lasso_manifest": str(manifest_path),
        "retina_lasso_manifest_loaded": manifest is not None,
        "frame_count": len((manifest or {}).get("frames", [])),
        "trace_event_count": len(trace_events),
        "trace_events": trace_events,
        "filmstrip": str(filmstrip_path) if filmstrip_path is not None else None,
        "filmstrips": {
            name: str(path)
            for name, path in (filmstrip_paths or {}).items()
        },
        "command": list(command),
        "stimulus": stimulus or {},
        "uncertainty": [
            "Retina Lasso stills are visual evidence, not operator approval.",
            "Still-frame cadence can miss a single display-refresh flash; use trace events to narrow the gap.",
            "Trace alignment is wall-clock based and does not prove exact compositor frame identity.",
        ],
    }
    index_path = output / INDEX_NAME
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return index_path


def _manifest_frame_entries(manifest: dict[str, Any]) -> list[Any]:
    for key in ("frames", "captures", "images"):
        value = manifest.get(key)
        if isinstance(value, list):
            return value
    return []


def _frame_path_from_manifest_entry(output_dir: Path, entry: Any) -> Path | None:
    raw: str | None = None
    if isinstance(entry, str):
        raw = entry
    elif isinstance(entry, dict):
        for key in ("path", "image_path", "file_path", "filename", "file", "image"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                raw = value
                break
    if raw is None:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = output_dir / path
    return path


def _sample_evenly(items: Sequence[Path], max_items: int) -> list[Path]:
    if max_items <= 0:
        raise ValueError("max_items must be positive")
    if len(items) <= max_items:
        return list(items)
    if max_items == 1:
        return [items[0]]
    last = len(items) - 1
    indexes = {
        int(round(i * last / float(max_items - 1)))
        for i in range(max_items)
    }
    return [items[i] for i in sorted(indexes)]


def _frame_paths_from_manifest(output_dir: Path, manifest_name: str) -> list[Path]:
    manifest_path = output_dir / manifest_name
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [
        path
        for entry in _manifest_frame_entries(manifest)
        if (path := _frame_path_from_manifest_entry(output_dir, entry)) is not None
        and path.exists()
    ]


def _parse_shell_config(value: Any) -> dict[str, float]:
    if not isinstance(value, str):
        return {}
    parsed: dict[str, float] = {}
    for part in value.split(","):
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        try:
            parsed[key.strip()] = float(raw)
        except ValueError:
            continue
    return parsed


def _clamp_crop_box(
    *,
    image_size: tuple[int, int],
    center_x: float,
    center_y: float,
    width: float,
    height: float,
) -> tuple[int, int, int, int]:
    image_w, image_h = image_size
    width = min(max(1.0, width), float(image_w))
    height = min(max(1.0, height), float(image_h))
    left = int(round(center_x - width / 2.0))
    top = int(round(center_y - height / 2.0))
    left = max(0, min(left, image_w - int(round(width))))
    top = max(0, min(top, image_h - int(round(height))))
    right = min(image_w, left + int(round(width)))
    bottom = min(image_h, top + int(round(height)))
    return (left, top, right, bottom)


def infer_overlay_crop_box(
    *,
    image_size: tuple[int, int],
    trace_events: Sequence[dict[str, Any]],
    padding_px: int = 180,
) -> tuple[int, int, int, int]:
    image_w, image_h = image_size
    shells = [
        shell
        for event in trace_events
        if (shell := _parse_shell_config(event.get("comp_shell_config")))
    ]
    if shells:
        shell = max(shells, key=lambda item: item.get("w", 0.0))
        center_x = shell.get("cx", image_w / 2.0)
        center_y = shell.get("cy", image_h * 0.63)
        width = max(shell.get("w", 0.0) + padding_px * 2, image_w * 0.60)
    else:
        center_x = image_w / 2.0
        center_y = image_h * 0.63
        width = image_w * 0.72
    height = max(image_h * 0.34, 420.0)
    return _clamp_crop_box(
        image_size=image_size,
        center_x=center_x,
        center_y=center_y,
        width=width,
        height=height,
    )


def _top_left_corner_crop_box(
    overlay_box: tuple[int, int, int, int],
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    left, top, right, bottom = overlay_box
    overlay_w = right - left
    overlay_h = bottom - top
    corner_w = min(max(360, int(round(overlay_w * 0.34))), overlay_w)
    corner_h = min(max(260, int(round(overlay_h * 0.52))), overlay_h)
    return _clamp_crop_box(
        image_size=image_size,
        center_x=left + corner_w / 2.0,
        center_y=top + corner_h / 2.0,
        width=corner_w,
        height=corner_h,
    )


def build_filmstrip_from_manifest(
    *,
    output_dir: str | Path,
    manifest_name: str = "manifest.json",
    output_name: str = FILMSTRIP_NAME,
    max_frames: int = 24,
    columns: int = 8,
    thumb_width: int = 360,
    gutter: int = 8,
    label_height: int = 22,
    crop_box: tuple[int, int, int, int] | None = None,
) -> Path | None:
    """Build a sampled visual filmstrip from Retina Lasso capture frames."""
    output = Path(output_dir).expanduser()
    frame_paths = _frame_paths_from_manifest(output, manifest_name)
    if not frame_paths:
        return None

    from PIL import Image, ImageDraw

    selected = _sample_evenly(frame_paths, max_frames)
    thumbs: list[tuple[Path, Image.Image]] = []
    for path in selected:
        image = Image.open(path).convert("RGB")
        if crop_box is not None:
            image = image.crop(crop_box)
        scale = max(float(thumb_width), 1.0) / max(float(image.width), 1.0)
        size = (
            max(1, int(round(image.width * scale))),
            max(1, int(round(image.height * scale))),
        )
        thumbs.append((path, image.resize(size, Image.Resampling.LANCZOS)))

    columns = max(1, int(columns))
    rows = int(math.ceil(len(thumbs) / float(columns)))
    cell_w = max(image.width for _, image in thumbs)
    cell_h = max(image.height for _, image in thumbs) + max(label_height, 0)
    canvas = Image.new(
        "RGB",
        (
            columns * cell_w + (columns + 1) * gutter,
            rows * cell_h + (rows + 1) * gutter,
        ),
        (18, 18, 20),
    )
    draw = ImageDraw.Draw(canvas)
    for idx, (path, image) in enumerate(thumbs):
        col = idx % columns
        row = idx // columns
        x = gutter + col * (cell_w + gutter)
        y = gutter + row * (cell_h + gutter)
        canvas.paste(image, (x, y + label_height))
        if label_height > 0:
            draw.text(
                (x, y + 3),
                f"{idx + 1:02d}/{len(frame_paths):02d} {path.name}",
                fill=(210, 214, 220),
            )

    filmstrip_path = output / output_name
    canvas.save(filmstrip_path)
    return filmstrip_path


def build_cropped_filmstrips_from_manifest(
    *,
    output_dir: str | Path,
    trace_events: Sequence[dict[str, Any]],
    manifest_name: str = "manifest.json",
    max_frames: int = 24,
    columns: int = 8,
    full_thumb_width: int = 360,
    overlay_thumb_width: int = 900,
    corner_thumb_width: int = 720,
    label_height: int = 22,
) -> dict[str, Path]:
    output = Path(output_dir).expanduser()
    frame_paths = _frame_paths_from_manifest(output, manifest_name)
    if not frame_paths:
        return {}

    from PIL import Image

    with Image.open(frame_paths[0]) as image:
        image_size = image.size
    overlay_box = infer_overlay_crop_box(image_size=image_size, trace_events=trace_events)
    corner_box = _top_left_corner_crop_box(overlay_box, image_size)
    strips: dict[str, Path] = {}
    full = build_filmstrip_from_manifest(
        output_dir=output,
        manifest_name=manifest_name,
        output_name="filmstrip-full.png",
        max_frames=max_frames,
        columns=columns,
        thumb_width=full_thumb_width,
        label_height=label_height,
    )
    if full is not None:
        strips["full"] = full
    overlay = build_filmstrip_from_manifest(
        output_dir=output,
        manifest_name=manifest_name,
        output_name="filmstrip-overlay.png",
        max_frames=max_frames,
        columns=columns,
        thumb_width=overlay_thumb_width,
        label_height=label_height,
        crop_box=overlay_box,
    )
    if overlay is not None:
        strips["overlay"] = overlay
    corner = build_filmstrip_from_manifest(
        output_dir=output,
        manifest_name=manifest_name,
        output_name="filmstrip-top-left-corner.png",
        max_frames=max_frames,
        columns=columns,
        thumb_width=corner_thumb_width,
        label_height=label_height,
        crop_box=corner_box,
    )
    if corner is not None:
        strips["top_left_corner"] = corner
    return strips


def run_autonomous_hammer_witness(
    *,
    trace_path: str | Path,
    output_dir: str | Path,
    repo_root: str | Path,
    perceptasia_root: str | Path = DEFAULT_PERCEPTASIA_ROOT,
    duration_seconds: float = 8.0,
    fps: float = 15.0,
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
    filmstrips = build_cropped_filmstrips_from_manifest(
        output_dir=output_dir,
        trace_events=trace_events,
    )
    return write_witness_index(
        output_dir=output_dir,
        trace_path=trace_path,
        started_at=started_at,
        ended_at=ended_at,
        command=command,
        trace_events=trace_events,
        filmstrip_path=filmstrips.get("full"),
        filmstrip_paths=filmstrips,
        stimulus=stimulus,
    )


def run_witness_window(
    *,
    trace_path: str | Path,
    output_dir: str | Path,
    perceptasia_root: str | Path = DEFAULT_PERCEPTASIA_ROOT,
    duration_seconds: float = 8.0,
    fps: float = 15.0,
    lane: str = DEFAULT_LANE,
    diaulos: str = DEFAULT_DIAULOS,
    source_app: str = DEFAULT_SOURCE_APP,
    source_window: str = DEFAULT_SOURCE_WINDOW,
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
    now: Callable[[], datetime] = _utc_now,
) -> Path:
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
    filmstrips = build_cropped_filmstrips_from_manifest(
        output_dir=output_dir,
        trace_events=trace_events,
    )
    return write_witness_index(
        output_dir=output_dir,
        trace_path=trace_path,
        started_at=started_at,
        ended_at=ended_at,
        command=command,
        trace_events=trace_events,
        filmstrip_path=filmstrips.get("full"),
        filmstrip_paths=filmstrips,
    )


def run_trace_triggered_witness(
    *,
    trace_path: str | Path,
    output_dir: str | Path,
    perceptasia_root: str | Path = DEFAULT_PERCEPTASIA_ROOT,
    duration_seconds: float = 4.0,
    fps: float = 18.0,
    trigger_event: str = "overlay.materialization.start",
    trigger_timeout_seconds: float = 30.0,
    lane: str = DEFAULT_LANE,
    diaulos: str = DEFAULT_DIAULOS,
    source_app: str = DEFAULT_SOURCE_APP,
    source_window: str = DEFAULT_SOURCE_WINDOW,
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
    now: Callable[[], datetime] = _utc_now,
) -> Path:
    start_line = trace_line_count(trace_path)
    armed_at = now()
    trigger = wait_for_trace_event(
        trace_path,
        event_name=trigger_event,
        start_line=start_line,
        timeout_seconds=trigger_timeout_seconds,
    )
    index_path = run_witness_window(
        trace_path=trace_path,
        output_dir=output_dir,
        perceptasia_root=perceptasia_root,
        duration_seconds=duration_seconds,
        fps=fps,
        lane=lane,
        diaulos=diaulos,
        source_app=source_app,
        source_window=source_window,
        runner=runner,
        now=now,
    )
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["armed_at"] = _format_instant(armed_at)
    payload["trigger_event"] = trigger
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return index_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a Retina Lasso capture window and index it against a Spoke trace."
    )
    parser.add_argument(
        "--trace",
        default=TRACE_AUTO,
        help="Command overlay JSONL trace to align with captures, or 'auto' for the freshest /tmp trace.",
    )
    parser.add_argument("--output-dir", required=True, help="Directory for Retina Lasso frames and witness index.")
    parser.add_argument("--perceptasia-root", default=str(DEFAULT_PERCEPTASIA_ROOT))
    parser.add_argument("--duration", type=float, default=8.0, help="Capture window length in seconds.")
    parser.add_argument("--fps", type=float, default=15.0, help="Requested still capture cadence.")
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
    parser.add_argument(
        "--arm-on-open",
        action="store_true",
        help="Wait for the next optical transition trace event, then capture and crop filmstrips.",
    )
    parser.add_argument("--trigger-event", default="overlay.materialization.start")
    parser.add_argument("--arm-timeout", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    trace_path = resolve_trace_path(args.trace)
    if args.arm_on_open:
        index_path = run_trace_triggered_witness(
            trace_path=trace_path,
            output_dir=args.output_dir,
            perceptasia_root=args.perceptasia_root,
            duration_seconds=args.duration,
            fps=args.fps,
            trigger_event=args.trigger_event,
            trigger_timeout_seconds=args.arm_timeout,
            lane=args.lane,
            diaulos=args.diaulos,
            source_app=args.source_app,
            source_window=args.source_window,
        )
    elif args.hammer_toggles or args.retarget_during_dismiss_repeats or args.launch_target:
        index_path = run_autonomous_hammer_witness(
            trace_path=trace_path,
            output_dir=args.output_dir,
            repo_root=Path(__file__).resolve().parents[1],
            perceptasia_root=args.perceptasia_root,
            duration_seconds=args.duration,
            fps=args.fps,
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
            trace_path=trace_path,
            output_dir=args.output_dir,
            perceptasia_root=args.perceptasia_root,
            duration_seconds=args.duration,
            fps=args.fps,
            lane=args.lane,
            diaulos=args.diaulos,
            source_app=args.source_app,
            source_window=args.source_window,
        )
    print(index_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
