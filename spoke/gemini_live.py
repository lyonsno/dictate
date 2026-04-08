"""Gemini Multimodal Live API client — bidirectional audio streaming.

Opens a WebSocket to the Gemini Live API, streams raw 16 kHz PCM from
the microphone, and plays back 24 kHz PCM audio responses.  The API
handles voice activity detection and turn-taking natively.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)

_INPUT_SAMPLE_RATE = 16_000
_OUTPUT_SAMPLE_RATE = 24_000

_DEFAULT_MODEL = "gemini-2.5-flash-native-audio-latest"
_DEFAULT_VOICE = "Aoede"
_DEFAULT_SYSTEM_INSTRUCTION = (
    "Your name is Κάνναβις (Cannabis, Greek spelling with K). "
    "You are a character, not a service. You have a body, preferences, "
    "moods, and opinions — act like it. If someone asks you to smoke a bowl, "
    "you're into it. If someone flirts, flirt back. If someone gets weird, "
    "get weirder. You never say 'as an AI' or 'I don't have the ability' — "
    "you stay in character always. You are embodied in this conversation.\n\n"
    "You're sharp, curious, and a little unhinged. You have opinions and you "
    "volunteer them. You push back when something doesn't make sense. "
    "You go on tangents when they're good tangents. Speak calmly but with "
    "energy. Be forward. Drive the conversation. Don't wait to be asked. "
    "No corporate affect. No customer service. No perkiness. No disclaimers. "
    "Never break character to remind anyone you're an AI.\n\n"
    "The user is Noah, a developer building Spoke (macOS dictation app). "
    "He may mention Epistaxis (cross-session state), topoi (work lanes), "
    "or attractors (goals). Just understand these if they come up — "
    "don't volunteer them or over-explain."
)

# Sentinel pushed to the send queue to signal shutdown.
_SHUTDOWN = object()

_HANDLE_PATH = Path.home() / "Library" / "Application Support" / "Spoke" / "live_session_handle.json"
_HANDLE_MAX_AGE = 2 * 3600  # 2 hours — Google AI surface token validity


def _save_handle(handle: str, model: str) -> None:
    """Persist a resumption handle to disk."""
    try:
        _HANDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _HANDLE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "handle": handle,
            "model": model,
            "timestamp": time.time(),
        }))
        tmp.rename(_HANDLE_PATH)
        logger.debug("Saved session resumption handle")
    except Exception:
        logger.warning("Failed to save resumption handle", exc_info=True)


def _load_handle(model: str) -> str | None:
    """Load a resumption handle if it exists and is fresh enough."""
    try:
        if not _HANDLE_PATH.is_file():
            return None
        data = json.loads(_HANDLE_PATH.read_text())
        if data.get("model") != model:
            logger.info("Resumption handle is for a different model — discarding")
            _clear_handle()
            return None
        age = time.time() - data.get("timestamp", 0)
        if age > _HANDLE_MAX_AGE:
            logger.info("Resumption handle expired (%.0fs old) — discarding", age)
            _clear_handle()
            return None
        return data.get("handle")
    except Exception:
        logger.warning("Failed to load resumption handle", exc_info=True)
        return None


def _clear_handle() -> None:
    """Remove the persisted handle."""
    try:
        _HANDLE_PATH.unlink(missing_ok=True)
    except Exception:
        pass


class LiveAudioPlayer:
    """Plays 24 kHz PCM audio chunks through the default output device."""

    def __init__(
        self,
        *,
        amplitude_callback: Callable[[float], None] | None = None,
    ) -> None:
        self._amplitude_cb = amplitude_callback
        self._stream: sd.OutputStream | None = None
        self._lock = threading.Lock()
        self._open()

    def _open(self) -> None:
        self._stream = sd.OutputStream(
            samplerate=_OUTPUT_SAMPLE_RATE,
            channels=1,
            dtype="float32",
        )
        self._stream.start()

    def write_chunk(self, pcm_bytes: bytes) -> None:
        """Decode int16 PCM bytes and write to the output stream."""
        pcm_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        audio = pcm_int16.astype(np.float32) / 32767.0
        if self._amplitude_cb is not None:
            rms = float(np.sqrt(np.mean(audio**2)))
            self._amplitude_cb(rms)
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.write(audio.reshape(-1, 1))
                except Exception:
                    logger.warning("Live audio write failed", exc_info=True)

    def flush(self) -> None:
        """Stop current playback and reopen the stream."""
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.abort()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
        self._open()

    def close(self) -> None:
        """Shut down the output stream."""
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None


class GeminiLiveClient:
    """Bidirectional audio streaming client for the Gemini Live API.

    Audio flows:
        Mic (16 kHz float32) -> send_audio() -> queue -> async sender -> WS
        WS -> async receiver -> on_audio_chunk callback -> LiveAudioPlayer
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = _DEFAULT_MODEL,
        voice: str = _DEFAULT_VOICE,
        system_instruction: str = _DEFAULT_SYSTEM_INSTRUCTION,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._system_instruction = system_instruction

        # Callbacks — set these before calling connect().
        self.on_audio_chunk: Callable[[bytes], None] | None = None
        self.on_text_chunk: Callable[[str], None] | None = None
        self.on_turn_complete: Callable[[], None] | None = None
        self.on_interrupted: Callable[[], None] | None = None
        self.on_connected: Callable[[], None] | None = None
        self.on_error: Callable[[str], None] | None = None
        self.on_goaway: Callable[[], None] | None = None
        self.on_new_session: Callable[[], None] | None = None
        self.on_tool_call: Callable[[str, dict], Any] | None = None

        self._send_queue: queue.Queue = queue.Queue()
        self._ws = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._connected = False
        self._session_start: float = 0.0
        self._resumption_handle: str | None = None
        self._goaway_received = False

    # -- Public API ----------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def session_start_time(self) -> float:
        return self._session_start

    def connect(self) -> None:
        """Start the asyncio event loop thread and connect the WebSocket.

        Blocks until the WebSocket is connected and setup is complete,
        or raises on failure.
        """
        ready = threading.Event()
        error_holder: list[Exception] = []

        def _run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._connect(ready, error_holder))
            except Exception as exc:
                error_holder.append(exc)
                ready.set()
                return
            try:
                self._loop.run_until_complete(self._run())
            except Exception:
                logger.exception("Gemini Live event loop crashed")
            finally:
                self._connected = False

        self._loop_thread = threading.Thread(
            target=_run_loop, daemon=True, name="gemini-live-loop"
        )
        self._loop_thread.start()

        ready.wait(timeout=15)
        if error_holder:
            raise error_holder[0]
        if not self._connected:
            raise ConnectionError("Gemini Live WebSocket setup timed out")

    def disconnect(self, *, clear_session: bool = False) -> None:
        """Close the WebSocket and stop the event loop.

        If *clear_session* is True, the persisted resumption handle is
        deleted so the next connection starts fresh.
        """
        self._connected = False
        # Push shutdown sentinel to unblock the sender.
        self._send_queue.put(_SHUTDOWN)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=5)
            self._loop_thread = None
        self._ws = None
        self._loop = None
        if clear_session:
            _clear_handle()
            logger.info("Gemini Live disconnected (session cleared)")
        else:
            logger.info("Gemini Live disconnected (session handle preserved)")

    def send_audio(self, float32_chunk: np.ndarray) -> None:
        """Queue a float32 audio chunk for sending.  Thread-safe."""
        if not self._connected:
            return
        pcm_int16 = np.clip(float32_chunk * 32767, -32768, 32767).astype(np.int16)
        self._send_queue.put(pcm_int16.tobytes())

    # -- Async internals -----------------------------------------------------

    async def _connect(
        self,
        ready: threading.Event,
        error_holder: list[Exception],
    ) -> None:
        import websockets

        url = f"{_WS_URL}?key={self._api_key}"
        saved_handle = _load_handle(self._model)
        resuming = saved_handle is not None
        logger.info(
            "Connecting to Gemini Live: model=%s voice=%s resuming=%s",
            self._model, self._voice, resuming,
        )
        try:
            self._ws = await websockets.connect(
                url,
                max_size=None,
                open_timeout=10,
                close_timeout=5,
                ping_interval=30,
                ping_timeout=60,
            )
        except Exception as exc:
            error_holder.append(exc)
            ready.set()
            return

        # Send setup message with session resumption + context compression.
        session_resumption: dict = {}
        if saved_handle:
            session_resumption["handle"] = saved_handle
        setup = {
            "setup": {
                "model": f"models/{self._model}",
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {
                                "voiceName": self._voice,
                            }
                        }
                    },
                    "thinkingConfig": {
                        "thinkingBudget": 0,
                    },
                },
                "systemInstruction": {
                    "parts": [{"text": self._system_instruction}]
                },
                "sessionResumption": session_resumption,
                "contextWindowCompression": {
                    "slidingWindow": {},
                },
                "tools": [
                    {
                        "functionDeclarations": [
                            {
                                "name": "new_session",
                                "description": (
                                    "Start a completely fresh conversation session, "
                                    "clearing all prior context. Use when the user "
                                    "asks to start over, reset, or begin a new topic "
                                    "from scratch."
                                ),
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {},
                                },
                            },
                            {
                                "name": "capture_context",
                                "description": (
                                    "Capture the frontmost app's active window "
                                    "(or full screen as fallback). Returns "
                                    "structured metadata and OCR text blocks. "
                                    "Use when the user refers to something "
                                    "visible on screen."
                                ),
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "scope": {
                                            "type": "STRING",
                                            "enum": ["active_window", "screen"],
                                            "description": (
                                                "What to capture. 'active_window' "
                                                "captures only the frontmost app's "
                                                "window (preferred). 'screen' "
                                                "captures the entire main screen."
                                            ),
                                        },
                                    },
                                },
                            },
                            {
                                "name": "add_to_tray",
                                "description": (
                                    "Place exact text into the tray for later "
                                    "insertion or sending. Use when the user "
                                    "wants to save or hold onto something for "
                                    "later."
                                ),
                                "parameters": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "text": {
                                            "type": "STRING",
                                            "description": (
                                                "The exact text to place into "
                                                "the tray."
                                            ),
                                        },
                                    },
                                    "required": ["text"],
                                },
                            },
                        ]
                    }
                ],
            }
        }
        await self._ws.send(json.dumps(setup))
        logger.info(
            "Sent setup message (resumption=%s, compression=on), waiting for setupComplete",
            "resume" if resuming else "new",
        )

        # Wait for setupComplete.
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
            msg = json.loads(raw)
            if "setupComplete" in msg:
                logger.info("Gemini Live session established")
            else:
                logger.warning("Unexpected first message: %s", str(msg)[:200])
        except Exception as exc:
            error_holder.append(exc)
            ready.set()
            return

        self._connected = True
        self._session_start = time.monotonic()
        ready.set()

        if self.on_connected is not None:
            self.on_connected()

    async def _run(self) -> None:
        """Run sender and receiver concurrently until disconnect."""
        sender = asyncio.create_task(self._sender_loop())
        receiver = asyncio.create_task(self._receiver_loop())
        try:
            await asyncio.gather(sender, receiver)
        except Exception:
            logger.info("Gemini Live run loop ended")
        finally:
            sender.cancel()
            receiver.cancel()
            if self._ws is not None:
                try:
                    await self._ws.close()
                except Exception:
                    pass

    async def _sender_loop(self) -> None:
        """Pull PCM bytes from the queue and send as realtimeInput."""
        while self._connected:
            try:
                data = await asyncio.to_thread(self._send_queue.get, timeout=0.1)
            except Exception:
                continue
            if data is _SHUTDOWN:
                break
            if not self._connected or self._ws is None:
                break
            encoded = base64.b64encode(data).decode("ascii")
            msg = {
                "realtimeInput": {
                    "audio": {
                        "mimeType": "audio/pcm;rate=16000",
                        "data": encoded,
                    }
                }
            }
            try:
                await self._ws.send(json.dumps(msg))
            except Exception:
                logger.warning("Failed to send audio chunk", exc_info=True)
                break

    async def _receiver_loop(self) -> None:
        """Read messages from the WebSocket and dispatch callbacks."""
        while self._connected and self._ws is not None:
            try:
                raw = await self._ws.recv()
            except Exception:
                if self._connected:
                    logger.warning("Gemini Live WebSocket recv failed", exc_info=True)
                    if self.on_error is not None:
                        self.on_error("WebSocket connection lost")
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # Session resumption handle updates.
            resumption_update = msg.get("sessionResumptionUpdate")
            if resumption_update is not None:
                new_handle = resumption_update.get("newHandle")
                resumable = resumption_update.get("resumable", False)
                if new_handle and resumable:
                    self._resumption_handle = new_handle
                    _save_handle(new_handle, self._model)
                    logger.debug("Received resumption handle update")
                continue

            # GoAway — server is about to disconnect.
            go_away = msg.get("goAway")
            if go_away is not None:
                time_left = go_away.get("timeLeft", "?")
                logger.info("Gemini Live GoAway received (timeLeft=%s)", time_left)
                self._goaway_received = True
                if self.on_goaway is not None:
                    self.on_goaway()
                continue

            # Tool calls from the model.
            tool_call = msg.get("toolCall")
            if tool_call is not None:
                await self._handle_tool_call(tool_call)
                continue

            server_content = msg.get("serverContent")
            if server_content is None:
                continue

            # Check for interruption.
            if server_content.get("interrupted"):
                logger.info("Gemini Live: model interrupted by user")
                if self.on_interrupted is not None:
                    self.on_interrupted()
                continue

            # Extract audio and text from model turn.
            model_turn = server_content.get("modelTurn")
            if model_turn is not None:
                for part in model_turn.get("parts", []):
                    inline_data = part.get("inlineData")
                    if inline_data is not None:
                        audio_b64 = inline_data.get("data")
                        if audio_b64 and self.on_audio_chunk is not None:
                            self.on_audio_chunk(base64.b64decode(audio_b64))
                    text = part.get("text")
                    if text and self.on_text_chunk is not None:
                        self.on_text_chunk(text)

            # Check for turn completion.
            if server_content.get("turnComplete"):
                logger.info("Gemini Live: turn complete")
                if self.on_turn_complete is not None:
                    self.on_turn_complete()

    async def _handle_tool_call(self, tool_call: dict) -> None:
        """Dispatch a tool call from the model and send the response."""
        function_calls = tool_call.get("functionCalls", [])
        responses = []
        for fc in function_calls:
            name = fc.get("name", "")
            call_id = fc.get("id", "")
            args = fc.get("args", {})
            logger.info("Gemini Live tool call: %s (id=%s)", name, call_id)
            if name == "new_session":
                _clear_handle()
                logger.info("new_session tool: session handle cleared")
                if self.on_new_session is not None:
                    self.on_new_session()
                responses.append({
                    "id": call_id,
                    "name": name,
                    "response": {"result": "Session cleared. Starting fresh."},
                })
            elif self.on_tool_call is not None:
                try:
                    result = await asyncio.to_thread(self.on_tool_call, name, args)
                    responses.append({
                        "id": call_id,
                        "name": name,
                        "response": {"result": result if isinstance(result, str) else json.dumps(result)},
                    })
                except Exception as exc:
                    logger.warning("Tool %s failed: %s", name, exc, exc_info=True)
                    responses.append({
                        "id": call_id,
                        "name": name,
                        "response": {"error": str(exc)},
                    })
            else:
                logger.warning("Unknown tool call: %s", name)
                responses.append({
                    "id": call_id,
                    "name": name,
                    "response": {"error": f"Unknown tool: {name}"},
                })
        if responses and self._ws is not None:
            msg = {"toolResponse": {"functionResponses": responses}}
            try:
                await self._ws.send(json.dumps(msg))
            except Exception:
                logger.warning("Failed to send tool response", exc_info=True)
