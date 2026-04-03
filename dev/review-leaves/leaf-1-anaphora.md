# Leaf 1 Anaphora

## Scope

Reviewed Gemini's `spoke/__main__.py` changes from:

- `30d661e` — VAD state gating
- `a2b6c99` — glow gating behind VAD state
- `7dfe889` — 5s grace period and menubar telemetry
- `fed9575` — purported menubar import fix

## Findings

### 1. `fed9575` leaves `spoke/__main__.py` unparsable in multiple places

Severity: critical

Evidence:

- `python3 -m py_compile /private/tmp/spoke-careless-whisper-0402/spoke/__main__.py`
  fails immediately with `IndentationError: unexpected indent (__main__.py, line 205)`.
- The current file also contains the same bad extra-indent pattern at
  `spoke/__main__.py:390`, `spoke/__main__.py:401`, and `spoke/__main__.py:416`.
- `spoke/__main__.py:715` is a malformed duplicate signature:
  `def amplitudeUpdate_(self, rms_number) -> None:(self, rms_number) -> None:`

Why this matters:

- The branch cannot import `spoke.__main__`, so the whole leaf is dead on arrival.
- Even after fixing line 205, the later bad indents and malformed function
  definition would still prevent the file from compiling cleanly.

Commit linkage:

- The extra-indented `_mic_probe_in_flight` lines and surrounding corruption were
  introduced by `fed9575`.

### 2. The VAD "start true for grace period" change is immediately overwritten

Severity: high

Evidence:

- In the trusted pre-`fed9575` history, `7dfe889` added:
  `self._is_speech = True  # Start true for grace period`
- In the current leaf, the hold-start path now sets:
  - `spoke/__main__.py:649` `self._is_speech = True`
  - then immediately starts segmented-preview state
  - and no preserved grace-period logic remains coherent with the merged code
- In the parent state before `fed9575`, the same block already showed the bug
  explicitly:
  it set `_is_speech = True` and then immediately reset `_is_speech = False`.

Why this matters:

- The 5-second grace-period feature from `7dfe889` is not actually in effect.
- Preview gating and glow gating can fall back to "silence" immediately at the
  start of recording instead of honoring the intended initial speech window.

Commit linkage:

- The broken interaction is between `7dfe889` and the later rewrite in `fed9575`.

### 3. Segmented preview transcription cannot work as written

Severity: high

Evidence:

- The new batch preview path uses `np.concatenate(...)` at
  `spoke/__main__.py:899`, but `__main__.py` does not import NumPy anywhere.
- The segment worker exists as `_segment_transcribe_worker`, but there is no
  call site that creates or starts `self._segment_worker_thread`.
  A repo-wide search in this file finds only:
  - the field declarations,
  - the worker method definition,
  - `self._segment_queue.put(wav_bytes)`,
  - and `self._segment_queue.put(None)` on hold end.

Why this matters:

- Any path that reaches `np.concatenate(...)` will raise `NameError: name 'np' is
  not defined`.
- Even before that, opportunistic segment transcription never runs, because
  queued segments are never consumed by a started worker.
- On hold end, `self._segment_queue.put(None)` permanently poisons the queue for
  any future worker started against the same queue instance.

Commit linkage:

- This is part of the segmented-preview plumbing layered into the file after
  `30d661e`/`7dfe889` and left incoherent by the current merged state.

## Commands run

- `python3 -m py_compile /private/tmp/spoke-careless-whisper-0402/spoke/__main__.py` — failed with `IndentationError` at line 205
- `git -C /private/tmp/spoke-careless-whisper-0402 show 30d661e -- spoke/__main__.py`
- `git -C /private/tmp/spoke-careless-whisper-0402 show a2b6c99 -- spoke/__main__.py`
- `git -C /private/tmp/spoke-careless-whisper-0402 show 7dfe889 -- spoke/__main__.py`
- `git -C /private/tmp/spoke-careless-whisper-0402 show fed9575 -- spoke/__main__.py`
- `git -C /private/tmp/spoke-careless-whisper-0402 show fed9575^:spoke/__main__.py | sed -n '560,760p'`
- targeted `rg`/`nl` inspection of the current `spoke/__main__.py`

## Conclusion

Leaf 1 is not a "single indent fix." `fed9575` left `spoke/__main__.py` in a
badly merged state with parser errors, and the later VAD/segmented-preview
plumbing is not internally coherent. The material fixes for this leaf should be:

1. restore a syntactically valid file,
2. make the VAD grace-period state transition real instead of self-canceling,
3. either complete the segmented-preview worker/import lifecycle or remove that
   partial path from this file.
