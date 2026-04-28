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

## Modal Agent Shell Sessions

`spoke` carries SDK-backed coding-agent transport for Claude Agent SDK and
Codex SDK, but those providers are not generic tools for the default assistant
to call. The operator-facing contract is **Agent Shell**: a modal route
destination where ordinary input goes to the selected Claude/Codex session,
while Spoke-owned control input and Epistaxis-shaped verbs remain under the
operator shell.

The menubar exposes an `Agent Shell` provider selector (`Off`, `Claude Agent
SDK`, `Codex SDK`). This is intentionally separate from `Assistant Backend`:
the local assistant remains the fuzzy-intent resolver and router, while
Claude/Codex are modal worker shells selected by route/mode state.

The lower-level provider contract recognizes `claude` for Claude Agent SDK and
`codex` for Codex SDK. Provider sessions are asynchronous, keep Spoke-owned ids
distinct from provider session/thread ids, carry the requested working
directory, and surface SDK-unavailable failures as operator-visible state
rather than as raw terminal-command failures.

Provider SDK packages are optional runtime dependencies. The command shell can
boot without them; activating a provider whose SDK is absent should produce a
clear failed session with `sdk_unavailable=true` once the provider launch path
is connected to the modal router.
