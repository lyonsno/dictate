from __future__ import annotations

from unittest.mock import Mock, call

import spoke.terraform as mod
from spoke.terraform import Topos


def test_plan_resume_action_prefers_existing_lane_pane():
    topos = Topos(
        id="cc-terror-form-resume-tab-0408",
        machine="nlm2pr.local",
        worktree="/private/tmp/donttype-terror-form-resume-tab-0408",
        resume_cmd="codex resume 019d6db2-b8d0-7623-83da-ea76d459b9cc",
    )
    panes = [
        {
            "pane_id": 18,
            "tab_id": 17,
            "window_id": 2,
            "cwd": "file://nlm2pr.local/private/tmp/donttype-terror-form-resume-tab-0408",
            "title": "Terror Form work",
        }
    ]
    clients = [{"focused_pane_id": 15}]

    plan = mod.plan_resume_action(topos, panes, clients, current_machine="nlm2pr.local")

    assert plan.kind == "focus_existing"
    assert plan.pane_id == 18
    assert plan.window_id == 2


def test_plan_resume_action_spawns_in_focused_window_when_lane_not_open():
    topos = Topos(
        id="cc-terror-form-resume-tab-0408",
        machine="nlm2pr.local",
        worktree="/private/tmp/donttype-terror-form-resume-tab-0408",
        resume_cmd="codex resume 019d6db2-b8d0-7623-83da-ea76d459b9cc",
    )
    panes = [
        {
            "pane_id": 18,
            "tab_id": 17,
            "window_id": 2,
            "cwd": "file://nlm2pr.local/Users/noahlyons/dev/donttype",
            "title": "main checkout",
        }
    ]
    clients = [{"focused_pane_id": 18}]

    plan = mod.plan_resume_action(topos, panes, clients, current_machine="nlm2pr.local")

    assert plan.kind == "spawn_new"
    assert plan.window_id == 2
    assert plan.cwd == "/private/tmp/donttype-terror-form-resume-tab-0408"
    assert plan.command == "codex resume 019d6db2-b8d0-7623-83da-ea76d459b9cc"


def test_plan_resume_action_rejects_remote_machine_lane():
    topos = Topos(
        id="cc-remote-0408",
        machine="MacBook-Pro-2.local",
        worktree="/private/tmp/donttype-remote-0408",
        resume_cmd="codex resume remote",
    )
    panes = []
    clients = [{"focused_pane_id": 18}]

    plan = mod.plan_resume_action(topos, panes, clients, current_machine="nlm2pr.local")

    assert plan.kind == "unavailable"
    assert plan.reason == "machine_mismatch"


def test_apply_resume_plan_focuses_existing_pane_then_activates_wezterm():
    runner = Mock(return_value=Mock(returncode=0))
    plan = mod.plan_resume_action(
        Topos(
            id="cc-terror-form-resume-tab-0408",
            machine="nlm2pr.local",
            worktree="/private/tmp/donttype-terror-form-resume-tab-0408",
            resume_cmd="codex resume 019d6db2-b8d0-7623-83da-ea76d459b9cc",
        ),
        panes=[
            {
                "pane_id": 18,
                "tab_id": 17,
                "window_id": 2,
                "cwd": "file://nlm2pr.local/private/tmp/donttype-terror-form-resume-tab-0408",
            }
        ],
        clients=[{"focused_pane_id": 15}],
        current_machine="nlm2pr.local",
    )

    assert mod.apply_resume_plan(plan, runner=runner) is True
    assert runner.call_args_list == [
        call(["wezterm", "cli", "activate-pane", "--pane-id", "18"]),
        call(["osascript", "-e", 'tell application "WezTerm" to activate']),
    ]


def test_apply_resume_plan_spawns_tab_then_activates_wezterm():
    runner = Mock(return_value=Mock(returncode=0))
    plan = mod.plan_resume_action(
        Topos(
            id="cc-terror-form-resume-tab-0408",
            machine="nlm2pr.local",
            worktree="/private/tmp/donttype-terror-form-resume-tab-0408",
            resume_cmd="codex resume 019d6db2-b8d0-7623-83da-ea76d459b9cc",
        ),
        panes=[
            {
                "pane_id": 18,
                "tab_id": 17,
                "window_id": 2,
                "cwd": "file://nlm2pr.local/Users/noahlyons/dev/donttype",
            }
        ],
        clients=[{"focused_pane_id": 18}],
        current_machine="nlm2pr.local",
    )

    assert mod.apply_resume_plan(plan, runner=runner) is True
    assert runner.call_args_list == [
        call(
            [
                "wezterm",
                "cli",
                "spawn",
                "--window-id",
                "2",
                "--cwd",
                "/private/tmp/donttype-terror-form-resume-tab-0408",
                "/bin/zsh",
                "-lc",
                "codex resume 019d6db2-b8d0-7623-83da-ea76d459b9cc",
            ]
        ),
        call(["osascript", "-e", 'tell application "WezTerm" to activate']),
    ]
