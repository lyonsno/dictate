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
