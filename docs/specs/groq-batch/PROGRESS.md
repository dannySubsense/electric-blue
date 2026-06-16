# Progress: groq-batch

## Status: IN_PROGRESS

## Branch: sprint/groq-batch (off main @ f96c6b3)
Baseline: 82 tests green.

## Slices
- [ ] S1: Characterization tests (5 CHAR) — IN_PROGRESS
- [ ] S2: Config additions + Capabilities.is_async — PENDING
- [ ] S3: BatchStore + data schemas — PENDING
- [ ] S4: UrlStager + FunnelStager — PENDING
- [ ] S5: AsyncBackend + GroqBatchBackend (mocked HTTP) — PENDING
- [ ] S6: drain_batch + completion hook — PENDING
- [ ] S7: handle_batch + watcher observer + CLI — PENDING
- [ ] S8: Final gate + Frank BUILD gate — PENDING

## Current
Slice: S1
Step: @test-writer (char tests, no production code)

## Fix Attempts
| Test/File | Attempts | Last Error |
|-----------|----------|------------|
| (none yet) | | |

## Notes
- Per-slice exit = `PATH="$PWD/.venv/bin:$PATH" make gate` green. Comprehensive qc-agent + Frank BUILD gate at S8 with 100% recirculation.
- Live Groq smoke deferred (no paid key); hermetic gate only (INV-8).
