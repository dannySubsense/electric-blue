# Spec Review: completion-webhook

- **Status:** REVIEW COMPLETE
- **Reviewer:** reed (spec-reviewer)
- **Date:** 2026-06-14
- **Documents reviewed:** 01-REQUIREMENTS, 02-ARCHITECTURE, 04-ROADMAP, DDR-04
- **Governance checked:** INVARIANTS.md (INV-1, INV-3, INV-7, INV-9, INV-10), CADENCE.md (P3, P5–P9)
- **Code cross-checked:** `notify.py`, `watcher.py`, `config.py`, `outputs.py`, `test_watcher.py`,
  `test_outputs.py`, `test_config.py`
- **03-UI-SPEC:** Correctly **N/A** — internal library / systemd service, no user-facing surface
  (CADENCE P2 explicitly omits 03 for non-UI work). Not flagged.

---

## Verdict: READY FOR FORGE — WITH MINORS

No BLOCKER or MAJOR gaps. The headline behavior-preservation honesty check (INV-3) **passes**: the
docs do not overclaim "behavior-preserving" for what is an API rewrite of `notify()`. The two
architect-found DDR corrections (4xx-no-retry; `started_at` scoping) are consistently reflected in
both 02 and 04 and explicitly named as corrections over the DDR's now-superseded proposed code.
D1–D6 fidelity holds and the in-scope test count (15 of 17 DDR §8 tests) is consistent across all
three documents. The minors below are coverage-explicitness items and two documented residual risks;
none blocks Forge entry. Recommend fixing G1–G4 in-doc (cheap) before the Frank SPEC gate.

- **Gaps found:** 4 (0 BLOCKER, 0 MAJOR, 4 MINOR)
- **Risks identified:** 3
- **Open questions:** 1 (non-blocking)

---

## Load-Bearing Check: Behavior-Preservation Honesty (INV-3)

`notify()`'s public signature changes (`notify(cfg, text, meta)` → `notify(cfg, payload)`), so the
characterization tests are **not** an unedited before/after proof. The docs are honest about this:

| Contract | Old stub behavior | Disposition | Re-asserted against NEW `notify()`? | Honest? |
|----------|-------------------|-------------|-------------------------------------|---------|
| **CHAR-1** no-op when `notify_webhook=""` | `requests.post` never called | **survives** | Yes — `test_no_op_when_unset` (S5) | ✅ |
| **CHAR-2** never-raises | swallows any `Exception`, returns | **survives** | Yes — `test_swallows_exception` + REL-2/3/4 (S5) | ✅ |
| **CHAR-3** payload `{"text",**meta}` | `{"text":"hello","file":"x.mp4"}` | **superseded** → v1 structured dict | `test_posts_generic_payload`; CHAR-3 deleted, PR-named | ✅ |
| **CHAR-4** `timeout=15` | hardcoded 15 | **superseded** → `cfg.notify_timeout_sec` (5.0) | `test_timeout_from_config`; CHAR-4 deleted, PR-named | ✅ |

Findings:
- The non-blocking contract (never-raises / no-op-when-unset) **is** asserted against the rewritten
  `notify()`, not just the old stub (S5 tests `test_no_op_when_unset`, `test_swallows_exception`,
  REL-2/3/4). ✅
- Deliberately owned/changed behaviors are correctly classified: payload shape
  (`{"text",**meta}` → v1 structured) and timeout (15 → `cfg.notify_timeout_sec`). ✅
- The `notify()` rewrite and `process()` signature change are named as **owned changes** in the PR
  description (02 §6, §8; 04 S5 step 10). The docs do **not** label the `notify()` rewrite
  "behavior-preserving." ✅
- `write_outputs()` return-value change is correctly labeled behavior-preserving (additive return;
  no current caller reads it; verified against the 6 existing `test_outputs.py` write_outputs tests,
  none of which capture the return). ✅ Confirmed against actual `outputs.py`/`test_outputs.py`.

