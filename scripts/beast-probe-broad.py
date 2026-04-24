#!/usr/bin/env python3
"""Broad beast probe: run diverse samples from multiple days through the
full four-surface + beast pipeline.

Usage:
    uv run scripts/beast-probe-broad.py
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

_GRAPHEUS_DIR = Path.home() / "dev" / "grapheus" / "logs"
_ATTRACTORS_DIR = Path.home() / ".config" / "spoke" / "attractors"

# Diverse samples across days:
# 04-20/15: technical work (metal shaders, warping effects)
# 04-20/20: excitement about autonomous bug-finding agent
# 04-20/74: testing persistent chat ring buffer
# 04-20/78: Rocky movie quote / cultural reference
# 04-20/135: tool design discussion (compaction architecture)
# 04-20/137: asking about foot guns in tool design
# 04-23/19: subagent async reasoning
# 04-23/143: find attractor file ("the boys")
# 04-23/178: compact context + merge
SAMPLES_BY_DAY = {
    "2026-04-20": [15, 20, 74, 78, 135, 137],
    "2026-04-23": [19, 143, 178],
}

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
    for day, indices in SAMPLES_BY_DAY.items():
        log = _GRAPHEUS_DIR / f"grapheus-{day}.jsonl"
        if not log.exists():
            continue
        with open(log) as f:
            for i, line in enumerate(f):
                if i not in indices:
                    continue
                entry = json.loads(line)
                req = entry.get("request", {})
                msgs = req.get("messages", [])
                sys_msgs = [m for m in msgs if isinstance(m, dict) and m.get("role") == "system"]
                if any("attractor carver" in (m.get("content") or "") for m in sys_msgs):
                    continue
                user_msgs = [m for m in msgs if isinstance(m, dict) and m.get("role") == "user"]
                if not user_msgs:
                    continue
                samples.append({
                    "label": f"{day[-5:]}/{i}",
                    "user": user_msgs[-1].get("content", ""),
                })
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
        "stream": False, "temperature": 0.8, "top_p": 0.95, "top_k": 20, "repetition_penalty": 1.0,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        data=payload, headers=headers, method="POST",
    )
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
    print(f"Samples: {len(samples)}, Calls per sample: ~5")
    print(f"Estimated total time: {len(samples) * 2}–{len(samples) * 3} minutes\n")

    for sample in samples:
        print(f"{'='*70}")
        print(f"SAMPLE {sample['label']} ({len(sample['user'].split())}w)")
        print(f"  {sample['user'][:150]}...")
        print()

        candidates = []
        for i, (name, prompt, instruction) in enumerate(SURFACES):
            if i > 0:
                time.sleep(0.5)
            user_prompt = f"Current user utterance:\n\n\"{sample['user']}\"\n\n"
            if existing:
                user_prompt += f"{existing}\n\n"
            user_prompt += instruction

            print(f"  {name:10s}: ", end="", flush=True)
            try:
                raw, elapsed = _call(prompt, user_prompt)
                ops = _parse(raw)
                if not ops:
                    print(f"[]  ({elapsed:.1f}s)")
                    continue
                parts = []
                for op in ops:
                    slug = op.get("slug", "?")
                    op_type = op.get("op", "?")
                    candidates.append({"surface": name, "op": op})
                    parts.append(f"{op_type}:{slug}")
                print(f"{', '.join(parts)}  ({elapsed:.1f}s)")
            except Exception as e:
                print(f"ERROR: {e}")

        if not candidates:
            print("  No candidates — beast skipped.\n")
            continue

        # Beast pass
        print(f"\n  BEAST ({len(candidates)} candidates):")
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
                print(f"    Parse failed — all pass ({elapsed:.1f}s)")
            else:
                for v in verdicts:
                    idx = v.get("index", -1)
                    verdict = v.get("verdict", "?")
                    reason = v.get("reason", "")
                    if 0 <= idx < len(candidates):
                        c = candidates[idx]
                        slug = c["op"].get("slug", "?")
                        sym = {"pass": "+", "kill": "X"}.get(verdict, ">")
                        if verdict.startswith("reroute"):
                            sym = ">"
                        line = f"    [{sym}] {verdict:20s} {c['surface']:10s} {slug}"
                        print(line)
                        if reason:
                            print(f"        {reason[:120]}")
                print(f"    ({elapsed:.1f}s)")
        except Exception as e:
            print(f"    Beast ERROR: {e}")

        print()


if __name__ == "__main__":
    main()
