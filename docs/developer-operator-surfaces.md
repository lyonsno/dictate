# Developer And Operator Surfaces

This document holds real `spoke` capabilities that do not belong on the
public README but still need a durable canonical home.

## Bounded Post-Transcription Repair Pass

`spoke` keeps a bounded post-transcription repair pass for recurring
project-specific vocabulary observed in real logs.

This is a developer-facing correction surface, not a public product promise.
The implementation currently lives in [`spoke/dedup.py`](../spoke/dedup.py),
and README omission is intentional unless the repair pass becomes a visible
user-facing control or configuration surface.

## SDK-Backed Agent Sessions

`spoke` exposes operator-owned SDK coding-agent sessions through the command
tool surface:

- `launch_agent_session`
- `list_agent_sessions`
- `get_agent_session_result`
- `cancel_agent_session`

The provider contract currently recognizes `claude` for Claude Agent SDK and
`codex` for Codex SDK. Sessions are asynchronous, keep Spoke-owned ids distinct
from provider session/thread ids, carry the requested working directory, and
surface SDK-unavailable failures as operator-visible state rather than as raw
terminal-command failures.

Provider SDK packages are optional runtime dependencies. The command shell can
boot without them; launching a provider whose SDK is absent produces a clear
failed session with `sdk_unavailable=true`.
