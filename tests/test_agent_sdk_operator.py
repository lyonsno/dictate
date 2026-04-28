"""Tests for SDK-backed operator agent sessions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class _DeferredThread:
    """Test thread that starts only when run_now() is called."""

    created: list["_DeferredThread"] = []

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        self.daemon = daemon
        self.started = False
        type(self).created.append(self)

    def start(self):
        self.started = True

    def run_now(self):
        self._target(*self._args, **self._kwargs)


class TestAgentSDKManager:
    def test_launch_tracks_provider_cwd_resume_and_result_identity(self, tmp_path):
        from spoke.agent_sdk_operator import AgentSDKManager, AgentSDKRunResult

        calls = []
        _DeferredThread.created = []

        def fake_runner(provider, prompt, cwd, resume_id, cancel_check):
            calls.append((provider, prompt, cwd, resume_id, cancel_check()))
            return AgentSDKRunResult(
                provider=provider,
                session_id="claude-session-123",
                final_response="Plan complete.",
            )

        manager = AgentSDKManager(
            sdk_runner=fake_runner,
            thread_factory=_DeferredThread,
        )

        launched = manager.launch(
            provider="claude",
            prompt="inspect the failing tests",
            cwd=str(tmp_path),
            resume_id="prior-session",
        )
        assert launched["id"] == "sdk-agent-claude-1"
        assert launched["provider"] == "claude"
        assert launched["state"] == "queued"
        assert launched["cwd"] == str(tmp_path)
        assert launched["resume_id"] == "prior-session"

        _DeferredThread.created[-1].run_now()

        result = manager.get_session(launched["id"])
        assert calls == [
            ("claude", "inspect the failing tests", str(tmp_path), "prior-session", False)
        ]
        assert result["state"] == "completed"
        assert result["provider_session_id"] == "claude-session-123"
        assert result["result"] == "Plan complete."
        assert result["result_preview"] == "Plan complete."

    def test_sdk_unavailable_is_visible_without_looking_like_terminal_failure(self):
        from spoke.agent_sdk_operator import (
            AgentSDKManager,
            AgentSDKUnavailable,
        )

        _DeferredThread.created = []

        def fake_runner(provider, prompt, cwd, resume_id, cancel_check):
            raise AgentSDKUnavailable("claude-agent-sdk is not installed")

        manager = AgentSDKManager(
            sdk_runner=fake_runner,
            thread_factory=_DeferredThread,
        )

        launched = manager.launch(
            provider="claude",
            prompt="make a patch",
            cwd="/tmp/project",
        )
        _DeferredThread.created[-1].run_now()

        result = manager.get_session(launched["id"])
        assert result["state"] == "failed"
        assert result["sdk_unavailable"] is True
        assert "claude-agent-sdk" in result["error"]
        assert result["result"] is None

    @pytest.mark.parametrize("provider", ["", "search", "gpt"])
    def test_rejects_unknown_providers(self, provider):
        from spoke.agent_sdk_operator import AgentSDKManager

        manager = AgentSDKManager(
            sdk_runner=MagicMock(),
            thread_factory=_DeferredThread,
        )

        with pytest.raises(ValueError, match="Unsupported SDK agent provider"):
            manager.launch(provider=provider, prompt="hello", cwd="/tmp/project")

    def test_rejects_empty_prompt(self):
        from spoke.agent_sdk_operator import AgentSDKManager

        manager = AgentSDKManager(
            sdk_runner=MagicMock(),
            thread_factory=_DeferredThread,
        )

        with pytest.raises(ValueError, match="prompt must be a non-empty string"):
            manager.launch(provider="codex", prompt="   ", cwd="/tmp/project")

    def test_cancelled_session_does_not_publish_result(self):
        from spoke.agent_sdk_operator import AgentSDKManager, AgentSDKRunResult

        _DeferredThread.created = []

        def fake_runner(provider, prompt, cwd, resume_id, cancel_check):
            assert cancel_check() is True
            return AgentSDKRunResult(
                provider=provider,
                session_id="codex-thread-123",
                final_response="Should be discarded",
            )

        manager = AgentSDKManager(
            sdk_runner=fake_runner,
            thread_factory=_DeferredThread,
        )

        launched = manager.launch(provider="codex", prompt="continue", cwd="/tmp/project")
        cancelled = manager.cancel(launched["id"])
        assert cancelled["state"] == "cancelling"

        _DeferredThread.created[-1].run_now()

        result = manager.get_session(launched["id"])
        assert result["state"] == "cancelled"
        assert result["result"] is None
        assert result["provider_session_id"] is None


class TestAgentSDKToolDispatch:
    def test_generic_tool_schemas_do_not_expose_raw_sdk_agent_controls(self):
        from spoke import tool_dispatch

        schemas = tool_dispatch.get_tool_schemas()
        names = {schema["function"]["name"] for schema in schemas}

        assert "launch_agent_session" not in names
        assert "list_agent_sessions" not in names
        assert "get_agent_session_result" not in names
        assert "cancel_agent_session" not in names

    def test_execute_tool_does_not_launch_sdk_sessions_from_generic_surface(self):
        from spoke import tool_dispatch

        fake_manager = MagicMock()
        result = tool_dispatch.execute_tool(
            "launch_agent_session",
            {
                "provider": "codex",
                "prompt": "make a plan",
                "cwd": "/tmp/project",
                "resume_id": "thread-1",
            },
            agent_sdk_manager=fake_manager,
        )

        assert json.loads(result) == {"error": "Unknown tool: launch_agent_session"}
        fake_manager.launch.assert_not_called()

    def test_operator_prompt_does_not_present_sdk_sessions_as_generic_tools(self):
        import spoke.command as command

        assert "launch_agent_session" not in command.COMMAND_SYSTEM_PROMPT
        assert "Claude Agent SDK" not in command.COMMAND_SYSTEM_PROMPT
        assert "Codex SDK" not in command.COMMAND_SYSTEM_PROMPT

    def test_dispatch_module_does_not_import_claude_or_codex_sdk_directly(self):
        module_path = Path(__file__).resolve().parents[1] / "spoke" / "tool_dispatch.py"
        text = module_path.read_text(encoding="utf-8")

        assert "claude_agent_sdk" not in text
        assert "codex_app_server" not in text


class TestAgentShellRouting:
    def test_active_agent_shell_routes_ordinary_input_to_selected_provider(self):
        from spoke.agent_shell import AgentShellState, route_agent_shell_input

        state = AgentShellState(
            active=True,
            provider="codex",
            spoke_session_id="sdk-agent-codex-1",
            provider_session_id="thread-abc",
            cwd="/tmp/project",
        )

        decision = route_agent_shell_input(
            "inspect the failing test and propose the smallest fix",
            state,
        )

        assert decision.kind == "provider_message"
        assert decision.provider == "codex"
        assert decision.spoke_session_id == "sdk-agent-codex-1"
        assert decision.provider_session_id == "thread-abc"
        assert decision.cwd == "/tmp/project"
        assert decision.text == "inspect the failing test and propose the smallest fix"

    @pytest.mark.parametrize(
        "utterance",
        [
            "epistaxis zetesis how fares the tyrant state",
            "zetesis is there incoherence between these lanes",
            "how fares the tyrant state",
        ],
    )
    def test_active_agent_shell_routes_epistaxis_verbs_away_from_provider(self, utterance):
        from spoke.agent_shell import AgentShellState, route_agent_shell_input

        state = AgentShellState(
            active=True,
            provider="claude",
            spoke_session_id="sdk-agent-claude-1",
            provider_session_id="session-xyz",
            cwd="/tmp/project",
        )

        decision = route_agent_shell_input(utterance, state)

        assert decision.kind == "epistaxis_verb"
        assert decision.provider is None
        assert decision.epistaxis_text == utterance

    def test_active_agent_shell_routes_provider_switch_as_mode_control(self):
        from spoke.agent_shell import AgentShellState, route_agent_shell_input

        state = AgentShellState(active=True, provider="claude", cwd="/tmp/project")

        decision = route_agent_shell_input("switch to codex", state)

        assert decision.kind == "mode_control"
        assert decision.control_action == "switch_provider"
        assert decision.provider == "codex"

    def test_inactive_agent_shell_leaves_input_for_normal_assistant(self):
        from spoke.agent_shell import AgentShellState, route_agent_shell_input

        state = AgentShellState(active=False, provider=None, cwd="/tmp/project")

        decision = route_agent_shell_input("inspect the failing test", state)

        assert decision.kind == "normal_assistant"
        assert decision.text == "inspect the failing test"


class TestAgentShellMenuState:
    def test_delegate_exposes_agent_shell_provider_menu_without_backend_replacement(
        self, monkeypatch
    ):
        import spoke.__main__ as main_module

        delegate = main_module.SpokeAppDelegate.__new__(main_module.SpokeAppDelegate)
        delegate._command_client = MagicMock()
        delegate._command_backend = "local"
        delegate._command_model_id = "qwen-test"
        delegate._command_model_options = [("qwen-test", "qwen-test", True)]
        delegate._command_server_unreachable = False
        delegate._agent_shell_provider = "codex"
        delegate._agent_sdk_manager = MagicMock()
        delegate._load_cloud_provider_preference = MagicMock(return_value="google")
        delegate._load_preference = MagicMock(return_value=None)
        delegate._select_model = MagicMock(return_value=[])
        delegate._sanitize_model_ids = MagicMock(side_effect=lambda a, b: (a, b))
        delegate._default_transcription_model = MagicMock(return_value="whisper-base")
        delegate._launch_target_menu_state = MagicMock(return_value=None)
        delegate._local_whisper_controls_available = MagicMock(return_value=False)
        delegate._tts_client = None
        delegate._tts_backend = "local"
        delegate._tts_sidecar_url = ""
        delegate._whisper_backend = "local"
        delegate._preview_backend = "local"
        delegate._whisper_sidecar_url = ""
        delegate._whisper_cloud_url = ""
        delegate._whisper_cloud_api_key = ""

        state = delegate._handle_model_menu_action(None)

        assert state["assistant_backend"]["items"][0][1] == "Local OMLX"
        assert state["agent_shell"] == {
            "title": "Agent Shell",
            "items": [
                ("off", "Off", False, True),
                ("claude", "Claude Agent SDK", False, True),
                ("codex", "Codex SDK", True, True),
            ],
        }
