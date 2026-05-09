"""Tests for Agent Shell thread-card waypoint extraction and card state."""

from __future__ import annotations


def test_thread_card_uses_orientation_as_bearing_and_completed_state_as_ready():
    from spoke.agent_thread_cards import build_agent_thread_card

    card = build_agent_thread_card(
        {
            "id": "agent-backend-codex-1",
            "provider": "codex",
            "state": "completed",
            "prompt": "build the thread card",
            "result": "Done. The card contract is implemented.",
            "backend_events": [
                {
                    "sequence": 1,
                    "kind": "agent_message",
                    "text": (
                        "**Current intent**\n"
                        "Session: build Agent Shell cards.\n"
                        "Repo/task: Spoke Spinal Tap worktree.\n"
                        "Immediate next step: verify tests."
                    ),
                    "data": {"id": "msg-1"},
                },
                {
                    "sequence": 2,
                    "kind": "command_execution",
                    "data": {
                        "command": "uv run pytest -q tests/test_agent_thread_cards.py",
                        "status": "completed",
                    },
                },
            ],
        }
    )

    assert card.thread_id == "agent-backend-codex-1"
    assert card.readiness == "ready"
    assert card.title == "build Agent Shell cards"
    assert card.bearing.startswith("Session: build Agent Shell cards.")
    assert card.activity_line == "Command completed"
    assert card.latest_response == "Done. The card contract is implemented."


def test_selected_resting_display_exposes_latest_real_response():
    from spoke.agent_thread_cards import build_agent_thread_card, card_display_contract

    card = build_agent_thread_card(
        {
            "id": "agent-backend-codex-1",
            "provider": "codex",
            "state": "completed",
            "prompt": "summarize the packet",
            "result": "Here is the real Codex response, not a bearing summary.",
            "backend_events": [
                {
                    "sequence": 2,
                    "kind": "thread_waypoint",
                    "text": "Session: summarize packet\nImmediate next step: hand off",
                    "data": {
                        "kind": "current_intent",
                        "text": "Session: summarize packet\nImmediate next step: hand off",
                        "source": "fixture",
                    },
                }
            ],
        }
    )

    display = card_display_contract(card, selected=True)

    assert display["display_state"] == "selected_resting"
    assert display["show_latest_response"] is True
    assert display["primary_text"] == "Here is the real Codex response, not a bearing summary."
    assert display["compact_text"] == "summarize packet · Ready to read"
    assert "summarize packet" in display["bearing"]
