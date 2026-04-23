#!/usr/bin/env python3
"""Beast probe: run real Grapheus samples through all four carve surfaces,
then the beast species filter, and show what survives vs what gets killed.

Usage:
    uv run scripts/beast-probe.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import hashlib
import time
import urllib.request
from pathlib import Path

_GRAPHEUS_LOG = Path.home() / "dev" / "grapheus" / "logs" / "grapheus-2026-04-23.jsonl"
_ATTRACTORS_DIR = Path.home() / ".config" / "spoke" / "attractors"

_SAMPLE_INDICES = [19, 143, 178]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spoke.converge import (
    _CARVE_SYSTEM_PROMPT,
    _ANAMNESIS_SYSTEM_PROMPT,
    _TOPOS_SYSTEM_PROMPT,
    _POLICY_SYSTEM_PROMPT,
    _BEAST_SPECIES_PROMPT,
)

SURFACES = [
    ("attractor", _CARVE_SYSTEM_PROMPT, "Identify attractor operations for this utterance."),
    ("anamnesis", _ANAMNESIS_SYSTEM_PROMPT, "Extract factual observations worth remembering from this utterance."),
    ("topos", _TOPOS_SYSTEM_PROMPT, "Extract changes to the state of ongoing work from this utterance."),
    ("policy", _POLICY_SYSTEM_PROMPT, "Extract reasoning, rationales, or operational principles from this utterance."),
]


def _load_samples():
    samples = []
    with open(_GRAPHEUS_LOG) as f:
        for i, line in enumerate(f):
            if i not in _SAMPLE_INDICES:
                continue
            entry = json.loads(line)
            req = entry.get("request", {})
            msgs = req.get("messages", [])
            user_msgs = [m for m in msgs if isinstance(m, dict) and m.get("role") == "user"]
            if not user_msgs:
                continue
            samples.append({"index": i, "user": user_msgs[-1].get("content", "")})
    return samples


def _load_existing():
    if not _ATTRACTORS_DIR.is_dir():
        return ""
    lines = []
    for f in sorted(_ATTRACTORS_DIR.iterdir()):
        if f.is_file() and f.suffix == ".md":
            text = f.read_text(encoding="utf-8")
            title = f.stem
            for line in text.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            lines.append(f"- {f.stem}: {title}")
    return "Existing entries:\n" + "\n".join(lines) if lines else ""


def _call(system, user):
    t0 = time.time()
    base_url = os.environ.get("SPOKE_COMMAND_URL", "http://localhost:8090")
    api_key = os.environ.get("SPOKE_COMMAND_API_KEY") or os.environ.get("OMLX_SERVER_API_KEY", "")
    payload = json.dumps({
        "model": os.environ.get("SPOKE_COMMAND_MODEL", "Qwen3.6-35B-A3B-oQ8"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False, "temperature": 0.3,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(f"{base_url.rstrip('/')}/v1/chat/completions", data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = json.loads(resp.read())
    return body["choices"][0]["message"]["content"], time.time() - t0


def _parse(raw):
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        r = json.loads(cleaned)
        return [r] if isinstance(r, dict) else r
    except json.JSONDecodeError:
        return None


def main():
    samples = _load_samples()
    existing = _load_existing()
    # 4 carve passes + 1 beast pass per sample = 5 serial calls per sample
    print(f"Samples: {len(samples)}, Calls per sample: 5 (4 carve + 1 beast)")
    print(f"Staggering prefills by 0.5s between carve passes.\n")

    for sample in samples:
        print(f"{'='*70}")
        print(f"SAMPLE {sample['index']} ({len(sample['user'].split())}w)")
        print(f"  {sample['user'][:150]}...")
        print()

        # Phase 1: collect candidates from all four surfaces (staggered)
        candidates = []
        for i, (name, prompt, instruction) in enumerate(SURFACES):
            if i > 0:
                time.sleep(0.5)
            user_prompt = f"Current user utterance:\n\n\"{sample['user']}\"\n\n"
            if existing:
                user_prompt += f"{existing}\n\n"
            user_prompt += instruction

            print(f"  {name}: ", end="", flush=True)
            try:
                raw, elapsed = _call(prompt, user_prompt)
                ops = _parse(raw)
                if not ops:
                    print(f"[]  ({elapsed:.1f}s)")
                    continue
                for op in ops:
                    slug = op.get("slug", "?")
                    op_type = op.get("op", "?")
                    content = op.get("content", op.get("evidence", op.get("new_evidence", "")))
                    candidates.append({"surface": name, "op": op})
                    print(f"{op_type}:{slug}", end="  ")
                print(f"({elapsed:.1f}s)")
            except Exception as e:
                print(f"ERROR: {e}")

        if not candidates:
            print("\n  No candidates — beast pass skipped.\n")
            continue

        # Phase 2: beast species filter
        print(f"\n  --- BEAST ({len(candidates)} candidates) ---")
        candidate_lines = []
        for i, c in enumerate(candidates):
            op = c["op"]
            content = op.get("content", op.get("evidence", op.get("new_evidence", "")))
            candidate_lines.append(
                f"[{i}] surface={c['surface']} op={op.get('op','?')} slug={op.get('slug','?')}"
                + (f' content="{content[:100]}"' if content else "")
            )

        beast_prompt = (
            f"User utterance:\n\"{sample['user']}\"\n\n"
            f"Candidates ({len(candidates)}):\n"
            + "\n".join(candidate_lines)
            + "\n\nClassify each candidate."
        )

        try:
            raw, elapsed = _call(_BEAST_SPECIES_PROMPT, beast_prompt)
            verdicts = _parse(raw)
            if not verdicts:
                print(f"  Beast parse failed — all pass through ({elapsed:.1f}s)")
            else:
                for v in verdicts:
                    idx = v.get("index", -1)
                    verdict = v.get("verdict", "?")
                    reason = v.get("reason", "")
                    if 0 <= idx < len(candidates):
                        c = candidates[idx]
                        slug = c["op"].get("slug", "?")
                        marker = {"pass": "✓", "kill": "✗"}.get(verdict, "→") if not verdict.startswith("reroute") else "→"
                        if verdict.startswith("reroute"):
                            marker = "→"
                        print(f"  [{idx}] {marker} {verdict:20s} {c['surface']:10s} {slug}")
                        if reason:
                            print(f"      reason: {reason}")
                print(f"  ({elapsed:.1f}s)")
        except Exception as e:
            print(f"  Beast ERROR: {e}")

        print()


if __name__ == "__main__":
    main()
