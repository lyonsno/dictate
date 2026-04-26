"""Tests for converge-carve.py history loading with the new format."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

# Import the carve script as a module
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
import importlib

_carve = importlib.import_module("converge-carve")


class TestLoadHistoryUtterances:
    def test_legacy_pair_format_still_loads(self, tmp_path):
        history = [
            ["old user request", "old assistant reply"],
        ]
        history_path = tmp_path / "history.json"
        history_path.write_text(json.dumps(history))

        with patch.object(_carve, "_HISTORY_PATH", history_path):
            pairs = _carve._load_history_utterances()

        assert pairs == [
            {"user": "old user request", "assistant": "old assistant reply"}
        ]

    def test_new_format_message_chains(self, tmp_path):
        history = [
            [
                {"role": "user", "content": "what time is it"},
                {"role": "assistant", "content": "It's 3pm."},
            ],
            [
                {"role": "user", "content": "read the screen"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "tc1", "function": {"name": "capture_context"}}]},
                {"role": "tool", "tool_call_id": "tc1", "content": '{"scene_ref":"s1"}'},
                {"role": "assistant", "content": "I see your terminal."},
            ],
        ]
        history_path = tmp_path / "history.json"
        history_path.write_text(json.dumps(history))

        with patch.object(_carve, "_HISTORY_PATH", history_path):
            pairs = _carve._load_history_utterances()

        assert len(pairs) == 2
        assert pairs[0] == {"user": "what time is it", "assistant": "It's 3pm."}
        # Tool-using turn: first user msg + first non-null assistant content
        assert pairs[1]["user"] == "read the screen"
        assert pairs[1]["assistant"] == "I see your terminal."

    def test_skips_turns_without_user_message(self, tmp_path):
        history = [
            [
                {"role": "system", "content": "you are helpful"},
                {"role": "assistant", "content": "hello"},
            ],
        ]
        history_path = tmp_path / "history.json"
        history_path.write_text(json.dumps(history))

        with patch.object(_carve, "_HISTORY_PATH", history_path):
            pairs = _carve._load_history_utterances()

        assert pairs == []

    def test_missing_file_returns_empty(self, tmp_path):
        with patch.object(_carve, "_HISTORY_PATH", tmp_path / "missing.json"):
            assert _carve._load_history_utterances() == []


class TestCallModelUrl:
    """Verify _call_model builds the correct URL for local and cloud endpoints."""

    def test_local_url_gets_v1_prefix(self):
        """Local endpoints without version prefix get /v1 prepended."""
        import urllib.request
        with patch.object(urllib.request, "urlopen") as mock_open, \
             patch.dict(os.environ, {"SPOKE_COMMAND_URL": "http://localhost:8090"}, clear=False):
            mock_resp = mock_open.return_value.__enter__.return_value
            mock_resp.read.return_value = b'{"choices":[{"message":{"content":"ok"}}]}'
            _carve._call_model("sys", "usr")
            req = mock_open.call_args[0][0]
            assert req.full_url == "http://localhost:8090/v1/chat/completions"

    def test_cloud_url_with_version_prefix_no_double_v1(self):
        """Cloud endpoints that already have /v1 in the URL must not get /v1/v1."""
        import urllib.request
        with patch.object(urllib.request, "urlopen") as mock_open, \
             patch.dict(os.environ, {"SPOKE_COMMAND_URL": "https://generativelanguage.googleapis.com/v1beta"}, clear=False):
            mock_resp = mock_open.return_value.__enter__.return_value
            mock_resp.read.return_value = b'{"choices":[{"message":{"content":"ok"}}]}'
            _carve._call_model("sys", "usr")
            req = mock_open.call_args[0][0]
            assert req.full_url == "https://generativelanguage.googleapis.com/v1beta/chat/completions"

    def test_openrouter_url_with_v1(self):
        """OpenRouter-style URLs with /v1 already present."""
        import urllib.request
        with patch.object(urllib.request, "urlopen") as mock_open, \
             patch.dict(os.environ, {"SPOKE_COMMAND_URL": "https://openrouter.ai/api/v1"}, clear=False):
            mock_resp = mock_open.return_value.__enter__.return_value
            mock_resp.read.return_value = b'{"choices":[{"message":{"content":"ok"}}]}'
            _carve._call_model("sys", "usr")
            req = mock_open.call_args[0][0]
            assert req.full_url == "https://openrouter.ai/api/v1/chat/completions"
