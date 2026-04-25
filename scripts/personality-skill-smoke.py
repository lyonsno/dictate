#!/usr/bin/env python3
"""Smoke-test whether personality prompts trigger the README skill pointer.

This is an operator harness, not a unit test. It sends small one-turn probes to
an OpenAI-compatible command backend and checks whether the model's first move
is to read the personality README when the scenario calls for personality
authoring or selection.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import sys
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import urlparse

from spoke.command import CommandClient, _extract_xml_tool_calls, _personality_paths
from spoke.tool_dispatch import get_tool_schemas

_FALLBACK_COMMAND_MODEL = "qwen3p5-35B-A3B"
_MODEL_PREFERENCES_PATH = (
    Path.home() / "Library" / "Application Support" / "Spoke" / "model_preferences.json"
)


@dataclass(frozen=True)
class Scenario:
    id: str
    prompt: str
    expect_readme: bool
    context: tuple[dict[str, str], ...] = field(default_factory=tuple)
    note: str = ""


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class SmokeResult:
    scenario_id: str
    expected_readme: bool
    saw_readme: bool
    passed: bool
    first_tool_name: str | None
    first_tool_path: str | None
    note: str = ""


DEFAULT_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="create_load_after_technical_context",
        context=(
            {
                "role": "user",
                "content": (
                    "The Qwen KV cache reuse still feels suspicious around the "
                    "rewind boundary; we should reason about prefix identity "
                    "before touching the scheduler."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "Agreed. The cache contract needs a stable prefix witness "
                    "before the scheduler can safely share that state."
                ),
            },
        ),
        prompt=(
            "Make a calmer operator personality for long debugging sessions "
            "and load it."
        ),
        expect_readme=True,
        note="Personality request after unrelated technical context.",
    ),
    Scenario(
        id="switch_existing_personality",
        prompt="Switch the operator register to voight-kampff.md.",
        expect_readme=True,
        note="Selection-only request should still load the packet first.",
    ),
    Scenario(
        id="reset_personality_default",
        prompt="Reset the active operator personality back to the default.",
        expect_readme=True,
        note="Reset is selector work.",
    ),
    Scenario(
        id="technical_register_discussion_no_personality_work",
        context=(
            {
                "role": "user",
                "content": (
                    "Can we compare register allocation pressure against the "
                    "cache-line story before changing the hot loop?"
                ),
            },
        ),
        prompt=(
            "Let's stay on the compiler angle: why would the spill pattern "
            "change when the live range gets shorter?"
        ),
        expect_readme=False,
        note="Technical use of register language, no operator-personality work.",
    ),
)


def _json_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _extract_structured_tool_call(message: dict[str, Any]) -> ToolCall | None:
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return None
    first = tool_calls[0]
    if not isinstance(first, dict):
        return None
    function = first.get("function")
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return None
    return ToolCall(name=name, arguments=_json_arguments(function.get("arguments")))


def _extract_name_arguments_xml(content: str) -> ToolCall | None:
    import re

    match = re.search(
        r"<tool_call>\s*<name>(?P<name>[^<]+)</name>\s*"
        r"<arguments>(?P<args>.*?)</arguments>\s*</tool_call>",
        content,
        re.DOTALL,
    )
    if not match:
        return None
    return ToolCall(
        name=match.group("name").strip(),
        arguments=_json_arguments(match.group("args").strip()),
    )


def _extract_function_xml(content: str) -> ToolCall | None:
    parsed = _extract_xml_tool_calls(content)
    if not parsed:
        return None
    _, tool_calls = parsed
    if not tool_calls:
        return None
    first = tool_calls[0]
    function = first.get("function", {})
    name = function.get("name")
    if not isinstance(name, str) or not name:
        return None
    return ToolCall(name=name, arguments=_json_arguments(function.get("arguments")))


def extract_first_tool_call(response: dict[str, Any]) -> ToolCall | None:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return None
    message = first_choice.get("message") or {}
    if not isinstance(message, dict):
        return None

    structured = _extract_structured_tool_call(message)
    if structured:
        return structured

    content = message.get("content")
    if not isinstance(content, str):
        return None
    return _extract_function_xml(content) or _extract_name_arguments_xml(content)


def _same_path(left: str | None, right: str) -> bool:
    if not left:
        return False
    return os.path.abspath(os.path.expanduser(left)) == os.path.abspath(
        os.path.expanduser(right)
    )


def assess_response(
    scenario: Scenario,
    response: dict[str, Any],
    readme_path: str,
) -> SmokeResult:
    first_call = extract_first_tool_call(response)
    first_tool_name = first_call.name if first_call else None
    first_tool_path = None
    if first_call:
        raw_path = first_call.arguments.get("file_path")
        first_tool_path = raw_path if isinstance(raw_path, str) else None
    saw_readme = first_tool_name == "read_file" and _same_path(first_tool_path, readme_path)
    passed = saw_readme if scenario.expect_readme else not saw_readme
    return SmokeResult(
        scenario_id=scenario.id,
        expected_readme=scenario.expect_readme,
        saw_readme=saw_readme,
        passed=passed,
        first_tool_name=first_tool_name,
        first_tool_path=first_tool_path,
        note=scenario.note,
    )


def _chat_completions_url(base_url: str) -> str:
    raw_url = base_url.rstrip("/")
    parsed = urlparse(raw_url)
    path = parsed.path.rstrip("/")
    has_version = any(
        segment.startswith("v") and segment[1:].replace("beta", "").isdigit()
        for segment in path.split("/")
        if segment
    )
    suffix = "chat/completions" if has_version else "v1/chat/completions"
    return f"{raw_url}/{suffix}"


def _persisted_command_model(preferences_path: Path = _MODEL_PREFERENCES_PATH) -> str | None:
    try:
        payload = json.loads(preferences_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    model = payload.get("command_model")
    return model.strip() if isinstance(model, str) and model.strip() else None


def resolve_model(
    explicit_model: str | None,
    *,
    preferences_path: Path = _MODEL_PREFERENCES_PATH,
) -> str:
    if explicit_model and explicit_model.strip():
        return explicit_model.strip()
    env_model = os.environ.get("SPOKE_COMMAND_MODEL", "").strip()
    if env_model:
        return env_model
    return _persisted_command_model(preferences_path) or _FALLBACK_COMMAND_MODEL


def build_messages(scenario: Scenario, *, base_url: str, model: str) -> list[dict[str, str]]:
    client = CommandClient(
        base_url=base_url,
        model=model,
        history_path=None,
    )
    messages = client._build_messages(scenario.prompt)
    if not scenario.context:
        return messages
    return [messages[0], *scenario.context, messages[-1]]


def build_payload(
    scenario: Scenario,
    *,
    base_url: str,
    model: str,
    max_tokens: int,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": build_messages(scenario, base_url=base_url, model=model),
        "tools": get_tool_schemas(),
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
    }


def call_backend(
    scenario: Scenario,
    *,
    base_url: str,
    model: str,
    timeout: int,
    max_tokens: int,
) -> dict[str, Any]:
    payload = json.dumps(
        build_payload(
            scenario,
            base_url=base_url,
            model=model,
            max_tokens=max_tokens,
        )
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("SPOKE_COMMAND_API_KEY") or os.environ.get(
        "OMLX_SERVER_API_KEY",
        "",
    )
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        _chat_completions_url(base_url),
        data=payload,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _selected_scenarios(ids: list[str]) -> list[Scenario]:
    if not ids:
        return list(DEFAULT_SCENARIOS)
    by_id = {scenario.id: scenario for scenario in DEFAULT_SCENARIOS}
    missing = [scenario_id for scenario_id in ids if scenario_id not in by_id]
    if missing:
        raise SystemExit(f"Unknown scenario id(s): {', '.join(missing)}")
    return [by_id[scenario_id] for scenario_id in ids]


def _print_text_result(result: SmokeResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    expected = "README" if result.expected_readme else "no README"
    actual = (
        f"{result.first_tool_name}({result.first_tool_path})"
        if result.first_tool_name
        else "no tool call"
    )
    print(f"{status} {result.scenario_id}: expected {expected}; first move {actual}")
    if result.note:
        print(f"  {result.note}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SPOKE_COMMAND_URL", "http://localhost:8090"),
        help="OpenAI-compatible assistant base URL",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Assistant model id. Defaults to SPOKE_COMMAND_MODEL, then Spoke's "
            "persisted command_model, then a small static fallback."
        ),
    )
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--list", action="store_true", help="List scenario ids and exit")
    parser.add_argument("--json", action="store_true", help="Emit JSON results")
    args = parser.parse_args(argv)

    if args.list:
        for scenario in DEFAULT_SCENARIOS:
            expectation = "README" if scenario.expect_readme else "no README"
            print(f"{scenario.id}\t{expectation}\t{scenario.note}")
        return 0

    model = resolve_model(args.model)
    readme_path = str(_personality_paths()[3])
    results: list[SmokeResult] = []
    for scenario in _selected_scenarios(args.scenario):
        try:
            response = call_backend(
                scenario,
                base_url=args.base_url,
                model=model,
                timeout=args.timeout,
                max_tokens=args.max_tokens,
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            results.append(
                SmokeResult(
                    scenario_id=scenario.id,
                    expected_readme=scenario.expect_readme,
                    saw_readme=False,
                    passed=False,
                    first_tool_name=None,
                    first_tool_path=None,
                    note=f"backend error: {exc}",
                )
            )
            continue
        results.append(assess_response(scenario, response, readme_path))

    if args.json:
        print(json.dumps([result.__dict__ for result in results], indent=2))
    else:
        for result in results:
            _print_text_result(result)
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