**Residual nuance (see G4):** the *placement* of the surviving CHAR-1/CHAR-2 assertions after the
rewrite is ambiguous (edited in `test_char_notify.py` vs. re-added in `test_notify.py`).

---

## DDR Corrections — Consistency Check (02 ↔ 04 ↔ DDR)

| Correction | DDR (superseded) | 02-ARCHITECTURE | 04-ROADMAP | Consistent? |
|-----------|------------------|-----------------|-----------|-------------|
| **C1 — 4xx no-retry** | §3 uses `r.raise_for_status()` + catch-all → would retry 4xx (violates D3) | §3 "Correction over DDR" + §12 FLAG-1: explicit `r.status_code` branching, 4xx returns immediately | "Correction 1 (FLAG-1)" + S5 step 5; verified by `test_no_retry_on_4xx` (REL-7) | ✅ Both name the DDR code as corrected |
| **C2 — `started_at` scoping** | §7 sets `started_at` in `process()` but uses it in `handle()` except (impossible) | §6 "started_at lives in handle()" + §12 FLAG-2: stamped in `handle()`, passed to `process()` | "Correction 2 (FLAG-2)" + S5 step 8; verified by INT-4 | ✅ Both name the DDR scope bug |

Both corrections are reflected in 02 **and** 04 and explicitly flag the DDR's proposed code as
superseded (not silently contradicted). ✅ This satisfies INV-9 (no DDR decision contradicted —
these are corrections of *proposed code*, not of a locked D1–D6 decision; D3 is the locked decision
and the correction *enforces* it).

---

## D1–D6 Fidelity

| Decision | Requirement | Verified in spec |
|----------|-------------|------------------|
| D1 filenames-only, no snippet | `outputs:{fmt:path.name}`; no `snippet` in v1 | RED-1, payload schema 02 §2; snippet in Out-of-Scope ✅ |
| D2 generic + ntfy only; Slack/Teams deferred | 2 deferred §8 tests OUT OF SCOPE; **15 in-scope** | 01 coverage map (17→15), 02 §8 table, 04 S5 "15 of 15" + ledger "15 of 17" — **consistent across all three** ✅ |
| D3 4xx-no-retry / 5xx-retry / timeout 5s / retries 0 | `_post_with_retry` status branching; CFG-1 defaults | REL-1..8, CFG-1 ✅ |
| D4 HMAC behind empty default | header omitted when secret `""` | HMAC-1, CFG-1 ✅ |
| D5 single URL | one `NOTIFY_WEBHOOK`, all events | per-event routing in Out-of-Scope ✅ |
| D6 started event | fired before `transcribe()` | STA-1, STA-2, INT-4 ✅ |

In-scope DDR §8 test count is **15** everywhere (S3 contributes 6, S5 contributes 9). No drift.

---

## Invariant Compliance

- **INV-1 (no data loss):** Move-to-`done` stays strictly after `process()` returns; failure path
  moves to `failed/` after the `build_failed_payload` notify; `notify()` never raises, so the
  `failed/` move is always reached. Ordering unchanged from current `handle()`. 02 §6 + 04 S5 gate
  grep confirm. ✅ (Defense-in-depth note: `notify(done)` is called *inside* `process()` before
  return — relies on the never-raises contract so a notify error cannot misroute a successful file to
  `failed/`. Contract is asserted by REL-2/3/4 + `test_swallows_exception`. Acceptable.)
- **INV-3 (behavior preserved unless owned):** See load-bearing check above. ✅
- **INV-7 (secrets):** `_base_payload` uses `src.name` only, references only `cfg.backend`, never
  `api_key`/`hmac_secret`/`notify_webhook`; `_sign` never logs the secret. Structurally enforced;
  RED-1/2/3 tested. ✅ — **except** RED-4 coverage (G2) and the `str(error)` convention (Risk R2).
