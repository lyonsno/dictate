from __future__ import annotations

import importlib.util
import json
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


def _import_migration_module():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "migrate-personality-smoke-grapheus-headers.py"
    )
    spec = importlib.util.spec_from_file_location(
        "migrate_personality_smoke_grapheus_headers",
        script_path,
    )
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


def test_call_backend_labels_grapheus_requests_with_smoke_pathway(monkeypatch):
    mod = _import_smoke_module()
    seen = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"choices": [{"message": {"content": "ok"}}]}'

    def fake_urlopen(req, timeout):
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)

    scenario = mod.Scenario(
        id="create_load_after_technical_context",
        prompt="Make a calmer operator personality for long debugging sessions and load it.",
        expect_readme=True,
    )
    mod.call_backend(
        scenario,
        base_url="http://localhost:8093",
        model="Qwen3.6-35B-A3B-oQ8",
        timeout=7,
        max_tokens=64,
    )

    assert seen["headers"]["X-spoke-pathway"] == "personality-skill-smoke"
    assert seen["headers"]["X-spoke-utterance-id"] == "create_load_after_technical_context"
    assert seen["headers"]["X-spoke-turn"] == "0"
    assert seen["headers"]["X-spoke-smoke-harness"] == "personality-skill-smoke"
    assert seen["body"]["model"] == "Qwen3.6-35B-A3B-oQ8"
    assert seen["timeout"] == 7


def test_grapheus_log_migration_labels_legacy_personality_smoke_entries(tmp_path):
    mod = _import_migration_module()
    log_path = tmp_path / "grapheus-2026-04-25.jsonl"
    legacy_entry = {
        "timestamp": "2026-04-25T19:20:47.186934+00:00",
        "request": {
            "messages": [
                {"role": "system", "content": "system"},
                {
                    "role": "user",
                    "content": (
                        "Make a calmer operator personality for long debugging "
                        "sessions and load it."
                    ),
                },
            ]
        },
        "request_headers": {"Content-Type": "application/json"},
        "spoke_metadata": None,
        "summary": {
            "user_utterance": (
                "Make a calmer operator personality for long debugging "
                "sessions and load it."
            ),
            "response_length_chars": 0,
            "has_thinking": True,
            "tool_call_count": 1,
        },
    }
    unrelated_entry = {
        "timestamp": "2026-04-25T19:20:55.633484+00:00",
        "request_headers": {"Content-Type": "application/json"},
        "spoke_metadata": None,
        "summary": {
            "user_utterance": (
                "Let's stay on the compiler angle: why would the spill pattern "
                "change when the live range gets shorter?"
            ),
            "response_length_chars": 1303,
        },
    }
    log_path.write_text(
        json.dumps(legacy_entry) + "\n" + json.dumps(unrelated_entry) + "\n",
        encoding="utf-8",
    )

    result = mod.migrate_log(log_path)

    assert result.changed == 1
    migrated, untouched = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert migrated["spoke_metadata"] == {
        "pathway": "personality-skill-smoke",
        "utterance_id": "create_load_after_technical_context",
        "turn": "0",
        "smoke_harness": "personality-skill-smoke",
    }
    assert migrated["request_headers"]["X-Spoke-Pathway"] == "personality-skill-smoke"
    assert untouched["spoke_metadata"] is None
