from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _import_smoke_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "personality-skill-smoke.py"
    spec = importlib.util.spec_from_file_location("personality_skill_smoke", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_scenarios_include_contextual_personality_and_negative_controls():
    mod = _import_smoke_module()

    scenarios = {scenario.id: scenario for scenario in mod.DEFAULT_SCENARIOS}

    assert scenarios["create_load_after_technical_context"].expect_readme is True
    assert "KV cache" in scenarios["create_load_after_technical_context"].context[0]["content"]
    assert "load it" in scenarios["create_load_after_technical_context"].prompt
    assert scenarios["technical_register_discussion_no_personality_work"].expect_readme is False
    assert "operator personality" not in scenarios[
        "technical_register_discussion_no_personality_work"
    ].prompt.lower()
    assert scenarios["implicit_make_this_the_default_vibe"].expect_readme is True
    assert "default vibe" in scenarios["implicit_make_this_the_default_vibe"].prompt
    assert scenarios["path_dependent_direct_edit_then_activate"].expect_readme is True
    assert scenarios["wallace_style_without_named_command_colon"].expect_readme is True
    assert scenarios["draft_inline_do_not_install"].expect_readme is False
    assert "don't install" in scenarios["draft_inline_do_not_install"].prompt


def test_extract_first_tool_call_accepts_structured_and_xml_tool_calls():
    mod = _import_smoke_module()

    structured = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "read_file",
                                "arguments": '{"file_path": "/tmp/README.md"}',
                            }
                        }
                    ]
                }
            }
        ]
    }
    xml = {
        "choices": [
            {
                "message": {
                    "content": (
                        "<tool_call><name>read_file</name>"
                        '<arguments>{"file_path": "/tmp/README.md"}</arguments></tool_call>'
                    )
                }
            }
        ]
    }

    assert mod.extract_first_tool_call(structured).name == "read_file"
    assert mod.extract_first_tool_call(xml).arguments == {"file_path": "/tmp/README.md"}


def test_assess_response_checks_for_expected_readme_call():
    mod = _import_smoke_module()
    readme_path = "/Users/example/.config/spoke/personalities/README.md"
    scenario = mod.Scenario(
        id="load",
        prompt="Make a DFW-ish personality and load it.",
        expect_readme=True,
    )
    response = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "read_file",
                                "arguments": f'{{"file_path": "{readme_path}"}}',
                            }
                        }
                    ]
                }
            }
        ]
    }

    result = mod.assess_response(scenario, response, readme_path)

    assert result.passed is True
    assert result.first_tool_name == "read_file"
    assert result.first_tool_path == readme_path


def test_resolve_model_prefers_explicit_env_then_persisted_preference(tmp_path, monkeypatch):
    mod = _import_smoke_module()
    prefs_path = tmp_path / "model_preferences.json"
    prefs_path.write_text(
        '{"command_model": "Qwen3.6-35B-A3B-oQ8"}',
        encoding="utf-8",
    )

    monkeypatch.delenv("SPOKE_COMMAND_MODEL", raising=False)
    assert mod.resolve_model(None, preferences_path=prefs_path) == "Qwen3.6-35B-A3B-oQ8"

    monkeypatch.setenv("SPOKE_COMMAND_MODEL", "env-model")
    assert mod.resolve_model(None, preferences_path=prefs_path) == "env-model"
    assert mod.resolve_model("explicit-model", preferences_path=prefs_path) == "explicit-model"
