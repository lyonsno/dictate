"""Shared optical-shell transition choreography.

This module owns the House-level materialize/dismiss geometry and sidecar
config math. UI consumers may bring their own content, geometry, and identity;
the pressure-slit warp grammar lives here instead of inside one overlay.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os


def _env(name: str, default: float) -> float:
    v = os.environ.get(name)
    return float(v) if v is not None else default


def clamp01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def lerp(start: float, end: float, t: float) -> float:
    return start + (end - start) * t


def smoothstep(progress: float) -> float:
    t = clamp01(progress)
    return t * t * (3.0 - 2.0 * t)


def snap_ease_in(progress: float) -> float:
    t = clamp01(progress)
    return t * t * t


PRESSURE_SLIT_SMOKE_TIME_SCALE = 1.0 / 3.0
OPTICAL_MATERIALIZATION_BASE_S = 1.36 * PRESSURE_SLIT_SMOKE_TIME_SCALE
OPTICAL_MATERIALIZATION_BASE_SPREAD_END = 0.77
OPTICAL_MATERIALIZATION_SEAM_OPEN_SPEEDUP = 2.0
OPTICAL_MATERIALIZATION_POST_SPREAD_TIME_SCALE = 2.0
OPTICAL_MATERIALIZATION_SEAM_OPEN_S = (
    OPTICAL_MATERIALIZATION_BASE_S
    * OPTICAL_MATERIALIZATION_BASE_SPREAD_END
    / OPTICAL_MATERIALIZATION_SEAM_OPEN_SPEEDUP
)
OPTICAL_MATERIALIZATION_S = (
    OPTICAL_MATERIALIZATION_SEAM_OPEN_S
    + (
        OPTICAL_MATERIALIZATION_BASE_S
        - OPTICAL_MATERIALIZATION_SEAM_OPEN_S
    )
    * OPTICAL_MATERIALIZATION_POST_SPREAD_TIME_SCALE
)
OPTICAL_MATERIALIZATION_DISMISS_S = OPTICAL_MATERIALIZATION_BASE_S
OPTICAL_MATERIALIZATION_PUCKER_TAIL_S = 1.5 * PRESSURE_SLIT_SMOKE_TIME_SCALE
OPTICAL_MATERIALIZATION_PUCKER_OVERLAP_START_PROGRESS = 0.42
OPTICAL_MATERIALIZATION_PUCKER_PREARM_TAIL_PROGRESS = 0.12
OPTICAL_MATERIALIZATION_SEAM_LATCH_START = 0.0
OPTICAL_MATERIALIZATION_SEAM_LATCH_INTENSITY = 2.0
OPTICAL_MATERIALIZATION_SEAM_LENGTH_FRAC = 0.8
OPTICAL_MATERIALIZATION_SEAM_LENGTH_CLOSED_FRAC = 0.0
OPTICAL_MATERIALIZATION_SEAM_THICKNESS_FRAC = 0.15
OPTICAL_MATERIALIZATION_SEAM_FOCUS_FRAC = 1.0
OPTICAL_MATERIALIZATION_SEAM_VERTICAL_GRIP = 1.0
OPTICAL_MATERIALIZATION_SEAM_HORIZONTAL_GRIP = 0.60
OPTICAL_MATERIALIZATION_SEAM_AXIS_ROTATION = 0.0
OPTICAL_MATERIALIZATION_SEAM_MIRRORED_LIP = 0.0
OPTICAL_MATERIALIZATION_SEAM_FIELD_HEIGHT_FRAC = 0.72
OPTICAL_MATERIALIZATION_SEAM_FIELD_MIN_HEIGHT_POINTS = 96.0
DISMISS_SEAM_CLIENT_ID = "assistant.command.dismiss_seam"
DISMISS_RADIAL_PUCKER_CLIENT_ID = "assistant.command.dismiss_radial_pucker"
OPTICAL_MATERIALIZATION_RADIAL_PUCKER_INTENSITY = 0.25
OPTICAL_MATERIALIZATION_RADIAL_AREA_MULTIPLIER = 10.0
OPTICAL_MATERIALIZATION_PUCKER_DIAGNOSTIC_GAIN = 5.0
OPTICAL_MATERIALIZATION_PUCKER_GAIN_PEAK_AT = 0.30
OPTICAL_MATERIALIZATION_RADIAL_CYCLES = 2.35
OPTICAL_MATERIALIZATION_RADIAL_DAMPING = 4.4
OPTICAL_MATERIALIZATION_DISMISS_TOTAL_S = (
    OPTICAL_MATERIALIZATION_DISMISS_S
    + OPTICAL_MATERIALIZATION_PUCKER_TAIL_S
)
OPTICAL_MATERIALIZATION_BODY_READY = 0.55
OPTICAL_MATERIALIZATION_SEED_WIDTH_FRAC = 0.06
OPTICAL_MATERIALIZATION_SEED_HEIGHT_FRAC = 0.028
OPTICAL_MATERIALIZATION_SPREAD_END = (
    OPTICAL_MATERIALIZATION_SEAM_OPEN_S / OPTICAL_MATERIALIZATION_S
)
OPTICAL_MATERIALIZATION_BLOOM_START = OPTICAL_MATERIALIZATION_SPREAD_END
OPTICAL_MATERIALIZATION_MAG_SEED_FRAC = 0.04
OPTICAL_MATERIALIZATION_MAG_ACCEL_END = 0.42
OPTICAL_MATERIALIZATION_MAG_OVERSHOOT_AT = 0.72
OPTICAL_MATERIALIZATION_MAG_OVERSHOOT = 1.20
OPTICAL_MATERIAL_FILL_START = OPTICAL_MATERIALIZATION_SPREAD_END
OPTICAL_MATERIAL_FILL_SOLID_AT = (
    OPTICAL_MATERIALIZATION_SEAM_OPEN_S
    + (
        OPTICAL_MATERIALIZATION_BASE_S * 0.84
        - OPTICAL_MATERIALIZATION_SEAM_OPEN_S
    )
    * OPTICAL_MATERIALIZATION_POST_SPREAD_TIME_SCALE
) / OPTICAL_MATERIALIZATION_S
OPTICAL_MATERIAL_FILL_FULL_AT = (
    OPTICAL_MATERIALIZATION_SEAM_OPEN_S
    + (
        OPTICAL_MATERIALIZATION_BASE_S * 0.96
        - OPTICAL_MATERIALIZATION_SEAM_OPEN_S
    )
    * OPTICAL_MATERIALIZATION_POST_SPREAD_TIME_SCALE
) / OPTICAL_MATERIALIZATION_S
OPTICAL_MATERIAL_FILL_MIN_HEIGHT_FRAC = 0.011
OPTICAL_MATERIALIZATION_PUCKER_PREARM_START_PROGRESS = (
    OPTICAL_MATERIAL_FILL_SOLID_AT
    + (
        OPTICAL_MATERIAL_FILL_FULL_AT
        - OPTICAL_MATERIAL_FILL_SOLID_AT
    )
    * (
        (1.0 / 3.0 - OPTICAL_MATERIAL_FILL_MIN_HEIGHT_FRAC)
        / (1.0 - OPTICAL_MATERIAL_FILL_MIN_HEIGHT_FRAC)
    )
    ** (1.0 / 3.0)
)
OPTICAL_MATERIALIZATION_SEAM_OVERLAP_START_PROGRESS = (
    OPTICAL_MATERIALIZATION_PUCKER_PREARM_START_PROGRESS
)
OPTICAL_MATERIALIZATION_SEAM_PEAK_PROGRESS = OPTICAL_MATERIAL_FILL_SOLID_AT
POINTS_PER_CM = 72.0 / 2.54
OPTICAL_SHELL_FEATHER = 140.0
COMMAND_MATERIAL_FILL_OVERSCAN_POINTS = (
    _env("SPOKE_COMMAND_MATERIAL_FILL_OVERSCAN_MM", 1.5) / 10.0 * POINTS_PER_CM
)


@dataclass(frozen=True)
class OpticalTransitionFrame:
    progress: float
    main_config: dict
    seam_config: dict | None = None
    radial_config: dict | None = None
    complete: bool = False
    body_ready: bool = False


def _sidecar_id(client_id: str, suffix: str) -> str:
    return f"{client_id}.{suffix}" if client_id else suffix


def materialization_fill_state(progress: float) -> dict[str, float]:
    p = clamp01(progress)
    if p <= OPTICAL_MATERIAL_FILL_START:
        opacity = 0.0
    else:
        opacity = smoothstep(
            (p - OPTICAL_MATERIAL_FILL_START)
            / max(OPTICAL_MATERIAL_FILL_SOLID_AT - OPTICAL_MATERIAL_FILL_START, 1e-6)
        )
    height = lerp(
        OPTICAL_MATERIAL_FILL_MIN_HEIGHT_FRAC,
        1.0,
        clamp01(
            (p - OPTICAL_MATERIAL_FILL_SOLID_AT)
            / max(OPTICAL_MATERIAL_FILL_FULL_AT - OPTICAL_MATERIAL_FILL_SOLID_AT, 1e-6)
        )
        ** 3.0,
    )
    warp_bloom = snap_ease_in(
        (p - OPTICAL_MATERIALIZATION_BLOOM_START)
        / max(1.0 - OPTICAL_MATERIALIZATION_BLOOM_START, 1e-6)
    )
    height = min(height, max(OPTICAL_MATERIAL_FILL_MIN_HEIGHT_FRAC, warp_bloom))
    return {
        "opacity": clamp01(opacity),
        "height_frac": clamp01(height),
    }


def _with_gpu_material_basis(
    config: dict,
    *,
    width: float,
    height: float,
    corner_radius: float,
    progress: float = 1.0,
) -> None:
    if float(config.get("gpu_material_enabled", 0.0)) < 0.5:
        return
    state = materialization_fill_state(progress)
    config["gpu_material_base_width_points"] = max(float(width), 1.0)
    config["gpu_material_base_height_points"] = max(float(height), 1.0)
    config["gpu_material_base_corner_radius_points"] = max(float(corner_radius), 1.0)
    config["gpu_material_height_frac"] = state["height_frac"]
    config["gpu_material_opacity"] = min(
        float(config.get("gpu_material_opacity", 1.0)),
        state["opacity"] if progress < 1.0 else float(config.get("gpu_material_opacity", 1.0)),
    )


def materialized_shell_config(shell_config: dict, progress: float) -> dict:
    """Return a transient shell config for fluid entrance/dismissal."""
    config = dict(shell_config)
    p = clamp01(progress)
    if p >= 1.0:
        return config

    base_w = max(float(config.get("content_width_points", 1.0)), 1.0)
    base_h = max(float(config.get("content_height_points", 1.0)), 1.0)
    base_radius = max(float(config.get("corner_radius_points", 1.0)), 1.0)
    config["_materialization_base_width_points"] = base_w
    config["_materialization_base_height_points"] = base_h
    config["_materialization_base_corner_radius_points"] = base_radius
    _with_gpu_material_basis(
        config,
        width=base_w,
        height=base_h,
        corner_radius=base_radius,
        progress=p,
    )

    spread_t = snap_ease_in(p / OPTICAL_MATERIALIZATION_SPREAD_END)
    bloom_t = snap_ease_in(
        (p - OPTICAL_MATERIALIZATION_BLOOM_START)
        / max(1.0 - OPTICAL_MATERIALIZATION_BLOOM_START, 1e-6)
    )
    seed_w = max(24.0, min(base_w * OPTICAL_MATERIALIZATION_SEED_WIDTH_FRAC, 72.0))
    seed_h = max(2.5, min(base_h * OPTICAL_MATERIALIZATION_SEED_HEIGHT_FRAC, 7.0))
    width = lerp(seed_w, base_w, spread_t)
    height = lerp(seed_h, base_h, bloom_t)

    config["content_width_points"] = width
    config["content_height_points"] = height
    config["corner_radius_points"] = min(base_radius, height * 0.5)
    if "core_magnification" in config:
        base_mag = max(float(config.get("core_magnification", 1.0)), 0.0)
        seed_mag = base_mag * OPTICAL_MATERIALIZATION_MAG_SEED_FRAC
        if p <= OPTICAL_MATERIALIZATION_MAG_ACCEL_END:
            t = clamp01(p / OPTICAL_MATERIALIZATION_MAG_ACCEL_END)
            config["core_magnification"] = lerp(
                seed_mag,
                base_mag * 0.82,
                snap_ease_in(t),
            )
        elif p <= OPTICAL_MATERIALIZATION_MAG_OVERSHOOT_AT:
            t = clamp01(
                (p - OPTICAL_MATERIALIZATION_MAG_ACCEL_END)
                / (
                    OPTICAL_MATERIALIZATION_MAG_OVERSHOOT_AT
                    - OPTICAL_MATERIALIZATION_MAG_ACCEL_END
                )
            )
            config["core_magnification"] = lerp(
                base_mag * 0.82,
                base_mag * OPTICAL_MATERIALIZATION_MAG_OVERSHOOT,
                snap_ease_in(t),
            )
        else:
            t = clamp01(
                (p - OPTICAL_MATERIALIZATION_MAG_OVERSHOOT_AT)
                / max(1.0 - OPTICAL_MATERIALIZATION_MAG_OVERSHOOT_AT, 1e-6)
            )
            config["core_magnification"] = lerp(
                base_mag * OPTICAL_MATERIALIZATION_MAG_OVERSHOOT,
                base_mag,
                snap_ease_in(t),
            )
    for key in ("band_width_points", "tail_width_points"):
        if key in config:
            config[key] = max(1.0, float(config[key]) * lerp(0.25, 1.0, p))
    for key in ("ring_amplitude_points", "tail_amplitude_points"):
        if key in config:
            config[key] = float(config[key]) * lerp(0.35, 1.0, p)
    config["continuous_present"] = True
    return config


def dismiss_materialization_fill_state(progress: float) -> dict[str, float]:
    """Keep the visible shell body alive until the seam sidecar owns dismissal."""
    p = clamp01(progress)
    if p <= OPTICAL_MATERIALIZATION_PUCKER_OVERLAP_START_PROGRESS:
        return {
            "opacity": 0.0,
            "height_frac": OPTICAL_MATERIAL_FILL_MIN_HEIGHT_FRAC,
        }
    state = materialization_fill_state(p)
    return {
        "opacity": state["opacity"],
        "height_frac": state["height_frac"],
    }


def dismiss_pucker_amount(progress: float) -> float:
    """Signed radial ringdown: an underdamped pucker after the seam vanishes."""
    p = clamp01(progress)
    return math.exp(-OPTICAL_MATERIALIZATION_RADIAL_DAMPING * p) * math.cos(
        2.0 * math.pi * OPTICAL_MATERIALIZATION_RADIAL_CYCLES * p
    )


def dismiss_pucker_tail_progress_for_close_progress(close_progress: float) -> float:
    """Advance the radial tail while the shell is visually shrinking away."""
    start = max(OPTICAL_MATERIALIZATION_PUCKER_PREARM_START_PROGRESS, 1e-6)
    phase = clamp01((start - clamp01(close_progress)) / start)
    return lerp(
        0.0,
        OPTICAL_MATERIALIZATION_PUCKER_PREARM_TAIL_PROGRESS,
        phase,
    )


def dismiss_seam_latch_amount(progress: float) -> float:
    """Positive seam pucker already present at latch start, deeper at closure."""
    p = clamp01(progress)
    start = max(OPTICAL_MATERIALIZATION_PUCKER_OVERLAP_START_PROGRESS, 1e-6)
    t = clamp01((start - p) / start)
    return lerp(
        OPTICAL_MATERIALIZATION_SEAM_LATCH_START,
        1.0,
        1.0 - (1.0 - t) ** 3.0,
    )


def seam_pucker_tuning_defaults() -> dict[str, float]:
    return {
        "preview_progress": OPTICAL_MATERIALIZATION_PUCKER_OVERLAP_START_PROGRESS * 0.45,
        "seam_latch_start": OPTICAL_MATERIALIZATION_SEAM_LATCH_START,
        "seam_latch_intensity": OPTICAL_MATERIALIZATION_SEAM_LATCH_INTENSITY,
        "scar_seam_length_frac": OPTICAL_MATERIALIZATION_SEAM_LENGTH_FRAC,
        "scar_seam_thickness_frac": OPTICAL_MATERIALIZATION_SEAM_THICKNESS_FRAC,
        "scar_seam_focus_frac": OPTICAL_MATERIALIZATION_SEAM_FOCUS_FRAC,
        "scar_vertical_grip": OPTICAL_MATERIALIZATION_SEAM_VERTICAL_GRIP,
        "scar_horizontal_grip": OPTICAL_MATERIALIZATION_SEAM_HORIZONTAL_GRIP,
        "scar_axis_rotation": OPTICAL_MATERIALIZATION_SEAM_AXIS_ROTATION,
        "scar_mirrored_lip": OPTICAL_MATERIALIZATION_SEAM_MIRRORED_LIP,
    }


def dismiss_pucker_amplitude_multiplier(progress: float) -> float:
    """Diagnostic gain envelope: quick visibility peak, long elastic decay."""
    p = clamp01(progress)
    peak_at = max(OPTICAL_MATERIALIZATION_PUCKER_GAIN_PEAK_AT, 1e-6)
    if p <= peak_at:
        t = p / peak_at
        return lerp(
            1.0,
            OPTICAL_MATERIALIZATION_PUCKER_DIAGNOSTIC_GAIN,
            1.0 - (1.0 - t) ** 3.0,
        )
    t = (p - peak_at) / max(1.0 - peak_at, 1e-6)
    return OPTICAL_MATERIALIZATION_PUCKER_DIAGNOSTIC_GAIN * math.exp(-5.0 * t)


def apply_dismiss_seam_latch_fields(
    config: dict,
    progress: float,
    tuning: dict[str, float] | None = None,
) -> dict:
    """Apply the crisp seam latch while the slit is still zipping closed."""
    updated = dict(config)
    settings = seam_pucker_tuning_defaults()
    if tuning:
        for key, value in tuning.items():
            if key in settings:
                settings[key] = float(value)
    p = clamp01(progress)
    overlap_start = max(OPTICAL_MATERIALIZATION_PUCKER_OVERLAP_START_PROGRESS, 1e-6)
    t = clamp01((overlap_start - p) / overlap_start)
    base_h = max(
        float(
            updated.get(
                "_materialization_base_height_points",
                updated.get("content_height_points", 1.0),
            )
        ),
        1.0,
    )
    current_h = max(float(updated.get("content_height_points", 1.0)), 1.0)
    seam_field_h = max(
        current_h,
        min(
            base_h,
            max(
                OPTICAL_MATERIALIZATION_SEAM_FIELD_MIN_HEIGHT_POINTS,
                base_h * OPTICAL_MATERIALIZATION_SEAM_FIELD_HEIGHT_FRAC,
            ),
        ),
    )
    amount = lerp(
        settings["seam_latch_start"],
        1.0,
        1.0 - (1.0 - t) ** 3.0,
    ) * settings["seam_latch_intensity"]
    updated["content_height_points"] = seam_field_h
    updated["corner_radius_points"] = min(
        max(float(updated.get("corner_radius_points", 1.0)), 1.0),
        seam_field_h * 0.5,
    )
    updated["cleanup_blur_radius_points"] = 0.0
    updated["mip_blur_strength"] = 0.0
    updated["warp_mode"] = 3.0 if settings["scar_mirrored_lip"] >= 0.5 else 1.0
    updated["scar_amount"] = amount
    updated["scar_seam_length_frac"] = settings["scar_seam_length_frac"]
    updated["scar_seam_thickness_frac"] = settings["scar_seam_thickness_frac"]
    updated["scar_seam_focus_frac"] = settings["scar_seam_focus_frac"]
    updated["scar_vertical_grip"] = settings["scar_vertical_grip"]
    updated["scar_horizontal_grip"] = settings["scar_horizontal_grip"]
    updated["scar_axis_rotation"] = settings["scar_axis_rotation"]
    updated["scar_mirrored_lip"] = settings["scar_mirrored_lip"]
    updated["x_squeeze"] = 1.0
    updated["y_squeeze"] = 1.0
    updated["ring_amplitude_points"] = 0.0
    updated["tail_amplitude_points"] = 0.0
    updated["continuous_present"] = True
    return updated


def dismiss_seam_tuning_for_close_progress(
    close_progress: float,
    tuning: dict[str, float] | None = None,
) -> dict[str, float]:
    """Map close progress onto the seam tuner path without firing peak too early."""
    settings = seam_pucker_tuning_defaults()
    if tuning:
        for key, value in tuning.items():
            if key in settings:
                settings[key] = float(value)
    p = clamp01(close_progress)
    arm_start = max(OPTICAL_MATERIALIZATION_SEAM_OVERLAP_START_PROGRESS, 1e-6)
    peak = max(OPTICAL_MATERIALIZATION_SEAM_PEAK_PROGRESS, 1e-6)
    if p >= peak:
        arm_phase = smoothstep((arm_start - p) / max(arm_start - peak, 1e-6))
        settings["preview_progress"] = 0.0
        settings["seam_latch_intensity"] *= arm_phase
        settings["scar_seam_length_frac"] = OPTICAL_MATERIALIZATION_SEAM_LENGTH_FRAC
        return settings

    phase = clamp01((peak - p) / peak)
    settings["preview_progress"] = lerp(
        0.0,
        OPTICAL_MATERIALIZATION_PUCKER_OVERLAP_START_PROGRESS,
        phase,
    )
    settings["scar_seam_length_frac"] = lerp(
        OPTICAL_MATERIALIZATION_SEAM_LENGTH_FRAC,
        OPTICAL_MATERIALIZATION_SEAM_LENGTH_CLOSED_FRAC,
        phase,
    )
    return settings


def dismiss_seam_latch_shell_config(
    final_shell_config: dict,
    progress: float,
    tuning: dict[str, float] | None = None,
    *,
    client_id: str = DISMISS_SEAM_CLIENT_ID,
    role: str = "assistant",
    z_index: int = 10,
) -> dict:
    """Return the full-width seam field layered over the close animation."""
    config = dict(final_shell_config)
    config["client_id"] = client_id
    config["role"] = role
    config["visible"] = True
    config["z_index"] = z_index
    seam_tuning = dismiss_seam_tuning_for_close_progress(progress, tuning)
    return apply_dismiss_seam_latch_fields(
        config,
        seam_tuning["preview_progress"],
        seam_tuning,
    )


def apply_dismiss_radial_pucker_fields(config: dict, progress: float) -> dict:
    """Apply the post-close radial underdamped pucker without blur."""
    updated = dict(config)
    amount = (
        dismiss_pucker_amount(progress)
        * OPTICAL_MATERIALIZATION_RADIAL_PUCKER_INTENSITY
        * dismiss_pucker_amplitude_multiplier(progress)
    )
    updated["cleanup_blur_radius_points"] = 0.0
    updated["mip_blur_strength"] = 0.0
    updated["warp_mode"] = 2.0
    updated["scar_amount"] = amount
    updated["x_squeeze"] = 1.0
    updated["y_squeeze"] = 1.0
    updated["ring_amplitude_points"] = 0.0
    updated["tail_amplitude_points"] = 0.0
    updated["continuous_present"] = True
    return updated


def dismiss_pucker_shell_config(shell_config: dict, progress: float) -> dict:
    """Return the radial underdamped scar that releases after dismiss closes."""
    base_w = max(float(shell_config.get("content_width_points", 1.0)), 1.0)
    base_h = max(float(shell_config.get("content_height_points", 1.0)), 1.0)
    config = materialized_shell_config(shell_config, 0.0)
    base_diameter = max(560.0, min(base_w * 0.52, base_h * 2.9))
    diameter = base_diameter * math.sqrt(OPTICAL_MATERIALIZATION_RADIAL_AREA_MULTIPLIER)
    config["content_width_points"] = diameter
    config["content_height_points"] = diameter
    config["corner_radius_points"] = diameter * 0.5
    config["core_magnification"] = 1.0
    return apply_dismiss_radial_pucker_fields(config, progress)


def dismiss_radial_pucker_shell_config(
    shell_config: dict,
    progress: float,
    *,
    client_id: str = DISMISS_RADIAL_PUCKER_CLIENT_ID,
    role: str = "assistant",
    z_index: int = 9,
) -> dict:
    """Return the radial scar as an independent compositor client."""
    config = dismiss_pucker_shell_config(shell_config, progress)
    config["client_id"] = client_id
    config["role"] = role
    config["visible"] = True
    config["z_index"] = z_index
    return config


def hidden_dismiss_main_shell_config(shell_config: dict) -> dict:
    """Keep the main client registered without drawing a default shell frame."""
    config = materialized_shell_config(shell_config, 0.0)
    config["visible"] = False
    config["continuous_present"] = True
    config["mip_blur_strength"] = 0.0
    config["cleanup_blur_radius_points"] = 0.0
    return config


class OpticalTransitionRunner:
    """Deterministic House transition frame generator for one optical surface."""

    def __init__(
        self,
        final_shell_config: dict,
        *,
        direction: int = 1,
        client_id: str = "assistant.command",
        role: str = "assistant",
        z_index: int = 0,
    ) -> None:
        self.final_shell_config = dict(final_shell_config)
        self.direction = 1 if direction >= 0 else -1
        self.client_id = client_id
        self.role = role
        self.z_index = z_index

    @property
    def duration_s(self) -> float:
        if self.direction > 0:
            return OPTICAL_MATERIALIZATION_S
        return OPTICAL_MATERIALIZATION_DISMISS_S

    def frame_at(self, elapsed_s: float) -> OpticalTransitionFrame:
        raw = clamp01(max(elapsed_s, 0.0) / max(self.duration_s, 1e-6))
        progress = raw if self.direction > 0 else 1.0 - raw
        main_config = materialized_shell_config(self.final_shell_config, progress)
        seam_config = None
        radial_config = None
        if self.direction < 0:
            if progress <= OPTICAL_MATERIALIZATION_PUCKER_PREARM_START_PROGRESS:
                pucker_progress = dismiss_pucker_tail_progress_for_close_progress(progress)
                radial_config = dismiss_radial_pucker_shell_config(
                    self.final_shell_config,
                    pucker_progress,
                    client_id=_sidecar_id(self.client_id, "dismiss_radial_pucker"),
                    role=self.role,
                    z_index=self.z_index + 9,
                )
            if progress <= OPTICAL_MATERIALIZATION_SEAM_OVERLAP_START_PROGRESS:
                seam_config = dismiss_seam_latch_shell_config(
                    self.final_shell_config,
                    progress,
                    client_id=_sidecar_id(self.client_id, "dismiss_seam"),
                    role=self.role,
                    z_index=self.z_index + 10,
                )
        return OpticalTransitionFrame(
            progress=progress,
            main_config=main_config,
            seam_config=seam_config,
            radial_config=radial_config,
            complete=raw >= 1.0,
            body_ready=progress >= OPTICAL_MATERIALIZATION_BODY_READY,
        )


def dismiss_tail_frame(
    shell_config: dict,
    *,
    progress: float,
    client_id: str = "assistant.command",
    role: str = "assistant",
    z_index: int = 0,
) -> OpticalTransitionFrame:
    radial = dismiss_radial_pucker_shell_config(
        shell_config,
        progress,
        client_id=_sidecar_id(client_id, "dismiss_radial_pucker"),
        role=role,
        z_index=z_index + 9,
    )
    return OpticalTransitionFrame(
        progress=clamp01(progress),
        main_config=hidden_dismiss_main_shell_config(shell_config),
        radial_config=radial,
        complete=clamp01(progress) >= 1.0,
        body_ready=False,
    )
