# Spec Review: groq-batch (RE-REVIEW — recirculated-fix verification)

- **Status:** DRAFT (reviewer output — for Frank SPEC gate)
- **Reviewer:** reed (spec-reviewer role)
- **Date:** 2026-06-16
- **Docs reviewed:** 01-REQUIREMENTS.md (now 67 ACs), 02-ARCHITECTURE.md, 04-ROADMAP.md
- **Authority:** DDR-03 "Sprint Decisions — LOCKED 2026-06-16"; INVARIANTS.md; CADENCE.md;
  orchestrator decisions on Q1/Q2/Q3 (final, not re-litigated here)
- **Code cross-checked:** backends/base.py, backends/__init__.py, backends/api.py,
  backends/local.py, watcher.py, config.py, outputs.py, notify.py, models.py, cli.py
- **No UI-SPEC (03):** correct — internal/library work (CADENCE P2 omits 03 when no user surface).

This revision supersedes the prior 3-blocker / 14-minor / 3-question review. It verifies each
prior finding against the updated docs and runs a fresh consistency pass for edit-induced drift.

---

## Verdict

**READY for the Frank SPEC gate.**

All 3 blockers (B1–B3) are **RESOLVED**, all 14 minors (M1–M14) are **RESOLVED**, and all 3
open questions (Q1–Q3) are answered per the orchestrator decisions and faithfully implemented
across 01/02/04. The fixes are internally consistent in the **authoritative** locations: the
01 acceptance-criteria set (67 ACs, families tally correctly) and the 04 AC Coverage Ledger
(67/67, one slice each, no dup, no orphan).

The fresh pass surfaced **4 new minor findings (N1–N4)**, all documentation-drift in
**descriptive / appendix** sections of 02-ARCHITECTURE (§15 char-test prose, §19 module-layout
AC ranges) and one mis-citation in the 01 DDR coverage map. None block implementation — the
roadmap ledger and the AC bodies are correct and unambiguous — but per 100%-recirculation they
are listed below for a trivial cleanup pass.

- Prior blockers resolved: **3 / 3**
- Prior minors resolved: **14 / 14**
- Prior open questions closed: **3 / 3**
- New findings: **4** (all minor, doc-drift; 0 blocker)

---

## Resolution Table — Prior Findings

### Blockers

| ID | Status | Evidence |
|----|--------|----------|
| **B1** (funnel-URL misconfig strands files / uncaught raise) | **RESOLVED** | Two-layer fix per orchestrator Q1. **Primary (startup):** new **CFG-10** (01 line 263) — `ensure_batch_dirs()` raises `RuntimeError` when `batch_inbox_dir` set + `batch_funnel_base_url==""`; 02 §4 (lines 462–472), §7 "Startup validation" (lines 730–736), §13 run_watch (line 1089); 04 S7 CFG-10 test (lines 760–764). **Defense-in-depth (in-try construction):** 02 §12 handle_batch constructs `make_groq_batch_backend(cfg)` **inside** the try (line 1024 + design note 1021–1023); 02 §11 drain_batch constructs `_stager/_backend` inside the per-job try (lines 904–908). Edge-case table updated (01 line 302). Consistent across 01/02/04. |
| **B2** (SUBMIT-6 "original location" vs §12 destination) | **RESOLVED** | SUBMIT-6 reworded to "intended DESTINATION, set unconditionally before the move; file may remain at `batch_inbox_dir` after a failed move; recovery operator-driven" (01 lines 248). New dedicated **SUBMIT-8** asserts `record.staged_path == str(cfg.batch_submitted_dir / path.name)` (01 line 250). 02 §12 (lines 1036–1040) and §7 (lines 747–751) match. No remaining contradiction. |
| **B3** (`a.mp3` staged-filename collision) | **RESOLVED** | New **STAG-7** (01 line 213): MP3 named `f"{src.stem}.mp3"`, URL `f"{cfg.batch_funnel_base_url}/{src.stem}.mp3"`, unique per source. 02 §5 step 3 (lines 597–602) and step 5 (605), §8 contract (lines 819–824). ASYNC-3(c) custom_id `eb-{src.stem}`. STAG-7 → S5 (04 ledger line 877, test lines 504–509). |