- **INV-9 (locked DDR):** No D1–D6 decision contradicted; corrections enforce D3. ✅
- **INV-10 (schema_version additive):** Payload reuses `schema_version:1` literal. Note: INVARIANTS.md
  still marks INV-10 **TARGET** ("not emitted today"), but `outputs.py` already emits it (DDR-02 @
  fab9c71). Stale ledger entry — see Open Question OQ-1; not this sprint's blocker.

---

## Gaps Table

| ID | Document | Severity | Description |
|----|----------|----------|-------------|
| **G1** | 04-ROADMAP | MINOR | AC Coverage Ledger lists **44** distinct ACs (CHAR 4 + CFG 7 + PAY 5 + STA 2 + RED 4 + REL 8 + FMT 3 + HMAC 4 + OUT 3 + INT 4) but states "All **41** sprint ACs covered." Miscount — correct the total to 44. Cosmetic but reviewer-facing. |
| **G2** | 01 / 02 / 04 | MINOR | **RED-4 has no dedicated verifying test.** RED-4 (HMAC secret never in logs **and** never in serialized payload) is claimed "satisfied" in 04 S5 ACs and 04 S3 ACs, but no scheduled test asserts it — S3 covers only paths (RED-1/2) and `api_key` (RED-3); RED-4 is absent from 02 §8 table and the DDR §8 map. The not-in-logs half needs a `caplog` assertion on the `_sign`/`notify` failure path; the not-in-payload half should extend `test_no_api_key_in_payload` to also assert `notify_hmac_secret` is absent. Add an explicit `test_no_hmac_secret_leak`. |
| **G3** | 02 / 04 | MINOR | **FMT-3 and INT-4 verified by inspection only.** FMT-3 (formatter introduces no path/secret fields) and INT-4 (single `datetime.now(timezone.utc)` call shared across payloads) are listed as satisfied but have no dedicated automated test in 02 §8 or 04 S5. They are design/structural properties. Either add an explicit assertion (e.g., INT-4: assert the same `started_at` object reaches all three builders; FMT-3: assert `set(formatted) ⊆` derivable-from-input) or state explicitly that they are Frank-gate inspection items, not test-covered. |
| **G4** | 04-ROADMAP | MINOR | **Surviving-test placement ambiguity (INV-3 home).** S5 step 10 edits CHAR-1/CHAR-2 in `test_char_notify.py` to the 2-arg form; step 11 also adds `test_no_op_when_unset`/`test_swallows_exception` in `test_notify.py` and notes "they may be identical." INV-3's post-change replacement assertion should have one unambiguous home. Specify whether the surviving assertions live in `test_char_notify.py`, `test_notify.py`, or are deliberately duplicated — avoid an accidental "deleted from one, assumed in the other" gap. |

---

## Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|------------|--------|------------|
| R1 | **HMAC signed bytes ≠ wire bytes.** `notify()` signs `json.dumps(formatted, sort_keys=True, separators=(",",":"))` but `requests.post(json=formatted)` serializes without `sort_keys`/compact separators. A consumer verifying the HMAC over the *raw received body* will fail unless it re-canonicalizes (parse + re-dump `sort_keys=True`). | M | L (HMAC opt-in, default off) | Documented in 02 §3 and DDR §5 as accepted; HMAC-3/HMAC-4 pin the canonical form. Future: POST exact signed bytes via `data=` + explicit `Content-Type` to make wire == signed. Acceptable for v1. |
| R2 | **`str(error)` redaction is convention, not structural (INV-7).** `build_failed_payload` emits `str(error)`, sent to an external webhook. A theoretical exception embedding a secret (e.g., a URL with credentials) would leak. | L | M | 02 §7 point 4 honestly flags this as convention-only for v1. Known pipeline exceptions (RuntimeError, codec errors) don't embed secrets. Accept for v1; revisit if a backend surfaces credential-bearing messages. |
| R3 | **Watcher thread blocks up to `notify_timeout_sec × (1 + notify_retries)`.** Default 5s × 1 = 5s synchronous block per event, plus a new `started` round-trip per file (D6). | M | L | DDR Risks + 02 FLAG-3 document it; defaults preserve single-attempt fast path; high-volume deployments lower `NOTIFY_TIMEOUT_SEC`. Threading is explicitly future scope. |

