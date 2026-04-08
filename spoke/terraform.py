"""Terraform: epistaxis topoi parser and HUD panel.

Parses scoped local state from an epistaxis project note and renders
a scrollable sidebar showing active topoi with semeion names, status,
and current intent.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

_DEFAULT_EPISTAXIS_NOTE = (
    Path.home() / "dev" / "epistaxis" / "projects" / "spoke" / "epistaxis.md"
)


@dataclass
class Topos:
    """A single parsed topos from epistaxis scoped local state."""

    id: str
    semeion: str | None = None
    branch: str | None = None
    worktree: str | None = None
    resume_cmd: str | None = None
    status: str | None = None
    temperature: str | None = None
    attractors: list[str] = field(default_factory=list)
    machine: str | None = None
    tool: str | None = None
    observed: str | None = None
    all_semeions: list[str] = field(default_factory=list)


_TAG_PATTERNS = re.compile(
    r"^(reboot|consult |see |pull |check |blocked|shared-surface|leaf \d|"
    r"operator-chord|launcher-teardown|finger-flounder-coverage|"
    r"test-isolation)",
    re.IGNORECASE,
)


def _is_tag_semeion(name: str) -> bool:
    """Return True if this semeion looks like an operational tag, not a name."""
    return bool(_TAG_PATTERNS.search(name.strip()))


def _clean_status(raw: str) -> str:
    """Strip markdown artifacts from status text."""
    s = re.sub(r"\*\*", "", raw)  # bold
    s = re.sub(r"`([^`]*)`", r"\1", s)  # backticks
    s = re.sub(r"~~([^~]*)~~", r"\1", s)  # strikethrough
    return s.strip()


def parse_topoi(text: str) -> list[Topos]:
    """Parse scoped local state entries from an epistaxis note.

    Looks for the ``## Scoped Local State`` section and extracts each
    ``### <id>`` subsection into a :class:`Topos`.
    """
    # Find the scoped local state section
    scoped_match = re.search(
        r"^## Scoped Local State\s*$", text, re.MULTILINE
    )
    if not scoped_match:
        return []

    scoped_start = scoped_match.end()

    # Find the next ## section (or end of file)
    next_section = re.search(r"^## (?!Scoped Local State)", text[scoped_start:], re.MULTILINE)
    scoped_text = text[scoped_start : scoped_start + next_section.start()] if next_section else text[scoped_start:]

    # Split into individual topos entries
    entries = re.split(r"^### ", scoped_text, flags=re.MULTILINE)
    topoi: list[Topos] = []

    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue

        lines = entry.split("\n")
        topos_id = lines[0].strip()

        # Skip non-topos content (italic notes, plain text, etc.)
        # Topos IDs start with a letter or digit, not underscore
        if not re.match(r"^[a-zA-Z0-9][\w-]*", topos_id):
            continue
        topos = Topos(id=topos_id)

        body = "\n".join(lines[1:])

        # Extract semeion names from [Sēmeion: ...] markers
        # Grab only the name part before any em-dash qualifier
        semeion_matches = re.findall(
            r"\[Sēmeion:\s*`?([^]`—]+)`?\s*(?:—[^]]*)?]", body
        )
        topos.all_semeions = [s.strip() for s in semeion_matches]
        # Pick the first semeion that looks like a name, not an instruction/tag
        for s in topos.all_semeions:
            if not _is_tag_semeion(s):
                topos.semeion = s
                break

        # Extract fields from bullet lines
        for line in lines[1:]:
            line = line.strip()
            if not line.startswith("- "):
                continue
            content = line[2:]

            # Branch
            branch_m = re.search(r"Branch:\s*`([^`]+)`", content)
            if branch_m and not topos.branch:
                topos.branch = branch_m.group(1)

            worktree_m = re.search(r"Worktree:\s*`([^`]+)`", content)
            if worktree_m and not topos.worktree:
                topos.worktree = worktree_m.group(1)

            # Resume / Continuation
            resume_m = re.search(
                r"(?:Resume|Continuation):\s*`([^`]+)`", content
            )
            if resume_m and not topos.resume_cmd:
                topos.resume_cmd = resume_m.group(1)

            # Temperature (may be in backticks or bold)
            temp_m = re.search(r"Temperature:\s*\**`?([^`*\s]+)`?\**", content)
            if temp_m and not topos.temperature:
                topos.temperature = temp_m.group(1)

            # Machine
            machine_m = re.search(r"Machine:\s*`([^`]+)`", content)
            if machine_m and not topos.machine:
                topos.machine = machine_m.group(1)

            # Tool
            tool_m = re.search(r"Tool:\s*`?([^`|]+)`?", content)
            if tool_m and not topos.tool:
                topos.tool = tool_m.group(1).strip()

            # Observed timestamp
            obs_m = re.search(r"Observed:\s*`?([^`\n]+)`?", content)
            if obs_m and not topos.observed:
                topos.observed = obs_m.group(1).strip()

            # Status (the last "Status:" line wins)
            if content.startswith("Status:") or "Status:" in content:
                status_m = re.search(r"Status:\s*\**(.+)", content)
                if status_m:
                    topos.status = _clean_status(status_m.group(1))
                    # Override temperature when status says settled/katástasis,
                    # even if an explicit Temperature: field was set — the status
                    # is the more recent signal.
                    status_lower = topos.status.lower()
                    if ("katástasis" in status_lower
                            or "κατάστασις" in status_lower
                            or "katastasis" in status_lower
                            or "settled" in status_lower):
                        topos.temperature = "katástasis"

            # Attractors
            attr_m = re.search(r"Attractors?:\s*(.+)", content)
            if attr_m and not topos.attractors:
                raw = attr_m.group(1)
                # Split on commas, strip backticks and strikethrough
                parts = re.split(r",\s*", raw)
                for part in parts:
                    clean = re.sub(r"[`~]", "", part).strip()
                    # Remove parenthetical suffixes
                    clean = re.sub(r"\s*\([^)]*\)\s*$", "", clean)
                    if clean:
                        topos.attractors.append(clean)

        topoi.append(topos)

    # Also parse the Katastasis section — entries there are settled regardless
    # of their format. They appear as bullet points: - **id** (date): text...
    kata_match = re.search(r"^## Katastasis\s*$", text, re.MULTILINE)
    if kata_match:
        kata_start = kata_match.end()
        kata_next = re.search(r"^## ", text[kata_start:], re.MULTILINE)
        kata_text = text[kata_start : kata_start + kata_next.start()] if kata_next else text[kata_start:]

        # Known active topos IDs — skip duplicates
        active_ids = {t.id.split(" ")[0].split("—")[0].strip() for t in topoi}

        for m in re.finditer(
            r"^- \*\*([a-zA-Z0-9][\w-]*)\*\*\s*(?:\(([^)]*)\))?:\s*(.*)",
            kata_text,
            re.MULTILINE,
        ):
            raw_id = m.group(1).strip()
            if raw_id in active_ids:
                continue  # already in scoped local state
            date = m.group(2) or ""
            description = m.group(3).strip()
            # Truncate long descriptions
            if len(description) > 80:
                description = description[:77] + "..."
            topos = Topos(
                id=raw_id,
                temperature="katástasis",
                status=description or f"Settled {date}".strip(),
                observed=date or None,
            )
            topoi.append(topos)

    return topoi


_DEFAULT_EPISTAXIS_REPO = Path.home() / "dev" / "epistaxis"
_DEFAULT_EPISTAXIS_REL = "projects/spoke/epistaxis.md"


def _fetch_remote_text(repo: Path, rel_path: str) -> str | None:
    """Fetch a file from origin/main without touching the worktree.

    Runs ``git fetch origin main`` (quiet, fast) then reads the file
    via ``git show origin/main:<path>``. Returns None on any failure.
    """
    try:
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "--quiet", "origin", "main"],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        logger.debug("git fetch failed for %s", repo, exc_info=True)
    # Even if fetch fails, try git show — we might have a recent fetch
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "show", f"origin/main:{rel_path}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        logger.debug("git show failed for %s:%s", repo, rel_path, exc_info=True)
    return None


_load_topoi_cache: list[Topos] | None = None
_load_topoi_cache_mtime: float = 0.0
_load_topoi_last_fetch: float = 0.0
_REMOTE_FETCH_INTERVAL = 60.0  # seconds between git fetch calls


def load_topoi(
    path: str | Path | None = None,
) -> list[Topos]:
    """Load and parse topoi from epistaxis.

    Uses the local file for fast-path reads (mtime check, no subprocess).
    Remote fetch runs at most once per 60s in the background to keep
    origin/main fresh without blocking the main thread.

    Parameters
    ----------
    path : str or Path, optional
        Override path to a local epistaxis note (bypasses remote fetch).
    """
    global _load_topoi_cache, _load_topoi_cache_mtime, _load_topoi_last_fetch
    import time

    env_override = os.environ.get("SPOKE_EPISTAXIS_NOTE")
    if path or env_override:
        note_path = Path(path or env_override)
        if not note_path.exists():
            logger.warning("epistaxis note not found: %s", note_path)
            return []
        text = note_path.read_text(encoding="utf-8")
        return parse_topoi(text)

    # Fast path: read local file, only re-parse if mtime changed
    local = _DEFAULT_EPISTAXIS_NOTE
    if local.exists():
        try:
            mtime = local.stat().st_mtime
        except OSError:
            mtime = 0.0
        if _load_topoi_cache is not None and mtime == _load_topoi_cache_mtime:
            return _load_topoi_cache
        text = local.read_text(encoding="utf-8")
        _load_topoi_cache = parse_topoi(text)
        _load_topoi_cache_mtime = mtime

    # Kick off a remote fetch periodically (non-blocking on the read path)
    now = time.monotonic()
    if now - _load_topoi_last_fetch > _REMOTE_FETCH_INTERVAL:
        _load_topoi_last_fetch = now
        try:
            import threading
            threading.Thread(
                target=_fetch_remote_text,
                args=(_DEFAULT_EPISTAXIS_REPO, _DEFAULT_EPISTAXIS_REL),
                daemon=True,
            ).start()
        except Exception:
            pass

    if _load_topoi_cache is not None:
        return _load_topoi_cache

    logger.warning("epistaxis note not found (remote or local)")
    return []


# Temperature sort order: hot first, then warm, cool, cold, katastasis last.
# Unknown temperatures sort between cold and katastasis.
_TEMP_SORT_ORDER = {
    "hot": 0,
    "warm": 1,
    "cool": 2,
    "cold": 3,
    "katástasis": 5,
}
_TEMP_UNKNOWN = 4


def sort_topoi(
    topoi: list[Topos],
    key: str = "temperature",
) -> list[Topos]:
    """Sort topoi by the given key.

    Supported keys:

    - ``"temperature"`` (default): hot → warm → cool → cold → unknown → katastasis
    - ``"semeion"``: alphabetical by display name (semeion or id)
    - ``"machine"``: group by machine, then by temperature within each group
    """
    if key == "temperature":
        return sorted(
            topoi,
            key=lambda t: _TEMP_SORT_ORDER.get(t.temperature or "", _TEMP_UNKNOWN),
        )
    elif key == "semeion":
        return sorted(
            topoi,
            key=lambda t: (t.semeion or t.id).lower(),
        )
    elif key == "machine":
        return sorted(
            topoi,
            key=lambda t: (
                t.machine or "zzz-unknown",
                _TEMP_SORT_ORDER.get(t.temperature or "", _TEMP_UNKNOWN),
            ),
        )
    return topoi


def filter_topoi(
    topoi: list[Topos],
    *,
    hide_katastasis: bool = False,
    machine: str | None = None,
    tool: str | None = None,
    temperature: str | None = None,
) -> list[Topos]:
    """Filter topoi by criteria.

    Parameters
    ----------
    hide_katastasis : bool
        If True, exclude topoi with temperature "katástasis".
    machine : str, optional
        If set, only include topoi from this machine (substring match).
    tool : str, optional
        If set, only include topoi using this tool (substring match, case-insensitive).
    temperature : str, optional
        If set, only include topoi with this exact temperature.
    """
    result = topoi
    if hide_katastasis:
        result = [t for t in result if t.temperature != "katástasis"]
    if machine:
        machine_lower = machine.lower()
        result = [
            t for t in result
            if t.machine and machine_lower in t.machine.lower()
        ]
    if tool:
        tool_lower = tool.lower()
        result = [
            t for t in result
            if t.tool and tool_lower in t.tool.lower()
        ]
    if temperature:
        result = [t for t in result if t.temperature == temperature]
    return result


@dataclass
class AttractorStats:
    """Counts of attractors by status."""

    total: int = 0
    active: int = 0
    unclassified: int = 0
    soak: int = 0
    smoke: int = 0
    katastasis: int = 0


def count_attractors(
    epistaxis_root: str | Path | None = None,
) -> AttractorStats:
    """Count attractors by status from frontmatter.

    Scans both ``attractors/`` (top-level, cross-repo) and
    ``projects/spoke/attractors/`` for ``.md`` files with YAML frontmatter.
    Files without a ``status:`` field are counted as active.
    """
    root = Path(epistaxis_root) if epistaxis_root else Path.home() / "dev" / "epistaxis"
    env_override = os.environ.get("SPOKE_EPISTAXIS_ROOT")
    if env_override:
        root = Path(env_override)

    stats = AttractorStats()
    dirs = [
        root / "attractors",
        root / "projects" / "spoke" / "attractors",
    ]
    seen: set[str] = set()  # dedup by filename

    for d in dirs:
        if not d.is_dir():
            continue
        for f in d.glob("*.md"):
            if f.name in seen:
                continue
            seen.add(f.name)
            stats.total += 1

            # Try to read status from frontmatter
            status = None  # None means no frontmatter status found
            try:
                head = f.read_text(encoding="utf-8", errors="replace")[:500]
                if head.startswith("---"):
                    end = head.find("---", 3)
                    if end != -1:
                        fm = head[3:end]
                        m = re.search(r"^status:\s*(.+)$", fm, re.MULTILINE)
                        if m:
                            status = m.group(1).strip().lower()
            except OSError:
                pass

            if status is None:
                stats.unclassified += 1
            elif status in ("soak", "soaking"):
                stats.soak += 1
            elif status in ("smoke", "smoking"):
                stats.smoke += 1
            elif status in ("katástasis", "katastasis", "settled"):
                stats.katastasis += 1
            else:
                stats.active += 1

    return stats


@dataclass(frozen=True)
class ResumePlan:
    """Concrete WezTerm action for re-entering a lane."""

    kind: str
    pane_id: int | None = None
    window_id: int | None = None
    cwd: str | None = None
    command: str | None = None
    reason: str | None = None


def _normalize_machine_name(name: str | None) -> str | None:
    if not name:
        return None
    normalized = name.strip().lower()
    if normalized.endswith(".local"):
        normalized = normalized[:-6]
    return normalized or None


def _normalize_path(path: str | None) -> str | None:
    if not path:
        return None
    parsed = urlparse(path)
    candidate = unquote(parsed.path) if parsed.scheme == "file" else path
    try:
        return str(Path(candidate).resolve())
    except OSError:
        return str(Path(candidate))


def _pane_location(pane: dict[str, Any]) -> tuple[str | None, str | None]:
    raw_cwd = pane.get("cwd")
    if not raw_cwd:
        return None, None
    parsed = urlparse(raw_cwd)
    host = _normalize_machine_name(parsed.hostname) if parsed.scheme == "file" else None
    return host, _normalize_path(raw_cwd)


def _focused_window_id(
    panes: list[dict[str, Any]],
    clients: list[dict[str, Any]],
) -> int | None:
    panes_by_id = {
        int(pane["pane_id"]): pane
        for pane in panes
        if pane.get("pane_id") is not None
    }
    for client in clients:
        focused = client.get("focused_pane_id")
        if focused is None:
            continue
        pane = panes_by_id.get(int(focused))
        if pane and pane.get("window_id") is not None:
            return int(pane["window_id"])
    active_panes = [pane for pane in panes if pane.get("is_active")]
    if active_panes:
        return int(active_panes[0]["window_id"])
    if panes and panes[0].get("window_id") is not None:
        return int(panes[0]["window_id"])
    return None


def _find_matching_pane(
    topos: Topos,
    panes: list[dict[str, Any]],
    *,
    current_machine: str,
    focused_window_id: int | None,
) -> dict[str, Any] | None:
    target_path = _normalize_path(topos.worktree)
    local_machine = _normalize_machine_name(current_machine)
    if not target_path or not local_machine:
        return None

    matches = []
    for pane in panes:
        pane_machine, pane_path = _pane_location(pane)
        if pane_path != target_path:
            continue
        if pane_machine and pane_machine != local_machine:
            continue
        matches.append(pane)

    if not matches:
        return None

    matches.sort(
        key=lambda pane: (
            pane.get("window_id") != focused_window_id,
            not pane.get("is_active", False),
            int(pane.get("pane_id", 0)),
        )
    )
    return matches[0]


def plan_resume_action(
    topos: Topos,
    panes: list[dict[str, Any]],
    clients: list[dict[str, Any]],
    *,
    current_machine: str | None = None,
) -> ResumePlan:
    """Choose whether to focus an existing WezTerm lane or spawn a new tab."""
    local_machine = current_machine or socket.gethostname()
    if not topos.resume_cmd:
        return ResumePlan(kind="unavailable", reason="missing_resume_cmd")
    if topos.machine and _normalize_machine_name(topos.machine) != _normalize_machine_name(local_machine):
        return ResumePlan(kind="unavailable", reason="machine_mismatch")

    focused_window_id = _focused_window_id(panes, clients)
    matching_pane = _find_matching_pane(
        topos,
        panes,
        current_machine=local_machine,
        focused_window_id=focused_window_id,
    )
    if matching_pane is not None:
        return ResumePlan(
            kind="focus_existing",
            pane_id=int(matching_pane["pane_id"]),
            window_id=int(matching_pane["window_id"]),
        )

    target_cwd = _normalize_path(topos.worktree)
    if not target_cwd:
        return ResumePlan(kind="unavailable", reason="missing_worktree")
    if focused_window_id is None:
        return ResumePlan(kind="unavailable", reason="missing_window")
    return ResumePlan(
        kind="spawn_new",
        window_id=focused_window_id,
        cwd=target_cwd,
        command=topos.resume_cmd,
    )


def _default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def apply_resume_plan(
    plan: ResumePlan,
    *,
    runner=_default_runner,
) -> bool:
    """Execute a WezTerm resume plan."""
    if plan.kind == "unavailable":
        logger.warning("Cannot resume topos in WezTerm: %s", plan.reason)
        return False

    if plan.kind == "focus_existing":
        primary = ["wezterm", "cli", "activate-pane", "--pane-id", str(plan.pane_id)]
    elif plan.kind == "spawn_new":
        primary = [
            "wezterm",
            "cli",
            "spawn",
            "--window-id",
            str(plan.window_id),
            "--cwd",
            str(plan.cwd),
            "/bin/zsh",
            "-lc",
            str(plan.command),
        ]
    else:
        logger.warning("Unknown WezTerm resume plan kind: %s", plan.kind)
        return False

    activate = ["osascript", "-e", 'tell application "WezTerm" to activate']
    primary_result = runner(primary)
    if getattr(primary_result, "returncode", 1) != 0:
        logger.warning("WezTerm command failed: %s", primary)
        return False
    activate_result = runner(activate)
    if getattr(activate_result, "returncode", 1) != 0:
        logger.warning("WezTerm activate failed")
        return False
    return True


def load_wezterm_state(
    *,
    runner=_default_runner,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return live WezTerm pane and client metadata."""
    panes_result = runner(["wezterm", "cli", "list", "--format", "json"])
    clients_result = runner(["wezterm", "cli", "list-clients", "--format", "json"])
    if getattr(panes_result, "returncode", 1) != 0:
        raise RuntimeError("wezterm cli list failed")
    if getattr(clients_result, "returncode", 1) != 0:
        raise RuntimeError("wezterm cli list-clients failed")
    return json.loads(panes_result.stdout), json.loads(clients_result.stdout)


def format_topos_summary(topos: Topos) -> str:
    """One-line summary for display."""
    name = topos.semeion or topos.id
    temp = f" [{topos.temperature}]" if topos.temperature else ""
    status_snippet = ""
    if topos.status:
        # Take first sentence or first 80 chars
        first_sentence = topos.status.split(". ")[0]
        if len(first_sentence) > 80:
            first_sentence = first_sentence[:77] + "..."
        status_snippet = f" — {first_sentence}"
    return f"{name}{temp}{status_snippet}"


def disambiguated_name(topos: Topos) -> str:
    """Display name with machine/tool suffix when semeion is shared or absent."""
    name = topos.semeion or topos.id
    parts = []
    if topos.machine:
        # Short hostname: "MacBook-Pro-2.local" → "MacBook-Pro-2"
        parts.append(topos.machine.split(".")[0])
    if topos.tool:
        # Short tool: "Claude Code (Opus 4.6)" → "Claude Code"
        parts.append(topos.tool.split("(")[0].strip())
    suffix = f"  ({', '.join(parts)})" if parts else ""
    return f"{name}{suffix}"