### Minors

| ID | Status | Evidence |
|----|--------|----------|
| M1 (size-cap had no AC) | **RESOLVED** | New **ASYNC-11** (01 line 227); 02 §5 step 4 (line 603); 04 S5 (lines 489–493). |
| M2 (CFG-1 only 6 of 8 defaults) | **RESOLVED** | **CFG-1** now asserts all 8 incl. `batch_stage_dir` and `batch_funnel_base_url==""` (01 line 254); 04 S2 (lines 229–233). |
| M3 (`Transcript` wrongly imported from batch_store in §3) | **RESOLVED** | 02 §3 lines 256–257: `from ..batch_store import JobRef, JobStatus` / `from ..backends.base import Capabilities, Transcript`. Matches §4 and §19. |
| M4 (hardcoded 20h expiry) | **RESOLVED** (Q2) | **DRAIN-8** now derives 80% of parsed `batch_completion_window` (01 line 274); 02 §11 `_maybe_warn_expiry` (lines 984–988); 04 S6 tests both 24h→19.2h and 7d→134.4h (lines 593–596). |
| M5 (ASYNC-2 `max_upload_mb` ambiguous) | **RESOLVED** | **ASYNC-2** asserts `max_upload_mb is None` (01 line 218); 02 §4 line 446; 04 S5 (line 457). |
| M6 (no AC for unknown/`validating` status) | **RESOLVED** | New **ASYNC-12** (01 line 228); 02 §5 (line 646); 04 S5 (lines 495–498). |
| M7 (fetch duration rounding vs api.py) | **RESOLVED** | 02 §5 line 659: `duration=round(float(... or 0.0), 2)  # round to 2 dp, matching api.py`. |
| M8 ("owned changes: 5" vs 6) | **RESOLVED** | 02 Status footer line 1355: "Owned changes to existing files: 6 (base, local, api, config, watcher, cli)". |
| M9 (DRAIN-9 wrong test seam) | **RESOLVED** | **DRAIN-9** rewritten: patch `electric_blue.drain.drain_batch`, set `sys.argv`, call `main()` with no args (01 line 275 + 04 lines 766–775). Verified against cli.py (lazy `from .watcher import ...`; `main()` reads `sys.argv`). |
| M10 (no char pin for cli.py owned edit) | **RESOLVED** (see N1) | **CHAR-5** added — pins pre-fix `main()` dispatch (`--once`/`--file`/default) before S7 edits cli.py (04 S1 lines 151–171; checkpoints lines 80–88). Counts as INV-3 process pin, not a numbered AC (04 lines 182–183), so the 67 tally is unaffected. *Note: 02 §15/§19 prose still says "Four char tests" — captured as N1.* |
| M11 (submit→save crash window unanalyzed) | **RESOLVED** | New 02 §7 subsection "Accepted partial state — submit() → store.save() window (M11)" (lines 757–775) documenting orphan-job/double-submit risk + operator recovery. |
| M12 (no `batch_done` ntfy branch) | **RESOLVED** | 02 §16 line 1226 notes ntfy `batch_done` falls to generic title; "not a bug; DDR-04 follow-up." |
| M13 (`custom_id` never asserted) | **RESOLVED** | **ASYNC-3(c)** asserts `"custom_id": f"eb-{src.stem}"` at request top level (01 line 219; 04 line 463). |
| M14 (`--file` crash left adjacent) | **RESOLVED** (Q3) | Now in-scope as **CLI-1** (01 line 293) — `process(cfg, Path(args.file), datetime.now(timezone.utc))`; 02 §4 (lines 559–568) + §14; 04 S7 (lines 716–723, 777–782). Verified: watcher.process is 3-arg (`process(cfg, src, started_at)`); current cli.py line 31 is the 2-arg crash being fixed. |

### Open Questions

