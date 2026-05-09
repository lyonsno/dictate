"""SDK-backed coding-agent sessions for the operator shell."""

from __future__ import annotations

import asyncio
import importlib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


_ALLOWED_PROVIDERS = {"claude", "codex"}


class AgentSDKUnavailable(RuntimeError):
    """Raised when an optional provider SDK is not installed or not ready."""


@dataclass(frozen=True)
class AgentSDKRunResult:
    provider: str
    session_id: str | None
    final_response: str


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _message_text(message: Any) -> str:
    result = getattr(message, "result", None)
    if isinstance(result, str):
        return result
    content = getattr(message, "content", None)
    if isinstance(content, list):
        parts = []
        for block in content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
    return ""


def _message_session_id(message: Any) -> str | None:
    data = getattr(message, "data", None)
    if isinstance(data, dict):
        session_id = data.get("session_id")
        if isinstance(session_id, str) and session_id:
            return session_id
    session_id = getattr(message, "session_id", None)
    if isinstance(session_id, str) and session_id:
        return session_id
    return None


async def _run_claude_agent_sdk_async(
    *,
    prompt: str,
    cwd: str,
    resume_id: str | None,
    cancel_check: Callable[[], bool] | None,
) -> AgentSDKRunResult:
    try:
        sdk = importlib.import_module("claude_agent_sdk")
    except ImportError as exc:
        raise AgentSDKUnavailable(
            "claude-agent-sdk is not installed; install it to enable Claude Agent SDK sessions"
        ) from exc

    options_kwargs: dict[str, Any] = {
        "cwd": cwd,
        "allowed_tools": ["Read", "Glob", "Grep", "Bash", "Edit", "Write"],
        "permission_mode": "default",
    }
    if resume_id:
        options_kwargs["resume"] = resume_id
    options = sdk.ClaudeAgentOptions(**options_kwargs)

    final_response = ""
    provider_session_id = resume_id
    async for message in sdk.query(prompt=prompt, options=options):
        if cancel_check is not None and cancel_check():
            break
        provider_session_id = _message_session_id(message) or provider_session_id
        text = _message_text(message)
        if text:
            final_response = text
    return AgentSDKRunResult(
        provider="claude",
        session_id=provider_session_id,
        final_response=final_response,
    )


def _run_claude_agent_sdk(
    *,
    prompt: str,
    cwd: str,
    resume_id: str | None,
    cancel_check: Callable[[], bool] | None,
) -> AgentSDKRunResult:
    return asyncio.run(
        _run_claude_agent_sdk_async(
            prompt=prompt,
            cwd=cwd,
            resume_id=resume_id,
            cancel_check=cancel_check,
        )
    )


def _run_codex_sdk(
    *,
    prompt: str,
    cwd: str,
    resume_id: str | None,
    cancel_check: Callable[[], bool] | None,
) -> AgentSDKRunResult:
    try:
        sdk = importlib.import_module("codex_app_server")
    except ImportError as exc:
        raise AgentSDKUnavailable(
            "codex_app_server is not installed; install the experimental Codex Python SDK "
            "from a local open-source Codex checkout or use the TypeScript @openai/codex-sdk bridge"
        ) from exc

    if cancel_check is not None and cancel_check():
        return AgentSDKRunResult(provider="codex", session_id=resume_id, final_response="")

    with sdk.Codex() as codex:
        if resume_id and hasattr(codex, "resume_thread"):
            thread = codex.resume_thread(resume_id)
        elif resume_id and hasattr(codex, "thread_resume"):
            thread = codex.thread_resume(resume_id)
        else:
            try:
                thread = codex.thread_start(cwd=cwd)
            except TypeError:
                thread = codex.thread_start()
        result = thread.run(prompt)

    session_id = (
        getattr(result, "thread_id", None)
        or getattr(thread, "id", None)
        or getattr(thread, "thread_id", None)
        or resume_id
    )
    final_response = getattr(result, "final_response", None)
    if final_response is None:
        final_response = getattr(result, "output_text", None)
    if final_response is None:
        final_response = str(result)
    return AgentSDKRunResult(
        provider="codex",
        session_id=session_id,
        final_response=final_response,
    )


def run_agent_sdk_session(
    provider: str,
    prompt: str,
    cwd: str,
    resume_id: str | None,
    cancel_check: Callable[[], bool] | None = None,
) -> AgentSDKRunResult:
    provider = provider.strip().lower()
    if provider == "claude":
        return _run_claude_agent_sdk(
            prompt=prompt,
            cwd=cwd,
            resume_id=resume_id,
            cancel_check=cancel_check,
        )
    if provider == "codex":
        return _run_codex_sdk(
            prompt=prompt,
            cwd=cwd,
            resume_id=resume_id,
            cancel_check=cancel_check,
        )
    raise ValueError(f"Unsupported SDK agent provider: {provider}")


