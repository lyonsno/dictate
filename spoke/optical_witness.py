"""Spoke-native optical lifecycle frame witness artifacts.

The hot path stores bounded frame references in memory only. Artifact encoding
is explicit post-lifecycle work so summon/dismiss animation is not punctured by
disk I/O or synchronous capture.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


_DEFAULT_MAX_FRAMES = 90
_DEFAULT_OUTPUT_DIR = Path.home() / "Library/Application Support/Spoke/Optical Witness"
_MATERIAL_KEYS = (
    "core_magnification",
    "ring_amplitude_points",
    "tail_amplitude_points",
    "mip_blur_strength",
    "warp_mode",
    "scar_amount",
    "bleed_zone_frac",
    "exterior_mix_width_points",
    "x_squeeze",
    "y_squeeze",
    "cleanup_blur_radius_points",
)
_GEOMETRY_KEYS = (
    "center_x",
    "center_y",
    "content_width_points",
    "content_height_points",
    "corner_radius_points",
    "band_width_points",
    "tail_width_points",
)


@dataclass(frozen=True)
class OpticalWitnessRGBFrame:
    width: int
    height: int
    rgb: bytes
    timestamp_monotonic: float
    frame_index: int


@dataclass(frozen=True)
class OpticalWitnessPixelBufferFrame:
    width: int
    height: int
    pixel_buffer: object
    timestamp_monotonic: float
    frame_index: int


@dataclass(frozen=True)
class OpticalWitnessCrop:
    x: int
    y: int
    width: int
    height: int

    def clamped(self, frame_width: int, frame_height: int) -> "OpticalWitnessCrop":
        x = max(0, min(self.x, max(frame_width - 1, 0)))
        y = max(0, min(self.y, max(frame_height - 1, 0)))
        width = max(1, min(self.width, frame_width - x))
        height = max(1, min(self.height, frame_height - y))
        return OpticalWitnessCrop(x=x, y=y, width=width, height=height)

    def as_manifest(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass
class OpticalWitnessJob:
    event_id: str
    overlay_kind: str
    phase: str
    client_id: str
    crop: OpticalWitnessCrop
    frames: list[OpticalWitnessRGBFrame | OpticalWitnessPixelBufferFrame]
    dropped_frame_count: int
    started_at_monotonic: float
    ended_at_monotonic: float
    wall_time_iso: str
    source_ref: dict[str, Any]
    geometry: dict[str, Any]
    material: dict[str, Any]
    diagnostics: dict[str, Any]


@dataclass
class _ActiveWitnessEvent:
    event_id: str
    overlay_kind: str
    phase: str
    client_id: str
    crop: OpticalWitnessCrop
    started_at_monotonic: float
    wall_time_iso: str
    source_ref: dict[str, Any]
    geometry: dict[str, Any]
    material: dict[str, Any]
    frames: list[OpticalWitnessRGBFrame | OpticalWitnessPixelBufferFrame] = field(
        default_factory=list
    )
    dropped_frame_count: int = 0


class OpticalWitnessController:
    def __init__(
        self,
        *,
        enabled: bool = False,
        output_dir: str | Path = _DEFAULT_OUTPUT_DIR,
        max_frames: int = _DEFAULT_MAX_FRAMES,
    ) -> None:
        self.enabled = bool(enabled)
        self.output_dir = Path(output_dir).expanduser()
        self.max_frames = max(1, int(max_frames))
        self._lock = threading.Lock()
        self._active: dict[str, _ActiveWitnessEvent] = {}
        self._ready: list[OpticalWitnessJob] = []

    def configure(
        self,
        *,
        enabled: bool | None = None,
        output_dir: str | Path | None = None,
        max_frames: int | None = None,
    ) -> None:
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)
            if output_dir is not None:
                self.output_dir = Path(output_dir).expanduser()
            if max_frames is not None:
                self.max_frames = max(1, int(max_frames))

    def begin_lifecycle(
        self,
        *,
        overlay_kind: str,
        phase: str,
        client_id: str,
        shell_config: Mapping[str, Any],
        timestamp_monotonic: float | None = None,
        wall_time_iso: str | None = None,
        source_ref: Mapping[str, Any] | None = None,
    ) -> str | None:
        if not self.enabled:
            return None
        now = time.monotonic() if timestamp_monotonic is None else float(timestamp_monotonic)
        event_id = _event_id(overlay_kind, phase, client_id, wall_time_iso)
        event = _ActiveWitnessEvent(
            event_id=event_id,
            overlay_kind=str(overlay_kind),
            phase=str(phase),
            client_id=str(client_id),
            crop=_crop_from_shell_config(shell_config),
            started_at_monotonic=now,
            wall_time_iso=wall_time_iso or _utc_timestamp(),
            source_ref=dict(source_ref or current_source_ref()),
            geometry=_select_keys(shell_config, _GEOMETRY_KEYS),
            material=_select_keys(shell_config, _MATERIAL_KEYS),
        )
        with self._lock:
            self._active[event_id] = event
        return event_id

    def observe_frame(self, frame: OpticalWitnessRGBFrame | OpticalWitnessPixelBufferFrame) -> None:
        if not self.enabled:
            return
        with self._lock:
            events = list(self._active.values())
            max_frames = self.max_frames
        for event in events:
            with self._lock:
                active = self._active.get(event.event_id)
                if active is None:
                    continue
                if len(active.frames) >= max_frames:
                    active.dropped_frame_count += 1
                    continue
                active.frames.append(frame)

    def observe_compositor_frame(
        self,
        *,
        pixel_buffer=None,
        width: int,
        height: int,
        timestamp_monotonic: float | None = None,
        frame_index: int = 0,
        **_ignored,
    ) -> None:
        if pixel_buffer is None:
            return
        self.observe_frame(
            OpticalWitnessPixelBufferFrame(
                width=int(width),
                height=int(height),
                pixel_buffer=pixel_buffer,
                timestamp_monotonic=(
                    time.monotonic()
                    if timestamp_monotonic is None
                    else float(timestamp_monotonic)
                ),
                frame_index=int(frame_index),
            )
        )

    def end_lifecycle(
        self,
        event_id: str | None,
        *,
        timestamp_monotonic: float | None = None,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> OpticalWitnessJob | None:
        if not event_id:
            return None
        ended = time.monotonic() if timestamp_monotonic is None else float(timestamp_monotonic)
        with self._lock:
            event = self._active.pop(event_id, None)
            if event is None:
                return None
            job = OpticalWitnessJob(
                event_id=event.event_id,
                overlay_kind=event.overlay_kind,
                phase=event.phase,
                client_id=event.client_id,
                crop=event.crop,
                frames=list(event.frames),
                dropped_frame_count=event.dropped_frame_count,
                started_at_monotonic=event.started_at_monotonic,
                ended_at_monotonic=ended,
                wall_time_iso=event.wall_time_iso,
                source_ref=dict(event.source_ref),
                geometry=dict(event.geometry),
                material=dict(event.material),
                diagnostics=dict(diagnostics or {}),
            )
            self._ready.append(job)
            return job

    def drain_ready(self) -> list[Path]:
        with self._lock:
            jobs = list(self._ready)
            self._ready.clear()
            output_dir = self.output_dir
        writer = OpticalWitnessArtifactWriter(output_dir)
        return [writer.write(job) for job in jobs]


class OpticalWitnessArtifactWriter:
    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir).expanduser()

    def write(self, job: OpticalWitnessJob) -> Path:
        bundle = self.output_dir / _bundle_name(job)
        frames_dir = bundle / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        cropped_frames = []
        for index, frame in enumerate(job.frames):
            cropped = _cropped_rgb(frame, job.crop)
            if cropped is None:
                continue
            width, height, rgb = cropped
            frame_path = frames_dir / f"frame_{index:04d}.ppm"
            _write_ppm(frame_path, width, height, rgb)
            cropped_frames.append((width, height, rgb, frame.timestamp_monotonic))
        if cropped_frames:
            sheet_w, sheet_h, sheet_rgb = _contact_sheet(cropped_frames)
            _write_ppm(bundle / "contact_sheet.ppm", sheet_w, sheet_h, sheet_rgb)
        manifest = _manifest_payload(job, len(cropped_frames))
        (bundle / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        return bundle


_CONTROLLER: OpticalWitnessController | None = None


def get_optical_witness_controller() -> OpticalWitnessController:
    global _CONTROLLER
    if _CONTROLLER is None:
        _CONTROLLER = OpticalWitnessController(
            enabled=_env_bool("SPOKE_OPTICAL_WITNESS_ENABLED", False),
            output_dir=os.environ.get("SPOKE_OPTICAL_WITNESS_DIR", _DEFAULT_OUTPUT_DIR),
            max_frames=int(os.environ.get("SPOKE_OPTICAL_WITNESS_MAX_FRAMES", _DEFAULT_MAX_FRAMES)),
        )
    return _CONTROLLER


def set_optical_witness_enabled(enabled: bool) -> OpticalWitnessController:
    controller = get_optical_witness_controller()
    controller.configure(enabled=enabled)
    return controller


def current_source_ref(repo_root: str | Path | None = None) -> dict[str, str]:
    root = Path(repo_root or Path(__file__).resolve().parents[1])

    def git(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return ""
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    return {
        "branch": git("branch", "--show-current") or "unknown",
        "commit": git("rev-parse", "--short", "HEAD") or "unknown",
    }


def _crop_from_shell_config(shell_config: Mapping[str, Any]) -> OpticalWitnessCrop:
    cx = float(shell_config.get("center_x", 0.0))
    cy = float(shell_config.get("center_y", 0.0))
    width = max(1, int(round(float(shell_config.get("content_width_points", 1.0)))))
    height = max(1, int(round(float(shell_config.get("content_height_points", 1.0)))))
    return OpticalWitnessCrop(
        x=int(round(cx - width / 2.0)),
        y=int(round(cy - height / 2.0)),
        width=width,
        height=height,
    )


def _select_keys(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: mapping[key] for key in keys if key in mapping}


def _cropped_rgb(
    frame: OpticalWitnessRGBFrame | OpticalWitnessPixelBufferFrame,
    crop: OpticalWitnessCrop,
) -> tuple[int, int, bytes] | None:
    if isinstance(frame, OpticalWitnessRGBFrame):
        frame_crop = crop.clamped(frame.width, frame.height)
        return (
            frame_crop.width,
            frame_crop.height,
            _crop_rgb_bytes(frame.rgb, frame.width, frame.height, frame_crop),
        )
    rgb = _rgb_from_pixel_buffer(frame.pixel_buffer, frame.width, frame.height, crop)
    if rgb is None:
        return None
    return rgb


def _crop_rgb_bytes(
    rgb: bytes,
    width: int,
    height: int,
    crop: OpticalWitnessCrop,
) -> bytes:
    if len(rgb) < width * height * 3:
        return b""
    out = bytearray()
    for y in range(crop.y, crop.y + crop.height):
        start = (y * width + crop.x) * 3
        end = start + crop.width * 3
        out.extend(rgb[start:end])
    return bytes(out)


def _rgb_from_pixel_buffer(
    pixel_buffer,
    width: int,
    height: int,
    crop: OpticalWitnessCrop,
) -> tuple[int, int, bytes] | None:
    try:
        import ctypes
        import objc

        from spoke.fullscreen_compositor import _load_screencapturekit_bridge

        bridge = _load_screencapturekit_bridge()
        cv_lib = bridge.get("_cv_lib") if bridge else None
        if cv_lib is None or pixel_buffer is None:
            return None
        raw_pb = objc.pyobjc_id(pixel_buffer)
        readonly = 1
        cv_lib.CVPixelBufferLockBaseAddress.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        cv_lib.CVPixelBufferLockBaseAddress.restype = ctypes.c_int
        cv_lib.CVPixelBufferUnlockBaseAddress.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        cv_lib.CVPixelBufferUnlockBaseAddress.restype = ctypes.c_int
        cv_lib.CVPixelBufferGetBaseAddress.argtypes = [ctypes.c_void_p]
        cv_lib.CVPixelBufferGetBaseAddress.restype = ctypes.c_void_p
        cv_lib.CVPixelBufferGetBytesPerRow.argtypes = [ctypes.c_void_p]
        cv_lib.CVPixelBufferGetBytesPerRow.restype = ctypes.c_size_t
        if cv_lib.CVPixelBufferLockBaseAddress(raw_pb, readonly) != 0:
            return None
        try:
            base = cv_lib.CVPixelBufferGetBaseAddress(raw_pb)
            bytes_per_row = int(cv_lib.CVPixelBufferGetBytesPerRow(raw_pb))
            if not base or bytes_per_row <= 0:
                return None
            frame_crop = crop.clamped(width, height)
            data = (ctypes.c_ubyte * (bytes_per_row * height)).from_address(base)
            out = bytearray()
            for y in range(frame_crop.y, frame_crop.y + frame_crop.height):
                row = y * bytes_per_row
                for x in range(frame_crop.x, frame_crop.x + frame_crop.width):
                    offset = row + x * 4
                    if offset + 2 < len(data):
                        b = data[offset]
                        g = data[offset + 1]
                        r = data[offset + 2]
                        out.extend((r, g, b))
            return frame_crop.width, frame_crop.height, bytes(out)
        finally:
            cv_lib.CVPixelBufferUnlockBaseAddress(raw_pb, readonly)
    except Exception:
        return None


def _contact_sheet(frames: list[tuple[int, int, bytes, float]]) -> tuple[int, int, bytes]:
    widths = [width for width, _height, _rgb, _ts in frames]
    heights = [height for _width, height, _rgb, _ts in frames]
    sheet_w = sum(widths)
    sheet_h = max(heights)
    sheet = bytearray(b"\x00" * (sheet_w * sheet_h * 3))
    cursor_x = 0
    for width, height, rgb, _ts in frames:
        for y in range(height):
            src = y * width * 3
            dst = (y * sheet_w + cursor_x) * 3
            sheet[dst:dst + width * 3] = rgb[src:src + width * 3]
        cursor_x += width
    return sheet_w, sheet_h, bytes(sheet)


def _write_ppm(path: Path, width: int, height: int, rgb: bytes) -> None:
    path.write_bytes(f"P6\n{width} {height}\n255\n".encode("ascii") + rgb)


def _manifest_payload(job: OpticalWitnessJob, encoded_frame_count: int) -> dict[str, Any]:
    return {
        "event_id": job.event_id,
        "overlay_kind": job.overlay_kind,
        "phase": job.phase,
        "client_id": job.client_id,
        "wall_time_iso": job.wall_time_iso,
        "started_at_monotonic": job.started_at_monotonic,
        "ended_at_monotonic": job.ended_at_monotonic,
        "duration_ms": max(
            (job.ended_at_monotonic - job.started_at_monotonic) * 1000.0,
            0.0,
        ),
        "frame_count": encoded_frame_count,
        "captured_frame_count": len(job.frames),
        "dropped_frame_count": job.dropped_frame_count,
        "crop": job.crop.as_manifest(),
        "geometry": job.geometry,
        "material": job.material,
        "diagnostics": job.diagnostics,
        "source_ref": job.source_ref,
    }


def _bundle_name(job: OpticalWitnessJob) -> str:
    stamp = _sanitize(job.wall_time_iso).strip("_") or "unknown_time"
    return "_".join(
        [
            stamp,
            _sanitize(job.overlay_kind),
            _sanitize(job.phase),
            _sanitize(job.client_id),
        ]
    )


def _event_id(
    overlay_kind: str,
    phase: str,
    client_id: str,
    wall_time_iso: str | None,
) -> str:
    stamp = _sanitize(wall_time_iso or _utc_timestamp()).strip("_")
    return f"{stamp}:{overlay_kind}:{phase}:{client_id}"


def _sanitize(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_")


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

