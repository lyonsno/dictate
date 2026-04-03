"""Geometry contracts for the screen-edge glow architecture."""

import importlib
import sys
from types import SimpleNamespace

import pytest

_APPLE_MASK_NOTCH_WIDTHS_14 = [
    386, 380, 376, 376, 374, 372, 372, 372, 372, 372, 372, 370, 370, 370,
    370, 370, 370, 370, 370, 370, 370, 370, 370, 370, 370, 370, 370, 370,
    370, 370, 370, 370, 370, 370, 370, 370, 370, 370, 370, 370, 370, 370,
    370, 370, 370, 370, 370, 370, 370, 368, 368, 366, 366, 364, 364, 362,
    360, 358, 356, 354, 352, 348, 344, 336,
]

_APPLE_MASK_NOTCH_WIDTHS_16 = [
    386, 380, 378, 376, 374, 372, 372, 372, 372, 372, 372, 372, 372, 372,
    372, 372, 372, 372, 372, 372, 372, 372, 372, 372, 372, 372, 372, 372,
    372, 372, 372, 372, 372, 372, 372, 372, 372, 372, 372, 372, 372, 372,
    372, 370, 370, 370, 370, 370, 370, 368, 368, 368, 366, 366, 364, 362,
    360, 360, 356, 354, 352, 348, 344, 336,
]


def _rect(x: float, y: float, width: float, height: float):
    return SimpleNamespace(
        origin=SimpleNamespace(x=x, y=y),
        size=SimpleNamespace(width=width, height=height),
    )


def _center_gap_width(field, row: int) -> int:
    """Measure the contiguous notch gap centered on the display midpoint."""
    width = field.shape[1]
    center = width // 2
    start = center
    while start > 0 and field[row, start - 1] >= 0.0:
        start -= 1
    end = center
    while end + 1 < width and field[row, end + 1] >= 0.0:
        end += 1
    return end - start + 1


def _notch_profile_widths(field, height: int) -> list[int]:
    return [_center_gap_width(field, row) for row in range(height)]


def test_continuous_glow_pass_specs_use_distance_field_layers(mock_pyobjc):
    """The additive glow should be composed from continuous distance-field passes, not edge/corner tiles."""
    sys.modules.pop("spoke.glow", None)
    mod = importlib.import_module("spoke.glow")
    try:
        specs = mod._continuous_glow_pass_specs()

        assert [spec["name"] for spec in specs] == ["core", "tight_bloom", "wide_bloom"]
        assert all(spec["path_kind"] == "distance_field" for spec in specs)
        assert specs[0]["falloff"] < specs[1]["falloff"] < specs[2]["falloff"]
        assert specs[0]["power"] <= specs[1]["power"] <= specs[2]["power"]
        assert not any("corner" in spec["name"] or "left" in spec["name"] for spec in specs)
    finally:
        sys.modules.pop("spoke.glow", None)


def test_continuous_vignette_pass_specs_use_same_distance_field_architecture(mock_pyobjc):
    """The subtractive vignette should use the same continuous distance-field architecture."""
    sys.modules.pop("spoke.glow", None)
    mod = importlib.import_module("spoke.glow")
    try:
        specs = mod._continuous_vignette_pass_specs()

        assert [spec["name"] for spec in specs] == ["core", "mid", "tail"]
        assert all(spec["path_kind"] == "distance_field" for spec in specs)
        assert specs[0]["falloff"] < specs[1]["falloff"] < specs[2]["falloff"]
        assert specs[0]["power"] <= specs[1]["power"] <= specs[2]["power"]
        assert not any("top" in spec["name"] or "bottom" in spec["name"] for spec in specs)
    finally:
        sys.modules.pop("spoke.glow", None)


def test_display_shape_geometry_derives_notch_from_auxiliary_areas(mock_pyobjc):
    """Live NSScreen auxiliary areas should define the notch cutout instead of a guessed hardcoded width."""
    sys.modules.pop("spoke.glow", None)
    mod = importlib.import_module("spoke.glow")
    try:
        screen = SimpleNamespace(
            auxiliaryTopLeftArea=lambda: _rect(0.0, 1085.0, 767.0, 32.0),
            auxiliaryTopRightArea=lambda: _rect(961.0, 1085.0, 767.0, 32.0),
        )

        geometry = mod._display_shape_geometry(screen, 1728.0, 1117.0, 2.0)

        assert geometry["pixel_width"] == 3456
        assert geometry["pixel_height"] == 2234
        assert geometry["notch"] is not None
        assert geometry["notch"]["x"] == pytest.approx(1534.0)
        assert geometry["notch"]["width"] == pytest.approx(388.0)
        assert geometry["notch"]["height"] == pytest.approx(64.0)
    finally:
        sys.modules.pop("spoke.glow", None)


