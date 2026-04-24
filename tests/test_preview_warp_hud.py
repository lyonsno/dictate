import importlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock


def _import_preview_warp_hud(mock_pyobjc):
    appkit = sys.modules["AppKit"]
    appkit.NSButton = MagicMock()
    appkit.NSSlider = MagicMock()
    sys.modules.pop("spoke.preview_warp_hud", None)
    mod = importlib.import_module("spoke.preview_warp_hud")
    return mod


def test_init_reapplies_saved_preview_tuning_only(mock_pyobjc, tmp_path):
    mod = _import_preview_warp_hud(mock_pyobjc)
    original_prefs_path = mod._PREFS_PATH
    prefs_path = tmp_path / "preview_warp_hud.json"
    prefs_path.write_text(
        json.dumps(
            {
                "visible": False,
                "tuning": {
                    "core_magnification": 2.46,
                    "x_squeeze": 2.45,
                    "y_squeeze": 0.98,
                    "inflation_x_radii": 1.09,
                    "inflation_y_radii": 1.40,
                    "bleed_zone_frac": 1.33,
                    "exterior_mix_width_points": 9.9,
                    "ring_amplitude_points": 37.4,
                },
            }
        )
    )
    mod._PREFS_PATH = prefs_path
    try:
        overlay = MagicMock()

        mod.PreviewWarpHUD.alloc().initWithOverlay_(overlay)

        overlay.update_preview_warp_tuning.assert_called_once_with(
            core_magnification=2.46,
            x_squeeze=2.45,
            y_squeeze=0.98,
            inflation_x_radii=1.09,
            inflation_y_radii=1.40,
            bleed_zone_frac=1.33,
            exterior_mix_width_points=9.9,
            ring_amplitude_points=37.4,
        )
    finally:
        mod._PREFS_PATH = original_prefs_path
        sys.modules.pop("spoke.preview_warp_hud", None)


def test_save_prefs_persists_preview_tuning_snapshot(mock_pyobjc, tmp_path):
    mod = _import_preview_warp_hud(mock_pyobjc)
    original_prefs_path = mod._PREFS_PATH
    prefs_path = tmp_path / "preview_warp_hud.json"
    mod._PREFS_PATH = prefs_path
    try:
        overlay = MagicMock()
        overlay.preview_warp_tuning_snapshot.return_value = {
            "core_magnification": 2.46,
            "x_squeeze": 2.45,
            "y_squeeze": 0.98,
            "inflation_x_radii": 1.09,
            "inflation_y_radii": 1.40,
            "bleed_zone_frac": 1.33,
            "exterior_mix_width_points": 9.9,
            "ring_amplitude_points": 37.4,
        }
        hud = mod.PreviewWarpHUD.alloc().initWithOverlay_(overlay)
        hud._visible = True
        hud._panel = MagicMock()
        hud._panel.frame.return_value = SimpleNamespace(
            origin=SimpleNamespace(x=1312.0, y=527.0)
        )

        hud._save_prefs()

        payload = json.loads(prefs_path.read_text())
        assert payload["visible"] is True
        assert payload["x"] == 1312.0
        assert payload["y"] == 527.0
        assert payload["tuning"] == {
            "core_magnification": 2.46,
            "x_squeeze": 2.45,
            "y_squeeze": 0.98,
            "inflation_x_radii": 1.09,
            "inflation_y_radii": 1.4,
            "bleed_zone_frac": 1.33,
            "exterior_mix_width_points": 9.9,
            "ring_amplitude_points": 37.4,
        }
    finally:
        mod._PREFS_PATH = original_prefs_path
        sys.modules.pop("spoke.preview_warp_hud", None)
