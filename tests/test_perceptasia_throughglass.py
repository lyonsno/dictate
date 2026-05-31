from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from spoke.optical_field import OpticalFieldBounds


def _connection_refused(*_args, **_kwargs):
    raise OSError("connection refused")


def test_manifest_defaults_to_current_local_perceptasia_provider(mock_pyobjc, monkeypatch):
    module = importlib.import_module("spoke.perceptasia_throughglass")

    monkeypatch.delenv("SPOKE_PERCEPTASIA_THROUGHGLASS_URL", raising=False)
    monkeypatch.setattr(module.urllib.request, "urlopen", _connection_refused)
    manifest = module.PerceptasiaThroughglassManifest.from_env()

    assert manifest.schema == "spoke.perceptasia-throughglass.provider.v0"
    assert manifest.url == "http://localhost:8742"
    assert manifest.scene_url == "http://localhost:8742/scene.json"
    assert manifest.selection_path.endswith(".local/state/perceptasia/selection.json")


def test_manifest_env_override_is_provider_contract_not_window_lifecycle(mock_pyobjc, monkeypatch):
    module = importlib.import_module("spoke.perceptasia_throughglass")

    monkeypatch.setenv("SPOKE_PERCEPTASIA_THROUGHGLASS_URL", "http://localhost:9999/")
    monkeypatch.setattr(module.urllib.request, "urlopen", _connection_refused)
    manifest = module.PerceptasiaThroughglassManifest.from_env()

    assert manifest.url == "http://localhost:9999"
    assert manifest.scene_url == "http://localhost:9999/scene.json"


def test_manifest_discovers_live_local_provider_when_requested_port_is_dead(mock_pyobjc, monkeypatch):
    module = importlib.import_module("spoke.perceptasia_throughglass")
    monkeypatch.setenv("SPOKE_PERCEPTASIA_THROUGHGLASS_URL", "http://localhost:8742")
    monkeypatch.setenv("SPOKE_PERCEPTASIA_THROUGHGLASS_DISCOVERY_PORTS", "8753")

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout=None):
        if request.full_url == "http://localhost:8753":
            return _Response()
        raise OSError("connection refused")

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    manifest = module.PerceptasiaThroughglassManifest.from_env()

    assert manifest.url == "http://localhost:8753"
    assert manifest.scene_url == "http://localhost:8753/scene.json"


def test_manifest_skips_non_perceptasia_directory_listing(mock_pyobjc, monkeypatch):
    module = importlib.import_module("spoke.perceptasia_throughglass")
    monkeypatch.setenv("SPOKE_PERCEPTASIA_THROUGHGLASS_URL", "http://localhost:8742")
    monkeypatch.setenv("SPOKE_PERCEPTASIA_THROUGHGLASS_DISCOVERY_PORTS", "8797,8798")

    class _Response:
        status = 200

        def __init__(self, body: bytes):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return self._body

    def fake_urlopen(request, timeout=None):
        if request.full_url == "http://localhost:8797":
            return _Response(b"<title>Directory listing for /</title>")
        if request.full_url == "http://localhost:8798":
            return _Response(b"<title>Perceptasia 3D</title>")
        raise OSError("connection refused")

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    manifest = module.PerceptasiaThroughglassManifest.from_env()

    assert manifest.url == "http://localhost:8798"


def test_throughglass_request_is_independent_sibling_without_progress_custody(mock_pyobjc):
    from spoke.perceptasia_throughglass import build_perceptasia_optical_request

    bounds = OpticalFieldBounds(100.0, 80.0, 900.0, 520.0)
    request = build_perceptasia_optical_request(bounds, state="rest")

    assert request.caller_id == "perceptasia.throughglass"
    assert request.role == "hud"
    assert request.visibility_scope == "independent"
    assert request.layout_recipe == "perceptasia-throughglass"
    assert request.profile.base == "agent_card"
    assert request.presentation.layer == "hud"
    assert request.presentation.order == 42


def test_throughglass_compiles_to_public_optical_field_shell_config(mock_pyobjc):
    from spoke.perceptasia_throughglass import compile_perceptasia_shell_config

    bounds = OpticalFieldBounds(100.0, 80.0, 900.0, 520.0)
    config = compile_perceptasia_shell_config(bounds, state="materialize")

    assert config["client_id"] == "perceptasia.throughglass"
    assert config["role"] == "hud"
    assert config["presentation_layer"] == "hud"
    assert config["presentation_order"] == 42
    assert config["optical_field"]["layout_recipe"] == "perceptasia-throughglass"
    assert config["optical_field"]["state"] == "materialize"
    assert "progress" not in config["optical_field"]
    assert "phase" not in config["optical_field"]
    assert config["gpu_material_enabled"] == pytest.approx(1.0)


def test_throughglass_real_pyobjc_import_accepts_private_helpers():
    if importlib.util.find_spec("objc") is None or importlib.util.find_spec("AppKit") is None:
        pytest.skip("PyObjC/AppKit unavailable")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from WebKit import WKWebView; "
            "from spoke.perceptasia_throughglass import PerceptasiaThroughglassGraft; "
            "print(PerceptasiaThroughglassGraft.__name__)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "PerceptasiaThroughglassGraft" in result.stdout


def test_throughglass_panel_is_click_through_until_input_mode(mock_pyobjc, monkeypatch):
    sys.modules.pop("spoke.perceptasia_throughglass", None)
    module = importlib.import_module("spoke.perceptasia_throughglass")

    panel = MagicMock()
    panel.contentView.return_value = MagicMock()
    module.NSPanel.alloc.return_value.initWithContentRect_styleMask_backing_defer_.return_value = panel
    module.NSScreen.mainScreen.return_value.visibleFrame.return_value = SimpleNamespace(
        origin=SimpleNamespace(x=0.0, y=0.0),
        size=SimpleNamespace(width=1440.0, height=900.0),
    )
    monkeypatch.setattr(module, "_make_content_view", lambda url, width, height: MagicMock())

    graft = module.PerceptasiaThroughglassGraft.alloc().initWithCompositorRegistry_(None)
    graft.setup()

    panel.setIgnoresMouseEvents_.assert_called_once_with(True)
