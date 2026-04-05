"""Terraform: epistaxis topoi parser and HUD panel.

Parses scoped local state from an epistaxis project note and renders
a scrollable sidebar showing active topoi with semeion names, status,
and current intent.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    resume_cmd: str | None = None
    status: str | None = None
    temperature: str | None = None
    attractors: list[str] = field(default_factory=list)
    machine: str | None = None
    tool: str | None = None
    all_semeions: list[str] = field(default_factory=list)


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
        if topos.all_semeions:
            topos.semeion = topos.all_semeions[0]

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

            # Status (the last "Status:" line wins)
            if content.startswith("Status:") or "Status:" in content:
                status_m = re.search(r"Status:\s*\**(.+)", content)
                if status_m:
                    # Strip bold markers
                    topos.status = re.sub(r"\*\*", "", status_m.group(1)).strip()

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

    return topoi


def load_topoi(
    path: str | Path | None = None,
) -> list[Topos]:
    """Load and parse topoi from an epistaxis note file.

    Parameters
    ----------
    path : str or Path, optional
        Override path to the epistaxis note. Defaults to
        ``~/dev/epistaxis/projects/spoke/epistaxis.md``.
    """
    note_path = Path(path) if path else _DEFAULT_EPISTAXIS_NOTE
    env_override = os.environ.get("SPOKE_EPISTAXIS_NOTE")
    if env_override:
        note_path = Path(env_override)

    if not note_path.exists():
        logger.warning("epistaxis note not found: %s", note_path)
        return []

    text = note_path.read_text(encoding="utf-8")
    return parse_topoi(text)


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
