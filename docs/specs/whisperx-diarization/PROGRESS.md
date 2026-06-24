# Progress: whisperx-diarization (DDR-05)

## Status: IN_PROGRESS

Branch: `sprint/whisperx-diarization` (off `main` @ e030293)
QC gate: **Frank** (judgment gate per forge invocation; loop until SHIP). YAGNI philosophy.

## Slices
- [x] S1: `exceptions.py` (ConfigurationError) — COMPLETE (Frank SHIP)
- [x] S2: Characterization tests (baseline lock) — COMPLETE (Frank SHIP)
- [x] S3: `Segment.speaker` in models.py — COMPLETE (Frank SHIP)
- [x] S4: Diarize fields in config.py — COMPLETE (Frank SHIP)
- [x] S5: Speaker prefix rendering in outputs.py — COMPLETE (Frank SHIP)
- [x] S6: `backends/diarize.py` (WhisperXBackend) — COMPLETE (Frank SHIP)
- [x] S7: Registry entry + watcher startup validation — COMPLETE (Frank SHIP)
- [x] S8: pyproject extra + marker + Makefile gate filter — COMPLETE (Frank SHIP)
- [x] S9: Diarize smoke test — COMPLETE (Frank SHIP; real run deferred to [diarize]+HF_TOKEN host)
- [ ] S10: README documentation — PENDING

## Current
Slice: S10
Step: starting
Baseline: `make gate` green — 195 passed, 2 deselected after S9

## Fix Attempts
| Test/File | Attempts | Last Error |
|-----------|----------|------------|
| (none yet) | | |

## Notes
- Frank is the QC gate (replaces @qc-agent in the standard forge cycle). Frank makes
  decisions/judgment calls; any issue/halt/note goes back to the forge team; loop until SHIP.
- Char-test-first: S2 must be green against unmodified models.py/outputs.py before S3/S5.
- S9 SMOKE TODO (Frank S6 flag): verify the REAL whisperX 3.8.6 export location of
  `assign_word_speakers` — impl calls top-level `wx.assign_word_speakers` (matches arch
  line 248) but arch patch-table lists `whisperx.diarize.assign_word_speakers`. Smoke must
  catch a mismatch against the live library.
