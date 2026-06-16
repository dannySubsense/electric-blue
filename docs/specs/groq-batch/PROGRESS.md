# Progress: groq-batch

## Status: MERGED — #17 squash-merged to main @ a2d7a05 (CODE-MERGED, NOT live; live needs deploy + Groq paid tier + Tailscale Funnel)

## Branch: sprint/groq-batch (off main @ f96c6b3)
Baseline: 82 tests. Now: 162 passed, 1 deselected.

## Slices
- [x] S1: Characterization tests (CHAR-1..5) — DONE (58af01e)
- [x] S2: Config additions + Capabilities.is_async (CFG-1..9) — DONE (f5735e8)
- [x] S3: BatchStore + schemas (STORE-1..8) — DONE (bf4d0a9)
- [x] S4: UrlStager + FunnelStager (STAG-1..3) — DONE (091952f)
- [x] S5: AsyncBackend + GroqBatchBackend (ASYNC-1..12, STAG-4/7) — DONE (be7b565)
- [x] S6: drain_batch + completion hook (DRAIN/HOOK/FAIL/STAG-5) — DONE (0cc214c)
- [x] S7: handle_batch + observer + CLI (SUBMIT/STAG-6/DRAIN-9/CFG-10/CLI-1) — DONE (3c59c18)
- [x] S8: Final gate + qc-agent + Frank BUILD gate — DONE (gate 162 green; QC found+fixed SUBMIT-6 blocker + HOOK-1 minor; Frank BUILD: SHIP)

## Current
Slice: S8 — deep qc-agent review, then Frank BUILD gate (100% recirculation).
Gate: `make gate` green (162 passed). Editable venv confirmed (INV-14). No network in gate (INV-8).

## Fix Attempts
| Test/File | Attempts | Last Error |
|-----------|----------|------------|
| (none — all slices first-pass green after orchestrator black/ruff) | | |

## Notes
- Per-slice gate green throughout. Live Groq smoke deferred (no paid key) — hermetic gate only.
- Frank SPEC gate: SHIP (#16 merged to main). Now Frank BUILD gate pending.