class AgentSDKManager:
    """Track operator-owned SDK agent sessions."""

    def __init__(
        self,
        *,
        sdk_runner: Callable[
            [str, str, str, str | None, Callable[[], bool]],
            AgentSDKRunResult,
        ] = run_agent_sdk_session,
        thread_factory: Callable[..., Any] = threading.Thread,
    ):
        self._sdk_runner = sdk_runner
        self._thread_factory = thread_factory
        self._lock = threading.Lock()
        self._counter = 0
        self._sessions: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []

    def launch(
        self,
        *,
        provider: str,
        prompt: str,
        cwd: str,
        resume_id: str | None = None,
    ) -> dict[str, Any]:
        provider = provider.strip().lower() if isinstance(provider, str) else ""
        if provider not in _ALLOWED_PROVIDERS:
            raise ValueError(f"Unsupported SDK agent provider: {provider}")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if not isinstance(cwd, str) or not cwd.strip():
            raise ValueError("cwd must be a non-empty string")
        resume_id = (
            resume_id.strip()
            if isinstance(resume_id, str) and resume_id.strip()
            else None
        )

        with self._lock:
            self._counter += 1
            session_id = f"sdk-agent-{provider}-{self._counter}"
            cancel_event = threading.Event()
            session = {
                "id": session_id,
                "provider": provider,
                "prompt": prompt.strip(),
                "cwd": cwd.strip(),
                "resume_id": resume_id,
                "state": "queued",
                "created_at": _iso_now(),
                "started_at": None,
                "finished_at": None,
                "provider_session_id": None,
                "result": None,
                "error": None,
                "sdk_unavailable": False,
                "_cancel_event": cancel_event,
            }
            self._sessions[session_id] = session
            self._order.insert(0, session_id)

        thread = self._thread_factory(
            target=self._run_session,
            args=(session_id,),
            daemon=True,
        )
        thread.start()
        return self._public_session(session)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                self._public_session(self._sessions[session_id])
                for session_id in self._order
            ]

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {"error": f"Unknown SDK agent session: {session_id}"}
            return self._public_session(session)

    def cancel(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {"error": f"Unknown SDK agent session: {session_id}"}
            if session["state"] in {"completed", "failed", "cancelled"}:
                return self._public_session(session)
            session["_cancel_event"].set()
            session["state"] = "cancelling"
            return self._public_session(session)

    def _run_session(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions[session_id]
            if session["_cancel_event"].is_set():
                session["state"] = "cancelled"
                session["finished_at"] = _iso_now()
                return
            session["state"] = "running"
            session["started_at"] = _iso_now()
            provider = session["provider"]
            prompt = session["prompt"]
            cwd = session["cwd"]
            resume_id = session["resume_id"]
            cancel_event = session["_cancel_event"]

        try:
            result = self._sdk_runner(
                provider,
                prompt,
                cwd,
                resume_id,
                cancel_event.is_set,
            )
        except AgentSDKUnavailable as exc:
            with self._lock:
                session = self._sessions[session_id]
                if session["_cancel_event"].is_set():
                    session["state"] = "cancelled"
                else:
                    session["state"] = "failed"
                    session["error"] = str(exc)
                    session["sdk_unavailable"] = True
                session["finished_at"] = _iso_now()
            return
        except Exception as exc:
            with self._lock:
                session = self._sessions[session_id]
                if session["_cancel_event"].is_set():
                    session["state"] = "cancelled"
                else:
                    session["state"] = "failed"
                    session["error"] = str(exc)
                session["finished_at"] = _iso_now()
            return

        with self._lock:
            session = self._sessions[session_id]
            if session["_cancel_event"].is_set():
                session["state"] = "cancelled"
            else:
                session["state"] = "completed"
                session["provider_session_id"] = result.session_id
                session["result"] = result.final_response
            session["finished_at"] = _iso_now()

    @staticmethod
    def _public_session(session: dict[str, Any]) -> dict[str, Any]:
        result = session.get("result")
        preview = None
        if isinstance(result, str) and result:
            preview = result[:160]
        poll_hint = None
        if session["state"] in {"queued", "running", "cancelling"}:
            poll_hint = (
                "SDK agent still in flight. Continue other work and check "
                "again later when useful."
            )
        return {
            "id": session["id"],
            "provider": session["provider"],
            "prompt": session["prompt"],
            "cwd": session["cwd"],
            "resume_id": session["resume_id"],
            "state": session["state"],
            "created_at": session["created_at"],
            "started_at": session["started_at"],
            "finished_at": session["finished_at"],
            "provider_session_id": session["provider_session_id"],
            "result": result,
            "result_preview": preview,
            "error": session.get("error"),
            "sdk_unavailable": bool(session.get("sdk_unavailable")),
            "poll_hint": poll_hint,
        }