---

## Assumptions

| Assumption | Impact if wrong |
|------------|-----------------|
| DDR-02 foundation merged at `fab9c71` (`schema_version` in `outputs.py`, backend seam) | Verified true in `outputs.py` line 52; low risk |
| `requests>=2.28` is a core dep (module-level import + mock seam valid) | Stub currently lazy-imports it; pyproject must declare it as core (02 §3 asserts this) — confirm at S5 |
| `fake_transcribe` fixture returns a `TranscriptInfo` with `.duration/.language/.backend` | `build_done_payload` runs eagerly inside `process()` even when webhook unset; if fixture's info is incomplete, existing `test_handle_success` would break at S5 (caught by gate) |
| `info.backend` (e.g. `"api:whisper-large-v3-turbo"`) is filename/secret-safe | Holds for current backends; structural redaction relies on it |

---

## Open Questions

| ID | Question | Status | Resolution path |
|----|----------|--------|-----------------|
| OQ-1 | INVARIANTS.md marks INV-10 **TARGET** ("no `schema_version` emitted today"), but `outputs.py` already emits `schema_version:1` and this sprint reuses it. Should the ledger flip TARGET→MET? | Open (non-blocking) | Docs-sync, separate from this sprint; note for the Frank gate. Does not affect webhook correctness. |

---

## Approval Checklist

### Requirements (01)
- [x] Summary present and clear
- [x] Locked constraints (D1–D6) enumerated and immutable
- [x] Every user story (US-01..10) has acceptance criteria
- [x] Edge-cases table populated (13 rows)
- [x] Out-of-scope non-empty and tied to D-decisions
- [x] DDR §8 coverage map present (17→15 in-scope)
- [ ] RED-4 acceptance criterion needs a scheduled verifying test (G2)

### Architecture (02)
- [x] Every requirement family has architecture coverage (13 components)
- [x] Full `notify.py` design is concrete code, not pseudocode
- [x] DDR corrections (FLAG-1, FLAG-2) called out and justified
- [x] Redaction enforced by construction (§7) with proof sketches
- [x] Mock seams / hermeticity (INV-8) specified
- [ ] FMT-3 / INT-4 verification path under-specified (G3)

### Roadmap (04)
- [x] 6 slices, linear dependency graph, no cycles
- [x] Each slice gate-verifiable (`make gate`) at its boundary
- [x] Behavior-preservation checkpoints per slice (char tests green S1–S4)
- [x] DDR corrections embedded in S5 steps
- [x] Frank BUILD gate final (S6)
- [ ] AC total miscount 41 vs 44 (G1)
- [ ] Surviving-test placement ambiguity (G4)

### Overall
- [x] No BLOCKER/MAJOR gaps
- [x] All risks have documented mitigations
- [x] Every in-scope AC has a slice home and (with G2/G3 exceptions) a verifying test
- [x] 03-UI-SPEC correctly N/A
- [ ] Human approves G1–G4 fixes (recommend in-doc before Frank SPEC gate)

---

## Reviewer Statement

The spec set is internally consistent, honest about the `notify()` API rewrite, and faithful to
D1–D6 and the two DDR corrections. It is **READY FOR FORGE with minors**. The four MINOR gaps are
coverage-explicitness and a count typo — none is load-bearing, and Forge can proceed once G1–G4 are
either patched in-doc or explicitly waived by the human at the Frank SPEC gate. No HALT condition is
present: no critical gap, no fundamental inconsistency, no missing information.
