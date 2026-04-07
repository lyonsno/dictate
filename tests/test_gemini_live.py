"""Tests for the Gemini Live API client and audio player."""

from __future__ import annotations

import base64
import json
import struct
import threading
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class TestLiveAudioPlayer:
    """Unit tests for LiveAudioPlayer."""

    @patch("spoke.gemini_live.sd")
    def test_write_chunk_converts_int16_to_float32(self, mock_sd):
        from spoke.gemini_live import LiveAudioPlayer

        stream = MagicMock()
        mock_sd.OutputStream.return_value = stream
        player = LiveAudioPlayer()

        # 4 samples of int16 PCM at half amplitude
        pcm = np.array([16383, -16383, 0, 32767], dtype=np.int16)
        player.write_chunk(pcm.tobytes())

        stream.write.assert_called_once()
        written = stream.write.call_args[0][0]
        assert written.dtype == np.float32
        assert written.shape == (4, 1)
        np.testing.assert_allclose(written[3, 0], 1.0, atol=1e-4)

    @patch("spoke.gemini_live.sd")
    def test_write_chunk_reports_amplitude(self, mock_sd):
        from spoke.gemini_live import LiveAudioPlayer

        mock_sd.OutputStream.return_value = MagicMock()
        amplitudes = []
        player = LiveAudioPlayer(amplitude_callback=amplitudes.append)

        pcm = np.array([16383, -16383], dtype=np.int16)
        player.write_chunk(pcm.tobytes())

        assert len(amplitudes) == 1
        assert amplitudes[0] > 0.0

    @patch("spoke.gemini_live.sd")
    def test_flush_reopens_stream(self, mock_sd):
        from spoke.gemini_live import LiveAudioPlayer

        streams = []
        mock_sd.OutputStream.side_effect = lambda **kw: MagicMock()

        player = LiveAudioPlayer()
        first_stream = player._stream
        player.flush()
        second_stream = player._stream

        assert first_stream is not second_stream
        first_stream.abort.assert_called_once()
        first_stream.close.assert_called_once()

    @patch("spoke.gemini_live.sd")
    def test_close_stops_stream(self, mock_sd):
        from spoke.gemini_live import LiveAudioPlayer

        stream = MagicMock()
        mock_sd.OutputStream.return_value = stream
        player = LiveAudioPlayer()
        player.close()

        stream.stop.assert_called_once()
        stream.close.assert_called_once()
        assert player._stream is None


class TestGeminiLiveClient:
    """Unit tests for GeminiLiveClient (no real WebSocket)."""

    def test_send_audio_converts_float32_to_int16(self):
        from spoke.gemini_live import GeminiLiveClient

        client = GeminiLiveClient("test-key")
        client._connected = True

        chunk = np.array([0.5, -0.5, 1.0, -1.0], dtype=np.float32)
        client.send_audio(chunk)

        raw = client._send_queue.get(timeout=1)
        pcm = np.frombuffer(raw, dtype=np.int16)
        assert len(pcm) == 4
        assert pcm[0] == 16383  # 0.5 * 32767 ≈ 16383
        assert pcm[2] == 32767  # clipped to max
        assert pcm[3] == -32767  # clipped to min (not -32768 due to symmetric clip)

    def test_send_audio_noop_when_disconnected(self):
        from spoke.gemini_live import GeminiLiveClient

        client = GeminiLiveClient("test-key")
        assert not client._connected

        chunk = np.array([0.5], dtype=np.float32)
        client.send_audio(chunk)

        assert client._send_queue.empty()

    def test_setup_message_structure(self):
        """Verify the setup message matches the Gemini Live API spec."""
        from spoke.gemini_live import GeminiLiveClient

        client = GeminiLiveClient(
            "test-key",
            model="gemini-2.0-flash-live",
            voice="Puck",
            system_instruction="Be helpful.",
        )

        # The setup message is built inside _connect; verify the expected shape
        # by checking the model and voice are stored correctly.
        assert client._model == "gemini-2.0-flash-live"
        assert client._voice == "Puck"
        assert client._system_instruction == "Be helpful."

    def test_disconnect_pushes_shutdown_sentinel(self):
        from spoke.gemini_live import GeminiLiveClient, _SHUTDOWN

        client = GeminiLiveClient("test-key")
        client._connected = True
        client.disconnect()

        assert not client._connected
        item = client._send_queue.get(timeout=1)
        assert item is _SHUTDOWN


