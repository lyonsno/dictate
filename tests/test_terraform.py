"""Tests for the Terraform epistaxis topoi parser."""

from spoke.terraform import Topos, parse_topoi, format_topos_summary


_SAMPLE_NOTE = """\
# Spoke Epistaxis

## Status

- **`origin/main-next` at `405a0e1`.**

## Scoped Local State

### cc-ham-hogg-0402
- Machine: `MacBook-Pro-2.local` | Tool: Claude Code (Opus 4.6)
- Checkout: `/Users/dev/donttype` | Branch: `ham-hogg-0402` | Worktree: `/tmp/spoke-ham-hogg-0402`
- Continuation: `codex resume 019d4bf1-1303-7053-9c37-f8f36fc5d720`
- Temperature: `hot`
- Attractors: `support-spoke-process-heartbeat_2026-04-02`, ~~`stop-test-killing-live_2026-04-02`~~ (test-kills-live → **katástasis**)
- [Sēmeion: `Operation Ham-Hogg`]
- [Sēmeion: `Operation Wet Nurse` — triage squadron for Careless Whisper fallout]
- Status: **Active.** Heartbeat + model TTL landed on `dev-0402`.

### cc-panic-switch-0404
- Session ID: `214778e9` | Machine: `MacBook-Pro-2.local` | Tool: Claude Code (Opus 4.6)
- Checkout: `/Users/dev/donttype` | Branch: `cc/panic-switch-0404` | Worktree: `/tmp/spoke-panic-switch-0404`
- Continuation: `claude -r 214778e9-5203-47f6-b791-f436dcbc2694`
- Temperature: `hot`
- Attractors: `stop-tool-call-parser-drop_2026-04-03`, `support-cancel-generation_2026-04-03`
- [Sēmeion: `Operation Panic Switch`]
- Status: **Active.** Fix for silent tool-call drop plus cancel chord landed.

### project-friendly-snoop-0402
- Session ID: `session-386e5f84` | Machine: `darwin` | Tool: `Gemini CLI`
- Temperature: **katástasis**
- Attractors: ~~`allow-operator-shell-to-query-gmail_2026-03-29`~~ (satisfied)
- [Sēmeion: Project Friendly Snoop]
- Status: **Katástasis.** Gmail operator merged.

## Decisions

- Some decisions here.
"""


def test_parse_topoi_count():
    topoi = parse_topoi(_SAMPLE_NOTE)
    assert len(topoi) == 3


def test_parse_topos_id():
    topoi = parse_topoi(_SAMPLE_NOTE)
    assert topoi[0].id == "cc-ham-hogg-0402"
    assert topoi[1].id == "cc-panic-switch-0404"
    assert topoi[2].id == "project-friendly-snoop-0402"


def test_parse_semeion():
    topoi = parse_topoi(_SAMPLE_NOTE)
    assert topoi[0].semeion == "Operation Ham-Hogg"
    assert topoi[1].semeion == "Operation Panic Switch"
    assert topoi[2].semeion == "Project Friendly Snoop"


def test_parse_all_semeions():
    topoi = parse_topoi(_SAMPLE_NOTE)
    assert topoi[0].all_semeions == ["Operation Ham-Hogg", "Operation Wet Nurse"]


def test_parse_branch():
    topoi = parse_topoi(_SAMPLE_NOTE)
    assert topoi[0].branch == "ham-hogg-0402"
    assert topoi[1].branch == "cc/panic-switch-0404"


def test_parse_resume_cmd():
    topoi = parse_topoi(_SAMPLE_NOTE)
    assert topoi[0].resume_cmd == "codex resume 019d4bf1-1303-7053-9c37-f8f36fc5d720"
    assert topoi[1].resume_cmd == "claude -r 214778e9-5203-47f6-b791-f436dcbc2694"


def test_parse_temperature():
    topoi = parse_topoi(_SAMPLE_NOTE)
    assert topoi[0].temperature == "hot"
    assert topoi[2].temperature == "katástasis"


def test_parse_machine():
    topoi = parse_topoi(_SAMPLE_NOTE)
    assert topoi[0].machine == "MacBook-Pro-2.local"


def test_parse_tool():
    topoi = parse_topoi(_SAMPLE_NOTE)
    assert topoi[0].tool == "Claude Code (Opus 4.6)"
    assert topoi[2].tool == "Gemini CLI"


def test_parse_status():
    topoi = parse_topoi(_SAMPLE_NOTE)
    assert topoi[0].status.startswith("Active.")
    assert "Katástasis." in topoi[2].status


def test_parse_attractors():
    topoi = parse_topoi(_SAMPLE_NOTE)
    assert "support-spoke-process-heartbeat_2026-04-02" in topoi[0].attractors
    # Strikethrough attractors are still parsed (just without ~~)
    assert "stop-test-killing-live_2026-04-02" in topoi[0].attractors


def test_format_topos_summary_with_semeion():
    topos = Topos(
        id="cc-ham-hogg-0402",
        semeion="Operation Ham-Hogg",
        temperature="hot",
        status="Active. Heartbeat landed.",
    )
    summary = format_topos_summary(topos)
    assert "Operation Ham-Hogg" in summary
    assert "[hot]" in summary
    assert "Active" in summary


def test_format_topos_summary_without_semeion():
    topos = Topos(id="cc-something-0404")
    summary = format_topos_summary(topos)
    assert summary == "cc-something-0404"


def test_parse_empty_scoped_state():
    text = """\
# Spoke Epistaxis

## Scoped Local State

_No active lanes._

## Decisions
"""
    topoi = parse_topoi(text)
    assert topoi == []


def test_parse_no_scoped_state_section():
    text = "# Spoke Epistaxis\n\n## Decisions\n\n- stuff\n"
    topoi = parse_topoi(text)
    assert topoi == []
