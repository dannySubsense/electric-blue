# Progress: backend-seam

## Status: IN_PROGRESS

Sprint: backend-seam (issue #4 / DDR-02). Branch: `sprint/backend-seam` (off `main` @ `724563c`).
Spec committed @ `d33f717`. Governance: `docs/INVARIANTS.md` + `docs/CADENCE.md` (on main via PR #5).

## Slices
- [x] S1 — Characterization Tests (pre-refactor): 22 char tests (20 API + 2 local) green vs CURRENT code — COMPLETE (2026-06-14)
- [ ] S2 — base.py: Backend Protocol + Capabilities + Transcript — IN_PROGRESS (next)
- [ ] S3 — Registry + get_backend() + refactor local/api (21 char tests still green; +registry test) — PENDING
- [ ] S4 — schema_version: 1 in outputs.py + test — PENDING
- [ ] S5 — full gate + smoke + Frank build gate — PENDING

## Current
Slice: S2
Step: @code-executor (create backends/base.py)
Branch: sprint/backend-seam

## S1 result (baseline established)
22/22 char tests green; `make gate` 46 passed; QC PASS (non-tautological, hermetic, public seam,
SI-boundary genuine). src/ untouched. Committed.

## Behavior-preservation checkpoints (INV-3)
- S1: 22 char tests green vs pre-refactor code (baseline)
- S3: 21 surviving char tests green vs refactored code (proof) + test_dispatch_unknown_backend_routes_local
  REMOVED (owned change → test_get_backend_unknown_raises)
- S4: 21 char tests green after schema_version addition
- S5: green under make gate + make smoke

## Invariant watch (this sprint flips TARGET→MET)
- INV-2 (backend-substitution half), INV-10 (schema_version), INV-11 (Protocol+registry dispatch).

## Fix Attempts
| Test/File | Attempts | Last Error |
|-----------|----------|------------|
| (none yet) | | |

## Notes
- S1 is test-only (no implementation): pins CURRENT api/local behavior so the S3 refactor is provably
  behavior-preserving. Tests call the PUBLIC `transcribe(cfg, src)` so they survive the refactor unedited.
- README.md shows a working-tree modification (user's IDE edit) — NOT part of this sprint; do not stage it.