def test_display_shape_geometry_selects_14_inch_corner_radii(mock_pyobjc):
    """A 14" MacBook Pro (3024×1964 native) should get its own corner radii from the lookup table."""
    sys.modules.pop("spoke.glow", None)
    mod = importlib.import_module("spoke.glow")
    try:
        screen = SimpleNamespace(
            auxiliaryTopLeftArea=lambda: _rect(0.0, 950.0, 660.0, 32.0),
            auxiliaryTopRightArea=lambda: _rect(852.0, 950.0, 660.0, 32.0),
        )

        geometry = mod._display_shape_geometry(screen, 1512.0, 982.0, 2.0)

        assert geometry["pixel_width"] == 3024
        assert geometry["pixel_height"] == 1964
        expected_top, expected_bot = mod._DISPLAY_CORNER_RADII[(3024, 1964)]
        assert geometry["top_radius"] == pytest.approx(expected_top * 2.0)
        assert geometry["bottom_radius"] == pytest.approx(expected_bot * 2.0)
        assert geometry["notch"] is not None
        assert geometry["notch"]["width"] == pytest.approx(384.0)
        assert geometry["notch"]["height"] == pytest.approx(64.0)
    finally:
        sys.modules.pop("spoke.glow", None)


def test_display_shape_geometry_selects_16_inch_corner_radii(mock_pyobjc):
    """A 16" MacBook Pro (3456×2234 native) should get its own corner radii from the lookup table."""
    sys.modules.pop("spoke.glow", None)
    mod = importlib.import_module("spoke.glow")
    try:
        screen = SimpleNamespace(
            auxiliaryTopLeftArea=lambda: _rect(0.0, 1085.0, 767.0, 32.0),
            auxiliaryTopRightArea=lambda: _rect(961.0, 1085.0, 767.0, 32.0),
        )

        geometry = mod._display_shape_geometry(screen, 1728.0, 1117.0, 2.0)

        expected_top, expected_bot = mod._DISPLAY_CORNER_RADII[(3456, 2234)]
        assert geometry["top_radius"] == pytest.approx(expected_top * 2.0)
        assert geometry["bottom_radius"] == pytest.approx(expected_bot * 2.0)
    finally:
        sys.modules.pop("spoke.glow", None)


def test_display_shape_geometry_keeps_14_inch_notch_straighter_than_16(mock_pyobjc):
    """The 14" notch should match the exact Apple mask row profile instead of a visually tuned approximation."""
    sys.modules.pop("spoke.glow", None)
    mod = importlib.import_module("spoke.glow")
    try:
        screen_14 = SimpleNamespace(
            auxiliaryTopLeftArea=lambda: _rect(0.0, 950.0, 660.0, 32.0),
            auxiliaryTopRightArea=lambda: _rect(852.0, 950.0, 660.0, 32.0),
        )

        geometry_14 = mod._display_shape_geometry(screen_14, 1512.0, 982.0, 2.0)
        assert geometry_14["notch"] is not None
        field_14 = mod._display_signed_distance_field(geometry_14)

        assert _notch_profile_widths(field_14, 64) == _APPLE_MASK_NOTCH_WIDTHS_14
    finally:
        sys.modules.pop("spoke.glow", None)


def test_display_shape_geometry_matches_16_inch_apple_mask_profile(mock_pyobjc):
    """The 16" notch should also follow the exact Apple mask profile rather than the legacy rounded cutout."""
    sys.modules.pop("spoke.glow", None)
    mod = importlib.import_module("spoke.glow")
    try:
        screen_16 = SimpleNamespace(
            auxiliaryTopLeftArea=lambda: _rect(0.0, 1085.0, 767.0, 32.0),
            auxiliaryTopRightArea=lambda: _rect(961.0, 1085.0, 767.0, 32.0),
        )

        geometry_16 = mod._display_shape_geometry(screen_16, 1728.0, 1117.0, 2.0)
        assert geometry_16["notch"] is not None
        field_16 = mod._display_signed_distance_field(geometry_16)

        assert _notch_profile_widths(field_16, 64) == _APPLE_MASK_NOTCH_WIDTHS_16
    finally:
        sys.modules.pop("spoke.glow", None)


def test_display_shape_geometry_falls_back_for_unknown_display(mock_pyobjc):
    """An unrecognized display should get the default corner radii."""
    sys.modules.pop("spoke.glow", None)
    mod = importlib.import_module("spoke.glow")
    try:
        screen = SimpleNamespace()

        geometry = mod._display_shape_geometry(screen, 1920.0, 1080.0, 2.0)

        assert geometry["pixel_width"] == 3840
        assert geometry["pixel_height"] == 2160
        assert geometry["top_radius"] == pytest.approx(mod._CORNER_RADIUS_TOP_DEFAULT * 2.0)
        assert geometry["bottom_radius"] == pytest.approx(mod._CORNER_RADIUS_BOTTOM_DEFAULT * 2.0)
        assert geometry["notch"] is None
    finally:
        sys.modules.pop("spoke.glow", None)
