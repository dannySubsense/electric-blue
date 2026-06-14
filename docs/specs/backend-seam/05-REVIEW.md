# Spec Review: backend-seam (ROUND 3 — post-QC-gate refresh)

- **Sprint:** backend-seam
- **DDR:** DDR-02 (ACCEPTED, 2026-06-14)
- **Issue:** #4
- **Reviewer:** spec-reviewer
- **Date:** 2026-06-14
- **Review round:** 3 (re-review after three QC-gate amendments to 01/02/04)
- **Docs reviewed:** 01-REQUIREMENTS, 02-ARCHITECTURE, 04-ROADMAP (all amended);
  03-UI-SPEC (absent — correctly N/A); DDR-02 (cross-check)

---

## What Changed Since Round 2

Round 2 closed gaps G1–G7 and landed at 38 ACs / 18 API char tests. Three QC-gate
amendments have since been applied, which this round re-reviews against the CURRENT files:

1. **Owned unknown-backend behavior change made explicit on both sides.** 01 US-04 gained
   two owned-change ACs (pre-refactor silent-local fallback pinned; post-refactor
   `RuntimeError`). The pre-refactor pin test `test_dispatch_unknown_backend_routes_local`
   is added in S1 and deliberately replaced in S3 by `test_get_backend_unknown_raises`.
2. **POST-shape pins added.** Two new API char tests (`test_api_post_files_and_timeout`,
   `test_api_raise_for_status_called`) raise the API char-test count 18 → 20.
3. **Hermeticity caveat added.** 02 §8.5 + 04 S1 note that `Config.from_env()` reads the
   real `os.environ` before `dataclasses.replace`, so every asserted field must be replaced.

Net effect: ACs 38 → 40 (US-04 +2); API char tests 18 → 20; behavior-preservation claim
now PRECISE (qualified by exactly one named owned exception) everywhere.

---

## Amendment Verification Table

| # | Amendment | Where it must land | Status |
|---|-----------|--------------------|--------|
| 1 | US-04 both-side owned-change ACs | 01 lines 178–190 (pre + post) | **CONFIRMED** |
| 1 | §6.1 owned-change note (no revert to `else` catch-all) | 02 lines 218–229 | **CONFIRMED** |
| 1 | Pre-refactor pin `test_dispatch_unknown_backend_routes_local` (S1) | 02 §8.7 (493–522), 04 S1 (169–179), 02 §10 (585) | **CONFIRMED** |
| 1 | Replaced S3 by `test_get_backend_unknown_raises` | 02 §8.7/§10 (586), 04 S3 (274–337) | **CONFIRMED** |
| 1 | §15 + 04 checkpoints name the single intentional exception | 02 §15 (662–688), 04 (51–66) | **CONFIRMED** |
| 2 | `test_api_post_files_and_timeout` (#19) + `test_api_raise_for_status_called` (#20) → 20 API tests | 02 §8.6 (421, 454–460), 04 S1 (83, 134–140) | **CONFIRMED** |
| 3 | Hermeticity caveat: `from_env()` reads real env before replace | 02 §8.5 (412), 04 S1 (150–156) | **CONFIRMED** |

All three amendments CONFIRMED in the current files. None partial, none missing.

---

## Count-Consistency Check

| Claim | 01 | 02 | 04 | Result |
|-------|----|----|----|--------|
| AC total = 40 | header "40" (l.9); recount 12+2+6+6+3+7+4 | — | — | **CONSISTENT** |
| API char tests = 20 | — | §8.6 "20 total" (421); §10 "20" (584) | S1 "20 API" (83); 20 functions listed (98–140) | **CONSISTENT** |
| S1 total = 22 (20 API + 2 local) | — | — | checkpoint "All 22" (53,59); S1 "all 22" (181); "2 local" (84) | **CONSISTENT** |
| After S3 = 21 surviving char + registry test | — | §15 (20 API + local happy-path) (677) | "21 surviving" (54); S3 "21 char tests" (347) + registry test (353–357) | **CONSISTENT** |

Arithmetic closes: 22 at S1 − 1 removed pin at S3 = 21 surviving char tests; the registry
test (`test_get_backend_unknown_raises`) is the deliberate replacement, counted separately,
not as a char test.

---

## Behavior-Preservation Precision Check

No document claims unconditional "no behavior change". Every site is qualified by the one
named owned exception:

- 01 Summary (18–22): "behavior-preserving … EXCEPT one deliberate, owned tightening …
  the only intentional behavior change."
- 02 §6.1 (226–229) and §15 (662–688): names the single replaced test as the lone exception.
- 04 Checkpoints (54) + mechanism prose (60–66): "one owned exception."
- Residual "no behavior change" phrasings (US-06 AC; 02 §6.3/§6.4; 04 S2) are correctly
  SCOPED to the `LocalBackend`/`ApiBackend`/`base.py` refactor — which IS behavior-preserving;
  the owned change lives in `__init__.py` dispatch, not in those classes. No false claim.

---

## Integrity / Regression Check (no new gaps)

| Check | Result |
|-------|--------|
| DDR-02 D1–D5 intact (01 Fixed Constraints 30–34; 02 §5/§12; 04 S2/S3) | OK — no drift |
| 03-UI-SPEC absence correctly N/A (internal seam; 01 Out-of-Scope 254) | OK |
| Slice DAG S1→S2→S3→S4→S5, checkpoints, no cycles | OK |
| Capability values (`local` None/gpu-rec; `api` 24/network) consistent 01/02/04 | OK |
| File change map vs. "Files NOT changed" (registry test = S3 CREATE only) | OK |
| G1–G7 (round 1) still closed; not reopened by amendments | OK |

---

## Final Verdict

**READY FOR FORGE.** All three QC-gate amendments are CONFIRMED in the current files, the
count chain (40 ACs · 20 API · 22 at S1 · 21 surviving + registry test) is internally
consistent across 02 and 04, and the behavior-preservation claim is precise (single named
owned exception) everywhere with no unconditional "no behavior change" survivors.

Frank's QC gate is verified separately — this review covers spec completeness/consistency
only, not the SHIP verdict.

**Remaining gap counts:** BLOCKER 0 · MAJOR 0 · MINOR 0 · (cosmetic 0).

---

## Approval Checklist

### Requirements (01)
- [x] AC count accurate (40; US-04 +2 owned-change ACs)
- [x] Owned unknown-backend change specified on both sides, testable
- [x] DDR-02 D1–D5 intact; Out-of-Scope intact

### Architecture (02)
- [x] §8.6 lists 20 API tests; §10 reads 20; §8.7 pins + replacement documented
- [x] §6.1 owned-change note; §15 names single exception
- [x] §8.5 hermeticity caveat present

### Roadmap (04)
- [x] S1 = 22 char tests (20 API + 2 local); hermeticity + env caveat stated
- [x] S3 removes pin, adds registry test; checkpoints read 21 surviving
- [x] Char-tests-first DAG, Frank final

### UI Spec (03)
- [x] N/A — correctly omitted (no user-facing surface)

### Overall
- [x] 3 amendments CONFIRMED; counts consistent; behavior claim precise
- [x] Ready for `/forge-start`