| ID | Status | Resolution implemented |
|----|--------|------------------------|
| Q1 (startup-fail vs route-to-failed for empty funnel URL) | **CLOSED** | Orchestrator: both. CFG-10 startup guard (primary) + in-try construction (defense-in-depth). Implemented — see B1. |
| Q2 (expiry threshold scaling) | **CLOSED** | Orchestrator: derive from `batch_completion_window` (~80%). Implemented — see M4. |
| Q3 (ratify leaving `--file` crash) | **CLOSED** | Orchestrator: fix it this sprint as CLI-1. Implemented — see M14. |

---

## Fresh Consistency Pass — NEW Findings

All four are documentation-drift in non-authoritative / descriptive sections. The authoritative
AC set (01) and AC Coverage Ledger (04 lines 869–896) are correct; these are sync gaps only.

| ID | Document | Severity | Description | Suggested fix |
|----|----------|----------|-------------|---------------|
| **N1** | 02 §15 (line 1205), §19 (line 1290), §14 | minor | The recirculated fix for M10 adds **CHAR-5** (cli.py dispatch pin) in 04 S1, but 02 §15 still reads "Four characterization tests committed and green BEFORE any source change" and lists only CHAR-1..4; §19 module layout (line 1290) still says `test_char_batch.py — CHAR-1 through CHAR-4`. §14's cli.py owned-change row also does not reference the required pre-change char pin. The build sequence is correct (04 is authoritative); only the architecture prose is stale. | Update 02 §15/§19 to "Five characterization tests (CHAR-1..5)"; add CHAR-5 (cli `main()` dispatch) and note it pins cli.py before the S7 owned edit. |
| **N2** | 02 §19 module-layout AC ranges (lines 1290–1296) | minor | Per-test-file AC ranges are stale vs the post-revision AC set: `test_staging.py — STAG-1..6` (STAG-7 now exists), `test_batch_groq.py — ASYNC-1..10` (now ASYNC-1..12 + STAG-4 + STAG-7), `test_handle_batch.py — SUBMIT-1..7` (now SUBMIT-1..8 + STAG-6 + DRAIN-9 + CFG-10 + CLI-1), `test_drain.py — DRAIN-1..10` (DRAIN-9 actually lives in test_handle_batch.py per 04), `test_char_batch.py — CHAR-1..4` (now +CHAR-5). Cosmetic; 04's ledger is the source of truth. | Sync the §19 comment ranges to the 04 ledger, or replace with "see 04 AC Coverage Ledger." |
| **N3** | 01 DDR Decision Coverage Map (line 451) | minor | The B1 row cites "**ASYNC-9** (defense-in-depth in submit)," but ASYNC-9 tests the empty **API-key** guard, not the funnel-URL guard. The actual funnel-URL defense-in-depth — submit() §5 step 2 guard, `make_stager()` raising on empty URL (02 §8 lines 835–837), and in-try construction routing to failed_dir — has **no dedicated AC** (SUBMIT-5 covers `submit()` raising, not the construction step; make_stager's RuntimeError is only in S4 "done-when" prose, line 358). Not gate-blocking: CFG-10 (primary) is well-AC'd and the design is sound. | Fix the citation to reference the §12 in-try construction + SUBMIT-5 chain; optionally add an AC: "empty funnel URL → `make_stager`/`submit` raises → file routed to failed_dir." |
| **N4** | 02 §3 (line 155) | minor (cosmetic) | The `Capabilities.max_upload_mb` inline comment reads "None or int for batch," looser than the decided `max_upload_mb=None` (ASYNC-2, §4 line 446). | Tighten the comment to "None for batch (size-cap enforced internally via cfg.batch_max_mb)." |

---

## Targeted Re-checks Requested by Orchestrator

| Check | Result |
|-------|--------|
| AC count / family tally (01) | **OK.** Header 67 = CHAR4+CFG10+STORE8+STAG7+ASYNC12+SUBMIT8+DRAIN10+HOOK3+FAIL4+CLI1; body ranges match each family exactly. |
| AC ledger (04) | **OK.** 67/67, each AC in exactly one slice, no dup/orphan. Family→slice summary (lines 888–896) consistent. CHAR-5 correctly excluded from the count as a process pin. |
| B1 two-layer fix internal consistency across 01/02/04 | **OK.** CFG-10 (primary) + in-try construction (handle_batch §12, drain_batch §11) present and mutually consistent; only the 01 coverage-map citation is mislabeled (N3). |
| Char-test does NOT incorrectly pin the CLI-1 crash | **OK.** CHAR-5 (S1) mocks `process` and asserts it is called with the path, explicitly "do NOT assert argument count" (04 line 162); the 2-arg call does not raise against a mock. CLI-1 (S7) pins the 3-arg fix. No char test pins a crash. |
| STAG-7 / SUBMIT-8 / CFG-10 land in the right slice | **OK.** STAG-7 → S5 (submit context), SUBMIT-8 → S7 (handle_batch), CFG-10 → S7 (ensure_batch_dirs lives in S7; correctly deferred from S2, 04 lines 259–261). All match the ledger. |
| Dangling references / import graph | **OK.** §3 Transcript import fixed (M3); §19 import graph acyclic; no new dangling refs introduced beyond the stale AC-range comments (N1/N2). |

---

## Risks (carried forward — all mitigated/accepted)

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| D7/D8 mocked schema diverges from live Groq → smoke fails post-build | M | M | FLAG-1/2 pre-smoke doc verify (S8.2); field names localized to submit()/fetch() |
| Funnel URL must stay reachable for full window; R630 reboot mid-window loses job | L | M | D5 fail→failed_dir + operator re-drop; 24h default minimizes window |
| Concurrent `--drain-batch` corrupts a shared sidecar | L | M | Documented unsupported (FLAG-2); per-job isolation bounds damage |
| Crash in submit()→store.save() window → orphan job + double-submit | L | L | Now documented as accepted partial-state (M11, 02 §7); operator recovery |
| B1 defense-in-depth construction step is thinly AC'd (N3) | L | L | Primary CFG-10 guard fully AC'd; add optional AC + fix citation |

---

## Approval Checklist

### Requirements (01)
- [x] Acceptance criteria testable — 67 ACs, families tally; ambiguities (M1/M5/M6/M13) closed
- [x] Out of scope acceptable — D9 cleanup, R2/B2, aggregation, live smoke properly deferred
- [x] Locked constraints match DDR Sprint Decisions — no drift
- [ ] (cosmetic) Fix DDR coverage-map B1 citation (N3)

### Architecture (02)
- [x] Patterns appropriate; schemas correct (M3/M7/M8 fixed)
- [x] INV-1 ordering complete — B1 startup+in-try, M11 window documented
- [x] Owned changes named (6 files) with char-first
- [ ] (cosmetic) Sync §15/§19 prose to 5 char tests + current AC ranges (N1/N2); tighten §3 comment (N4)

### Roadmap (04)
- [x] Sequence correct (S1 char-first; linear acyclic; CADENCE P3 per slice)
- [x] AC ledger complete — 67/67, no dup, no orphan; DRAIN-9 seam fixed (M9)
- [x] STAG-7/SUBMIT-8/CFG-10/CLI-1/CHAR-5 placed in correct slices

### Overall
- [x] All blockers (B1–B3) resolved
- [x] All minors (M1–M14) resolved
- [x] Open questions Q1–Q3 closed per orchestrator decisions
- [x] **Ready for Frank SPEC gate** (N1–N4 are non-blocking doc-sync nits)

---

## Behavior-Preservation Chain (INV-3) — verdict

Now airtight for **all** touched runtime files including cli.py: CHAR-5 pins `main()` dispatch
before the S7 owned edit (closes the prior M10 gap). `Capabilities`/local/api pinned by CHAR-4;
`handle()`/`run_watch()` by CHAR-1/2/3; `config.py` by CFG-7/CFG-8. INV-1 chain specified and
tested at submit (SUBMIT-1/5/6/8), drain success (DRAIN-3/5/6), drain failure
(DRAIN-4/FAIL-1..4), with B1 (CFG-10 + in-try) and M11 (accepted window) both now covered.
VERIFY items (D7/D8, URL-fetch timing) remain correctly quarantined to mocked gate tests + the
S8.2 pre-smoke live-doc step; none block the hermetic gate (INV-8).
