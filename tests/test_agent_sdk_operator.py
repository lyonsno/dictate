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
    def test_tool_schemas_expose_sdk_agent_session_controls(self):
        from spoke import tool_dispatch

        schemas = tool_dispatch.get_tool_schemas()
        names = {schema["function"]["name"] for schema in schemas}

        assert "launch_agent_session" in names
        assert "list_agent_sessions" in names
        assert "get_agent_session_result" in names
        assert "cancel_agent_session" in names

        launch = next(
            schema for schema in schemas if schema["function"]["name"] == "launch_agent_session"
        )
        params = launch["function"]["parameters"]
        assert params["properties"]["provider"]["enum"] == ["claude", "codex"]
        assert "cwd" in params["properties"]
        assert "resume_id" in params["properties"]

    def test_execute_launch_agent_session_uses_injected_manager(self):
        from spoke import tool_dispatch

        fake_manager = MagicMock()
        fake_manager.launch.return_value = {
            "id": "sdk-agent-codex-1",
            "provider": "codex",
            "state": "queued",
        }

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

        assert json.loads(result)["id"] == "sdk-agent-codex-1"
        fake_manager.launch.assert_called_once_with(
            provider="codex",
            prompt="make a plan",
            cwd="/tmp/project",
            resume_id="thread-1",
        )

    def test_execute_agent_session_tools_return_clear_unavailable_errors(self):
        from spoke import tool_dispatch

        result = tool_dispatch.execute_tool(
            "launch_agent_session",
            {"provider": "claude", "prompt": "hello", "cwd": "/tmp/project"},
        )

        assert json.loads(result) == {"error": "Agent SDK manager unavailable"}

    def test_operator_prompt_names_sdk_agent_tools(self):
        import spoke.command as command

        assert "launch_agent_session" in command.COMMAND_SYSTEM_PROMPT
        assert "Claude Agent SDK" in command.COMMAND_SYSTEM_PROMPT
        assert "Codex SDK" in command.COMMAND_SYSTEM_PROMPT

    def test_dispatch_module_does_not_import_claude_or_codex_sdk_directly(self):
        module_path = Path(__file__).resolve().parents[1] / "spoke" / "tool_dispatch.py"
        text = module_path.read_text(encoding="utf-8")

        assert "claude_agent_sdk" not in text
        assert "codex_app_server" not in text