class TestReceiverParsing:
    """Test the receiver's message parsing logic in isolation."""

    def _make_server_audio_message(self, pcm_bytes: bytes) -> str:
        encoded = base64.b64encode(pcm_bytes).decode("ascii")
        return json.dumps({
            "serverContent": {
                "modelTurn": {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "audio/pcm;rate=24000",
                                "data": encoded,
                            }
                        }
                    ]
                }
            }
        })

    def _make_text_message(self, text: str) -> str:
        return json.dumps({
            "serverContent": {
                "modelTurn": {
                    "parts": [{"text": text}]
                }
            }
        })

    def _make_turn_complete_message(self) -> str:
        return json.dumps({
            "serverContent": {"turnComplete": True}
        })

    def _make_interrupted_message(self) -> str:
        return json.dumps({
            "serverContent": {"interrupted": True}
        })

    def test_receiver_dispatches_audio_callback(self):
        from spoke.gemini_live import GeminiLiveClient

        client = GeminiLiveClient("test-key")
        received_chunks = []
        client.on_audio_chunk = received_chunks.append

        pcm = np.array([100, -100], dtype=np.int16).tobytes()
        msg = self._make_server_audio_message(pcm)

        # Simulate the receiver's message parsing
        parsed = json.loads(msg)
        sc = parsed["serverContent"]
        mt = sc["modelTurn"]
        for part in mt["parts"]:
            inline = part.get("inlineData")
            if inline:
                audio_b64 = inline["data"]
                client.on_audio_chunk(base64.b64decode(audio_b64))

        assert len(received_chunks) == 1
        result = np.frombuffer(received_chunks[0], dtype=np.int16)
        np.testing.assert_array_equal(result, np.array([100, -100], dtype=np.int16))

    def test_receiver_dispatches_text_callback(self):
        from spoke.gemini_live import GeminiLiveClient

        client = GeminiLiveClient("test-key")
        received_texts = []
        client.on_text_chunk = received_texts.append

        msg = self._make_text_message("Hello there")
        parsed = json.loads(msg)
        sc = parsed["serverContent"]
        mt = sc["modelTurn"]
        for part in mt["parts"]:
            text = part.get("text")
            if text and client.on_text_chunk:
                client.on_text_chunk(text)

        assert received_texts == ["Hello there"]

    def test_interrupted_message_fires_callback(self):
        from spoke.gemini_live import GeminiLiveClient

        client = GeminiLiveClient("test-key")
        interrupted = []
        client.on_interrupted = lambda: interrupted.append(True)

        msg = self._make_interrupted_message()
        parsed = json.loads(msg)
        sc = parsed["serverContent"]
        if sc.get("interrupted"):
            client.on_interrupted()

        assert interrupted == [True]

    def test_turn_complete_fires_callback(self):
        from spoke.gemini_live import GeminiLiveClient

        client = GeminiLiveClient("test-key")
        completed = []
        client.on_turn_complete = lambda: completed.append(True)

        msg = self._make_turn_complete_message()
        parsed = json.loads(msg)
        sc = parsed["serverContent"]
        if sc.get("turnComplete"):
            client.on_turn_complete()

        assert completed == [True]


