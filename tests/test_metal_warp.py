"""Contract tests for multi-shell warp composition planning."""

import importlib
import sys


class TestMetalWarpCompositionPlanning:
    def test_single_shell_config_stays_on_direct_path(self, mock_pyobjc):
        sys.modules.pop("spoke.metal_warp", None)
        mod = importlib.import_module("spoke.metal_warp")

        assert mod._requires_sequential_shell_composition(
            [{"content_width_points": 600.0, "content_height_points": 100.0}]
        ) is False

    def test_multiple_shell_configs_require_composition_chain(self, mock_pyobjc):
        sys.modules.pop("spoke.metal_warp", None)
        mod = importlib.import_module("spoke.metal_warp")

        assert mod._requires_sequential_shell_composition(
            [
                {"content_width_points": 600.0, "content_height_points": 100.0},
                {"content_width_points": 600.0, "content_height_points": 180.0},
            ]
        ) is True

    def test_assistant_overlap_debug_witness_only_arms_for_overlap_assistant_shell(
        self, mock_pyobjc, monkeypatch
    ):
        monkeypatch.setenv("SPOKE_ASSISTANT_OVERLAP_DEBUG_WITNESS", "1")
        sys.modules.pop("spoke.metal_warp", None)
        mod = importlib.import_module("spoke.metal_warp")

        assert mod._assistant_overlap_debug_witness(
            {"overlay_kind": "assistant"}, overlap_active=True
        ) == (18.0, 0.92, 1.0, 0.22, 0.08)
        assert mod._assistant_overlap_debug_witness(
            {"overlay_kind": "assistant"}, overlap_active=False
        ) == (0.0, 0.0, 0.0, 0.0, 0.0)
        assert mod._assistant_overlap_debug_witness(
            {"overlay_kind": "preview"}, overlap_active=True
        ) == (0.0, 0.0, 0.0, 0.0, 0.0)
