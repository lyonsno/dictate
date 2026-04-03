---
type: anaphora
repo: spoke
branch: gemini/careless-whisper-0402
leaf: 4
scope: spoke/command_overlay.py
target_commit: 84bcc17
status: active
created: 2026-04-03
---

# Anaphora: spoke careless whisper leaf 4 command overlay review

Scope: `spoke/command_overlay.py` dismiss-motion retune in `84bcc17` cross-referenced with `tests/test_command_overlay.py`.

## Findings

No material findings in the reviewed slice.

## Verification evidence

- Reviewed `git show 84bcc17 -- spoke/command_overlay.py tests/test_command_overlay.py`.
- Cross-checked the live branch version of `spoke/command_overlay.py` for dismiss lifecycle interactions with `show()`, `hide()`, `finish()`, `_cancel_all_timers()`, and `_set_overlay_scale()`.
- Ran `uv run pytest -q tests/test_command_overlay.py` -> `35 passed in 0.12s`.

## Notes

- The retune is narrower than it first looks: it replaces the old hold-then-fade path with a deterministic grow-then-shrink helper, resets scale on setup/show/animation completion, and explicitly clears the dismiss timer through `_cancel_dismiss_animation()`.
- The updated tests cover the new phase boundaries, completion behavior, and timer cancellation for this path.