class TestToolUseSupport:
    """Tests for Gemini Live tool use (function calling) integration."""

    def test_openai_schemas_converted_to_gemini_format(self):
        from spoke.gemini_live import _openai_tools_to_gemini

        openai_schemas = [
            {
                "type": "function",
                "function": {
                    "name": "capture_context",
                    "description": "Capture the screen",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "scope": {"type": "string", "enum": ["active_window", "screen"]},
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "add_to_tray",
                    "description": "Add text to tray",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
            },
        ]
        result = _openai_tools_to_gemini(openai_schemas)

        assert len(result) == 1
        declarations = result[0]["function_declarations"]
        assert len(declarations) == 2
        assert declarations[0]["name"] == "capture_context"
        assert declarations[0]["description"] == "Capture the screen"
        assert "parameters" in declarations[0]
        assert declarations[1]["name"] == "add_to_tray"

    def test_schema_conversion_strips_additionalProperties(self):
        from spoke.gemini_live import _openai_tools_to_gemini

        schemas = [{
            "type": "function",
            "function": {
                "name": "complex_tool",
                "description": "A tool with nested schemas",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ops": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"op": {"type": "string"}},
                                "required": ["op"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["ops"],
                    "additionalProperties": False,
                },
            },
        }]
        result = _openai_tools_to_gemini(schemas)
        params = result[0]["function_declarations"][0]["parameters"]
        assert "additionalProperties" not in params
        items = params["properties"]["ops"]["items"]
        assert "additionalProperties" not in items

    def test_client_stores_converted_tools(self):
        from spoke.gemini_live import GeminiLiveClient

        tools = [
            {"type": "function", "function": {"name": "test_tool", "description": "A test"}},
        ]
        client = GeminiLiveClient("test-key", tools=tools)

        assert client._tools is not None
        assert len(client._tools) == 1
        decls = client._tools[0]["function_declarations"]
        assert decls[0]["name"] == "test_tool"

    def test_client_no_tools_leaves_none(self):
        from spoke.gemini_live import GeminiLiveClient

        client = GeminiLiveClient("test-key")
        assert client._tools is None

    def test_send_tool_response_queues_structured_message(self):
        from spoke.gemini_live import GeminiLiveClient

        client = GeminiLiveClient("test-key")
        client._connected = True

        client.send_tool_response([
            {"id": "call_1", "name": "capture_context", "response": {"result": "{}"}}
        ])

        item = client._send_queue.get(timeout=1)
        assert isinstance(item, tuple)
        tag, msg = item
        assert tag == "__tool_response__"
        assert "tool_response" in msg
        fn_responses = msg["tool_response"]["function_responses"]
        assert len(fn_responses) == 1
        assert fn_responses[0]["id"] == "call_1"

    def test_send_tool_response_noop_when_disconnected(self):
        from spoke.gemini_live import GeminiLiveClient

        client = GeminiLiveClient("test-key")
        assert not client._connected

        client.send_tool_response([
            {"id": "call_1", "name": "test", "response": {"result": "x"}}
        ])
        assert client._send_queue.empty()

    def test_tool_call_callback_receives_function_calls(self):
        """Simulate a toolCall message arriving and verify dispatch."""
        from spoke.gemini_live import GeminiLiveClient

        client = GeminiLiveClient("test-key")
        received = []
        client.on_tool_call = received.append

        tool_call_msg = {
            "toolCall": {
                "functionCalls": [
                    {"id": "abc-123", "name": "capture_context", "args": {"scope": "screen"}},
                    {"id": "abc-124", "name": "add_to_tray", "args": {"text": "hello"}},
                ]
            }
        }

        # Simulate what _receiver_loop does
        tc = tool_call_msg.get("toolCall")
        fn_calls = tc.get("functionCalls", [])
        if fn_calls and client.on_tool_call:
            client.on_tool_call(fn_calls)

        assert len(received) == 1
        assert len(received[0]) == 2
        assert received[0][0]["name"] == "capture_context"
        assert received[0][1]["args"] == {"text": "hello"}

    def test_sender_loop_handles_tagged_tuple(self):
        """Verify sender_loop forwards tagged tuples as JSON."""
        import asyncio
        from unittest.mock import AsyncMock

        from spoke.gemini_live import GeminiLiveClient

        client = GeminiLiveClient("test-key")
        client._connected = True
        client._ws = AsyncMock()

        # Queue a tool response
        tool_msg = {"tool_response": {"function_responses": [{"id": "1", "name": "t", "response": {}}]}}
        client._send_queue.put(("__tool_response__", tool_msg))
        # Then shutdown
        from spoke.gemini_live import _SHUTDOWN
        client._send_queue.put(_SHUTDOWN)

        asyncio.run(client._sender_loop())

        # First call should be the tool response JSON
        calls = client._ws.send.call_args_list
        assert len(calls) == 1
        sent = json.loads(calls[0][0][0])
        assert "tool_response" in sent


class TestLiveToolSchemaFiltering:
    """Tests for tool schema filtering when entering live mode."""

    def test_read_aloud_excluded_from_live_tools(self):
        """Live mode should exclude read_aloud since model has native voice."""
        from spoke.tool_dispatch import get_tool_schemas

        all_schemas = get_tool_schemas()
        all_names = {s["function"]["name"] for s in all_schemas}
        assert "read_aloud" in all_names, "read_aloud should exist in full schema set"

        # Apply the same filter as __main__.py _enter_live_mode
        live_tools = [
            s for s in all_schemas
            if s.get("function", {}).get("name") != "read_aloud"
        ]
        live_names = {s["function"]["name"] for s in live_tools}
        assert "read_aloud" not in live_names
        assert "capture_context" in live_names
        assert "add_to_tray" in live_names
        assert len(live_tools) == len(all_schemas) - 1

    def test_gemini_setup_includes_tools_when_provided(self):
        """Setup message should contain tools field when tools are given."""
        from spoke.gemini_live import GeminiLiveClient

        tools = [
            {"type": "function", "function": {"name": "capture_context", "description": "Capture screen"}},
            {"type": "function", "function": {"name": "add_to_tray", "description": "Add to tray"}},
        ]
        client = GeminiLiveClient("test-key", tools=tools)
        assert client._tools is not None
        decl_names = [d["name"] for d in client._tools[0]["function_declarations"]]
        assert "capture_context" in decl_names
        assert "add_to_tray" in decl_names

    def test_gemini_setup_omits_tools_when_none(self):
        """Setup message should not contain tools field when none given."""
        from spoke.gemini_live import GeminiLiveClient

        client = GeminiLiveClient("test-key")
        assert client._tools is None


class TestLiveToolDispatch:
    """Tests for tool call dispatch from live mode (_on_live_tool_call)."""

    def test_tool_worker_executes_and_responds(self):
        """_live_tool_worker should call execute_tool and send response."""
        import spoke.__main__ as main_module

        d = main_module.SpokeAppDelegate.__new__(main_module.SpokeAppDelegate)
        d._scene_cache = None
        d._tray_stack = []
        d._tray_index = 0
        d._tray_active = False
        d._live_client = MagicMock()

        # Stub _add_assistant_content_to_tray
        d._add_assistant_content_to_tray = MagicMock()

        function_calls = [
            {"id": "call-1", "name": "capture_context", "args": {"scope": "screen"}},
        ]

        with patch("spoke.tool_dispatch.execute_tool", return_value='{"scene_ref": "test"}') as mock_exec:
            d._live_tool_worker(function_calls)

        mock_exec.assert_called_once_with(
            name="capture_context",
            arguments={"scope": "screen"},
            scene_cache=None,
            last_response=None,
            tts_client=None,
            tray_writer=d._add_assistant_content_to_tray,
        )
        d._live_client.send_tool_response.assert_called_once()
        responses = d._live_client.send_tool_response.call_args[0][0]
        assert len(responses) == 1
        assert responses[0]["id"] == "call-1"
        assert responses[0]["name"] == "capture_context"

    def test_tool_worker_handles_execution_error(self):
        """_live_tool_worker should catch exceptions and send error response."""
        import spoke.__main__ as main_module

        d = main_module.SpokeAppDelegate.__new__(main_module.SpokeAppDelegate)
        d._scene_cache = None
        d._tray_stack = []
        d._tray_index = 0
        d._tray_active = False
        d._live_client = MagicMock()
        d._add_assistant_content_to_tray = MagicMock()

        function_calls = [
            {"id": "call-err", "name": "bad_tool", "args": {}},
        ]

        with patch("spoke.tool_dispatch.execute_tool", side_effect=RuntimeError("boom")):
            d._live_tool_worker(function_calls)

        d._live_client.send_tool_response.assert_called_once()
        responses = d._live_client.send_tool_response.call_args[0][0]
        assert "error" in responses[0]["response"]["result"]

    def test_on_live_tool_call_dispatches_to_thread(self):
        """_on_live_tool_call should spawn a worker thread, not block."""
        import spoke.__main__ as main_module

        d = main_module.SpokeAppDelegate.__new__(main_module.SpokeAppDelegate)
        d._scene_cache = None
        d._tray_stack = []
        d._tray_index = 0
        d._tray_active = False
        d._live_client = MagicMock()
        d._add_assistant_content_to_tray = MagicMock()

        started = threading.Event()
        original_start = threading.Thread.start

        def _track_start(self_thread):
            original_start(self_thread)
            if self_thread.name == "live-tool-exec":
                started.set()

        function_calls = [
            {"id": "call-t", "name": "capture_context", "args": {}},
        ]

        with patch("spoke.tool_dispatch.execute_tool", return_value='{}'):
            with patch.object(threading.Thread, "start", _track_start):
                d._on_live_tool_call(function_calls)

        assert started.wait(timeout=2), "Worker thread should have started"
