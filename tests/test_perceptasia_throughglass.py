from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

from spoke.optical_field import OpticalFieldBounds


def test_manifest_defaults_to_current_local_perceptasia_provider(mock_pyobjc, monkeypatch):
    from spoke.perceptasia_throughglass import PerceptasiaThroughglassManifest

    monkeypatch.delenv("SPOKE_PERCEPTASIA_THROUGHGLASS_URL", raising=False)
    manifest = PerceptasiaThroughglassManifest.from_env()

    assert manifest.schema == "spoke.perceptasia-throughglass.provider.v0"
    assert manifest.url == "http://localhost:8742"
    assert manifest.scene_url == "http://localhost:8742/scene.json"
    assert manifest.selection_path.endswith(".local/state/perceptasia/selection.json")


def test_manifest_env_override_is_provider_contract_not_window_lifecycle(mock_pyobjc, monkeypatch):
    from spoke.perceptasia_throughglass import PerceptasiaThroughglassManifest

    monkeypatch.setenv("SPOKE_PERCEPTASIA_THROUGHGLASS_URL", "http://localhost:9999/")
    manifest = PerceptasiaThroughglassManifest.from_env()

    assert manifest.url == "http://localhost:9999"
    assert manifest.scene_url == "http://localhost:9999/scene.json"


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
            "from spoke.perceptasia_throughglass import PerceptasiaThroughglassGraft; "
            "print(PerceptasiaThroughglassGraft.__name__)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "PerceptasiaThroughglassGraft" in result.stdout
