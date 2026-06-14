# Progress: backend-seam

## Status: COMPLETE — all 5 slices built, Frank BUILD gate SHIP, ready for PR

Sprint: backend-seam (issue #4 / DDR-02). Branch: `sprint/backend-seam` (off `main` @ `724563c`).
Spec committed @ `d33f717`. Governance: `docs/INVARIANTS.md` + `docs/CADENCE.md` (on main via PR #5).

## Slices
- [x] S1 — Characterization Tests (pre-refactor): 22 char tests (20 API + 2 local) green vs CURRENT code — COMPLETE (2026-06-14)
- [x] S2 — base.py: Backend Protocol + Capabilities + Transcript — COMPLETE (2026-06-14)
- [x] S3 — Registry + get_backend() + refactor local/api — COMPLETE (2026-06-14); 21 surviving char tests green UNEDITED + registry test; INV-2/INV-11 TARGET→MET
- [x] S4 — schema_version: 1 in outputs.py + test_json_schema_version — COMPLETE (2026-06-14); INV-10 TARGET→MET
- [x] S5 — full gate + smoke + Frank build gate — COMPLETE (2026-06-14); gate 47 passed, smoke 1 passed, Frank SHIP

## Current
Slice: DONE — sprint complete. Next: PR sprint/backend-seam → main.
Branch: sprint/backend-seam

## S5 attestation (INV-4 / CADENCE P6+P8)
- `make gate` → 47 passed, 1 deselected; black + ruff clean (via editable venv, sourced from src/).
- `make smoke` → 1 passed (real tiny faster-whisper model + imageio-ffmpeg, LocalBackend via registry).
- Frank BUILD gate → SHIP (verified api/local bodies verbatim line-by-line; INV-2/10/11 flips real;
  MET invariants not regressed; owned change contained to dispatch only).

## NOTE: README.md working-tree edit is the USER's (Bowie lyrics, unrelated to sprint). Do NOT stage or
## revert it — sprint commits stage explicit file lists only. QC flagged it on S3; resolved as user work.

## ENV NOTE (load-bearing for S3+)
The local `.venv` was a NON-editable install (imported electric_blue from a site-packages COPY, not
src/). Reinstalled editable: `PATH="$PWD/.venv/bin:$PATH" pip install -e ".[dev]"`. Now src/ is the live
package. CRITICAL for S3: the refactor edits src/; tests MUST run against src/ or the behavior-
preservation proof is hollow. Always run gate via `PATH="$PWD/.venv/bin:$PATH" make gate`. S1 was
unaffected (it changed no src/, so copy == src for the pinned behavior).

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
