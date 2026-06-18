# Spec Review: whisperx-diarization (DDR-05)

- **Status:** APPROVABLE
- **Reviewer:** reed (spec-reviewer)
- **Date:** 2026-06-18
- **Iteration:** 6 (final — Frank SPEC gate)
- **Docs reviewed:** 01-REQUIREMENTS, 02-ARCHITECTURE, 04-ROADMAP, DDR-05
- **No 03-UI-SPEC:** correct — this is a backend/library feature with no UI surface.
- **Verdict:** **APPROVABLE**

---

## Iteration 5 Finding — Resolution Status

**Finding (iter 5, minor):** `get_backend(cfg)` startup-validation call was specified at an
imprecise placement ("after batch block, before `obs.start()`"), which would let the
pre-existing file backlog drain via `run_once(cfg)` before validation fired — meaning a
misconfigured `diarize` backend (no `HF_TOKEN`) would raise `ConfigurationError` mid-backlog
rather than before any work.

**RESOLVED — Y.** The call is now specified as the FIRST statement of `run_watch()`, before
`run_once(cfg)` and before the observer, in all three load-bearing locations:

| Location | Status |
|----------|--------|
| 02 Integration Points (`watcher.run_watch()` row) — "as the first statement before `run_once(cfg)` and the observer, so validation fires before any backlog files are processed" | OK |
| 02 Startup Validation — "called as the first statement of `run_watch()`, before `run_once(cfg)` drains the backlog and before the observer starts" | OK |
| 04 S7 Implementation Notes + Done When — "as the first line of `run_watch()`, before `run_once(cfg)`" with explicit rationale that post-`run_once()` placement drains backlog first | OK |

Ground-truth check: `src/electric_blue/watcher.py` `run_watch()` (line 194) currently has
`run_once(cfg)` as its first executable statement (line 207) and no `get_backend` call —
exactly the "currently" state the spec describes. The new line is additive and the
placement is internally consistent across 02 and 04.

---

## New Findings (this iteration)

None that affect approvability. One observation, carried (not new, not blocking):

- **OBS-1 (carried):** DDR-05 prose body (§1–§7) still uses the pre-lock name `"whisperx"` /
  `backends/whisperx.py`. The LOCKED decisions block (D1) and all of 01/02/04 use the
  authoritative `"diarize"` / `backends/diarize.py`. The DDR's own locked-decision header
  overrides its draft body; the specs are correct. No action — the DDR is a frozen decision
  record, not an implementation target.

---

## Carried Risks (unchanged, all have mitigations)

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| whisperX `DiarizationPipeline` ctor param (`token=` per 02 stage 3 vs `use_auth_token=` in DDR body) differs in real 3.8.6 | M | L | Build-time concern; smoke (S9) exercises real construction; gate mocks the seam. Resolve at S6 against installed wheel. |
| `torch~=2.8.0` tight pin breaks on torch 2.9 | M | M | `[diarize]` pins `whisperx>=3.8.6,<4.0`; torch transitive; track whisperX releases |
| pyannote gated-model ToS not accepted by operator | M | M | Fail-loud `OSError` → `failed/`; README ToS callout (S10) |
| Windows (`triton` no PyPI binary) | H (Win only) | L | Out of scope; README Windows note (S10); R630 Linux is primary host |
| Patch-targets table (02) lists submodule paths while fixture replaces whole `whisperx` module | L | L | Operative seam is `_get_whisperx()` returning the patched module; fixture is authoritative; table is supplementary |

---

## Assumptions (documented, unchanged)

| Assumption | Impact if Wrong |
|------------|-----------------|
| DDR-02 (`Backend` Protocol, `Capabilities`, `schema_version:1`) merged to `main` before build | Build cannot start; hard dependency |
| `Config` exposes `compute_type`, `device`, `model_size`, `language` reused by diarize | S6 helpers (`_resolve_compute`/`_resolve_device`) fail; verify at S6 |
| whisperX 3.8.6 top-level API confirmed; `DiarizationPipeline` via `whisperx.diarize` | Stage calls must match; verified by orchestrator |

---

## Coverage Summary

- **Requirements → Architecture:** US-1..US-7 + INV-2/7/8/10/11/13 + D5/D6/D7 mapped (02 Requirement Coverage table). Complete.
- **Architecture → Roadmap:** every component lands in S1–S10; no circular deps (S1→S2→S3→S5→S6→S7→S8→S9, S4→S6, S10←S7). Complete.
- **Acceptance criteria → slices:** 04 Requirement Coverage table maps every AC to a verifying slice. Complete.
- **Hermetic gate (INV-8):** mock seam + `diarize_smoke` exclusion + Makefile filter specified. Complete.

---

## Open Questions

None. D1–D7 locked; iteration-5 finding resolved; no new ambiguity.

---

## Approval Checklist

### Requirements (01)
- [x] Acceptance criteria testable
- [x] Out of scope explicit and acceptable
- [ ] Reviewed by human (Frank gate)

### Architecture (02)
- [x] Patterns appropriate; schemas valid Python
- [x] Integration points concrete and verified against source
- [ ] Reviewed by human (Frank gate)

### Roadmap (04)
- [x] Slices sized; sequence acyclic; done-criteria present
- [x] Char-test-first ordering enforced for modified files
- [ ] Reviewed by human (Frank gate)

### Overall
- [x] Iteration-5 finding resolved
- [x] All risks have mitigations
- [x] No open questions
- [x] **APPROVABLE** — ready for human (Frank SPEC gate) sign-off
