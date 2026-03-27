"""Contract tests for overlay timing constants."""

import importlib
import sys


class TestOverlayTiming:
    """Keep the overlay tuned to the current fast-handoff UX."""

    def test_fade_out_is_shortened_for_fast_finalization(self, mock_pyobjc):
        """Fade-out should get out of the way now that final injection lands quickly."""
        sys.modules.pop("spoke.overlay", None)
        mod = importlib.import_module("spoke.overlay")
        try:
            assert mod._FADE_OUT_S == 0.18
        finally:
            sys.modules.pop("spoke.overlay", None)
