# Progress: completion-webhook

## Status: IN_PROGRESS

Sprint: completion-webhook (DDR-04 / issue #10). Branch `sprint/completion-webhook` (off main @ 870d00e).
Spec on main (PR #11). Run gate via `PATH="$PWD/.venv/bin:$PATH" make gate` (INV-14 editable venv).

## Slices
- [x] S1 — Characterization tests (CHAR-1..4 pin current notify() stub) — COMPLETE
- [x] S2 — Config additions (4 fields + from_env + test_config) — COMPLETE
- [ ] S3 — Payload builders + redaction tests — PENDING
- [ ] S4 — write_outputs() -> dict[str,Path] — PENDING
- [ ] S5 — notify() rewrite + watcher integration (19 new tests; CHAR-3/4 superseded) — PENDING
- [ ] S6 — full gate + smoke + Frank build gate — PENDING

## Current
Slice: S3
Step: @code-executor (payload builders) + @test-writer (redaction tests)

## Behavior-preservation note (INV-3)
notify() is an OWNED API rewrite (signature changes) — NOT behavior-preserving. Only never-raises and
no-op-when-unset survive (re-asserted on new code in S5). CHAR-3 (payload shape) + CHAR-4 (timeout=15)
are deliberately superseded in S5. Two DDR corrections live in S5: 4xx-no-retry; started_at stamped in
handle() passed to process().

## Fix Attempts
| Test/File | Attempts | Last Error |
|-----------|----------|------------|
| (none yet) | | |
