"""Thinking narrator sidecar.

Reads streaming thinking tokens from a reasoning model and produces
short, present-participle status lines via a small local model (or
cloud endpoint).  Architecture A: each summary becomes an assistant
turn in a growing chat history so the narrator naturally *continues*
its own summary stream.

Configuration (env vars):
    SPOKE_NARRATOR_URL      OpenAI-compatible base URL (default: same as command URL)
    SPOKE_NARRATOR_MODEL    Model ID (default: Bonsai-8B-mlx-1bit)
    SPOKE_NARRATOR_API_KEY  Bearer token (falls back to OMLX_SERVER_API_KEY)
    SPOKE_NARRATOR_ENABLED  "1" to enable, "0" to disable (default: "1")
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Callable
from urllib.parse import urlparse

import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

_DEFAULT_NARRATOR_MODEL = "Bonsai-8B-mlx-1bit"

_SYSTEM_PROMPT = """\
You narrate an AI's thinking. Read the reasoning excerpt and write a \
short status line — what it is figuring out RIGHT NOW.

Rules:
- One fragment or short sentence. 8–15 words. Never exceed 15 words.
- Start with a present participle: Considering, Evaluating, Comparing, \
Breaking down, Checking, Debugging, Revisiting, Weighing, Testing, etc.
- Be specific: name the concrete thing (algorithm, variable, edge case, \
tradeoff). Never generic ("Thinking about the problem").
- Focus on what CHANGED or is NEW in this excerpt compared to before.
- Say what the AI is doing, not "the user".
- No preamble, no commentary. Output ONLY the status line."""

# ── chunking parameters ─────────────────────────────────────────────

_TARGET_CHUNK_TOKENS = 300
_MIN_INTERVAL_S = 5.0  # minimum seconds between narrator calls
_MAX_TOKENS = 30        # generation budget for each summary


def _rough_token_count(text: str) -> int:
    """Approximate token count (words × 1.3)."""
    return int(len(text.split()) * 1.3)


class ThinkingNarrator:
    """Accumulates thinking tokens and periodically summarizes them.

    Thread-safe.  Call ``feed()`` from the streaming thread with each
    thinking token.  Summaries are delivered via the ``on_summary``
    callback on a background thread — the caller is responsible for
    marshalling to the main thread if needed.
    """

    def __init__(
        self,
        on_summary: Callable[[str], None],
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ):
        self._on_summary = on_summary

        # Endpoint config — fall back to command URL, then localhost
        raw_url = (
            base_url
            or os.environ.get("SPOKE_NARRATOR_URL")
            or os.environ.get("SPOKE_COMMAND_URL", "http://localhost:8001")
        ).rstrip("/")
        path = urlparse(raw_url).path.rstrip("/")
        self._url_has_version_prefix = any(
            seg.startswith("v") and seg[1:].replace("beta", "").isdigit()
            for seg in path.split("/") if seg
        )
        self._base_url = raw_url
        self._model = (
            model
            or os.environ.get("SPOKE_NARRATOR_MODEL", _DEFAULT_NARRATOR_MODEL)
        )
        self._api_key = (
            api_key
            or os.environ.get("SPOKE_NARRATOR_API_KEY")
            or os.environ.get("OMLX_SERVER_API_KEY", "")
        )

        # State (guarded by _lock)
        self._lock = threading.Lock()
        self._buffer = ""          # accumulated thinking tokens since last dispatch
        self._last_dispatch = 0.0  # monotonic time of last narrator call
        self._messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
        self._active = False
        self._dispatch_thread: threading.Thread | None = None
        self._pending_dispatch = False  # a dispatch is in flight

    @staticmethod
    def is_enabled() -> bool:
        return os.environ.get("SPOKE_NARRATOR_ENABLED", "1") != "0"

    def start(self) -> None:
        """Begin a new narration session (new thinking phase)."""
        with self._lock:
            self._buffer = ""
            self._last_dispatch = time.monotonic()
            self._messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
            self._active = True
            self._pending_dispatch = False
        logger.info("Narrator session started")

    def stop(self) -> None:
        """End the narration session."""
        with self._lock:
            self._active = False
            self._buffer = ""
        logger.info("Narrator session stopped")

    def feed(self, token: str) -> None:
        """Feed a thinking token.  May trigger an async narrator call."""
        with self._lock:
            if not self._active:
                return
            self._buffer += token
            now = time.monotonic()
            elapsed = now - self._last_dispatch
            tokens = _rough_token_count(self._buffer)

            # Dispatch when BOTH conditions met: enough tokens AND enough time
            should_dispatch = (
                tokens >= _TARGET_CHUNK_TOKENS
                and elapsed >= _MIN_INTERVAL_S
                and not self._pending_dispatch
            )
            if not should_dispatch:
                return

            chunk = self._buffer
            self._buffer = ""
            self._last_dispatch = now
            self._pending_dispatch = True

        # Fire async
        t = threading.Thread(target=self._dispatch, args=(chunk,), daemon=True)
        t.start()

    def _dispatch(self, chunk: str) -> None:
        """Call the narrator model and deliver the summary."""
        try:
            # Build user message with the verbatim chunk
            user_content = f"Current reasoning excerpt:\n\n{chunk}"

            with self._lock:
                self._messages.append({"role": "user", "content": user_content})
                messages = list(self._messages)

            summary = self._chat_completion(messages)

            if summary:
                # Add as assistant turn for continuity
                with self._lock:
                    self._messages.append({"role": "assistant", "content": summary})
                    if not self._active:
                        return
                logger.info("Narrator summary: %s", summary)
                self._on_summary(summary)

        except Exception:
            logger.exception("Narrator dispatch failed")
        finally:
            with self._lock:
                self._pending_dispatch = False

    def _chat_completion(self, messages: list[dict]) -> str:
        """Synchronous chat completion call."""
        body = {
            "model": self._model,
            "messages": messages,
            "max_tokens": _MAX_TOKENS,
            "temperature": 0.3,
            "stream": False,
        }

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        url = (
            f"{self._base_url}/chat/completions"
            if self._url_has_version_prefix
            else f"{self._base_url}/v1/chat/completions"
        )
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        )

        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
        elapsed = time.monotonic() - t0
        logger.info("Narrator call: %.2fs, %d messages", elapsed, len(messages))

        return result["choices"][0]["message"]["content"].strip()
