"""Minimal Gemini-to-OpenAI compatibility shim for local command models.

This keeps Gemini CLI pointed at a Gemini-shaped API surface while translating
the request/response payloads to the local OpenAI-compatible OMLX endpoint.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterable
from urllib.parse import urlparse

import httpx

TARGET_URL = os.environ.get(
    "SPOKE_GEMINI_SHIM_TARGET_URL",
    "http://localhost:8001/v1/chat/completions",
)
AUTH_TOKEN = os.environ.get("SPOKE_GEMINI_SHIM_AUTH_TOKEN", "1234")
HOST = os.environ.get("SPOKE_GEMINI_SHIM_HOST", "127.0.0.1")
PORT = int(os.environ.get("SPOKE_GEMINI_SHIM_PORT", "8888"))

MODEL_MAP = {
    "gemini-2.5-pro": "step-3p5-flash-mixedp-final",
    "gemini-2.5-flash": "Qwen3p5-122B-A10B-mlx-mixedp",
    "gemini-2.5-flash-lite": "Qwen3-Coder-Next-mxfp8-experts",
    "gemini-1.5-pro": "qwen3p5-35B-A3B",
    "gemini-1.5-flash": "Qwen3.5-4B-MLX-bf16",
    "gemini-1.5-flash-8b": "Qwen3.5-0.8B-MLX-bf16",
    "default": "MLX-Qwen3.5-4B-Claude-4.6-Opus-Reasoning-Distilled-v2-bf16",
}

_STATUS_OK = {"status": "ok", "onboarded": True}


def _extract_requested_model(path: str, body: dict) -> str:
    if "models/" in path:
        return path.split("models/", 1)[1].split(":", 1)[0]
    body_model = body.get("model")
    if isinstance(body_model, str):
        return body_model.replace("models/", "")
    return "default"


def map_to_local_model(requested_model: str) -> str:
    for gemini_name, local_name in sorted(
        MODEL_MAP.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if gemini_name != "default" and gemini_name in requested_model:
            return local_name
    return MODEL_MAP["default"]


def gemini_contents_to_messages(contents: list[dict]) -> list[dict]:
    messages: list[dict] = []
    for content in contents:
        role = "assistant" if content.get("role") == "model" else "user"
        parts = content.get("parts", [])
        text = "".join(
            part.get("text", "") for part in parts if isinstance(part, dict)
        )
        messages.append({"role": role, "content": text})
    return messages


def build_openai_payload(path: str, body: dict) -> dict:
    parsed_path = urlparse(path).path
    requested_model = _extract_requested_model(parsed_path, body)
    return {
        "model": map_to_local_model(requested_model),
        "messages": gemini_contents_to_messages(body.get("contents", [])),
        "stream": "streamGenerateContent" in parsed_path
        or "StreamGenerateContent" in parsed_path,
    }


def translate_openai_response(data: dict) -> dict:
    choices = data.get("choices", [])
    if not choices:
        return {"error": data}
    content = choices[0].get("message", {}).get("content", "")
    return {
        "response": {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"text": content}],
                    },
                    "finishReason": "STOP",
                    "index": 0,
                    "safetyRatings": [],
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 0,
                "candidatesTokenCount": 0,
                "totalTokenCount": 0,
            },
        }
    }


def iter_gemini_stream_events(lines: Iterable[str]) -> Iterable[bytes]:
    for line in lines:
        if not line.startswith("data: "):
            continue
        if line == "data: [DONE]":
            break
        chunk = json.loads(line[6:])
        choices = chunk.get("choices", [])
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta", {})
        combined_text = (
            (delta.get("reasoning_content", "") or "")
            + (delta.get("content", "") or "")
        )
        finish_reason = choice.get("finish_reason")
        if not combined_text and not finish_reason:
            continue
        candidate = {"index": 0, "safetyRatings": []}
        if combined_text:
            candidate["content"] = {
                "role": "model",
                "parts": [{"text": combined_text}],
            }
        if finish_reason:
            candidate["finishReason"] = "STOP"
        yield (
            f"data: {json.dumps({'response': {'candidates': [candidate]}})}\n\n"
        ).encode("utf-8")
    yield b'data: {"response": {"candidates": [{"finishReason": "STOP"}]}}\n\n'


class GeminiShimHandler(BaseHTTPRequestHandler):
    server_version = "SpokeGeminiShim/0.1"

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def do_PUT(self) -> None:  # noqa: N802
        self._handle()

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw_body = self.rfile.read(length)
        if not raw_body:
            return {}
        return json.loads(raw_body.decode("utf-8"))

    def _write_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream_proxy(self, payload: dict) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
        with httpx.stream(
            "POST",
            TARGET_URL,
            json=payload,
            headers=headers,
            timeout=None,
        ) as resp:
            resp.raise_for_status()
            for chunk in iter_gemini_stream_events(resp.iter_lines()):
                self.wfile.write(chunk)
                self.wfile.flush()

    def _proxy_request(self, payload: dict) -> None:
        headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
        with httpx.Client(timeout=None) as client:
            resp = client.post(TARGET_URL, json=payload, headers=headers)
            resp.raise_for_status()
            self._write_json(translate_openai_response(resp.json()))

    def _handle(self) -> None:
        path = urlparse(self.path).path
        if any(
            marker in path
            for marker in ("loadCodeAssist", "listModels", "onboardUser")
        ):
            self._write_json(_STATUS_OK)
            return

        if "generateContent" not in path and "GenerateContent" not in path:
            self._write_json({"status": "ok"})
            return

        body = self._read_json_body()
        payload = build_openai_payload(path, body)
        if payload["stream"]:
            self._stream_proxy(payload)
            return
        self._proxy_request(payload)


def run_server(host: str = HOST, port: int = PORT) -> None:
    server = ThreadingHTTPServer((host, port), GeminiShimHandler)
    server.serve_forever()


if __name__ == "__main__":
    run_server()
