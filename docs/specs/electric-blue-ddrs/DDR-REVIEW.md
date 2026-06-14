# DDR Review — electric-blue backlog (DDR-02 … DDR-06)

- **Reviewer:** independent cross-consistency pass (automated)
- **Date:** 2026-06-14
- **Scope:** DDR-02–06 PROPOSED drafts, checked at their seams against DDR-01 (ACCEPTED) and each other.
- **Purpose:** make Danny's morning read efficient — flag problems, do not rewrite.

**Verdict (one line):** Coherent enough for a productive morning review. No HIGH blocker — the seams (async protocol, schema versioning, dependency order, format) line up. Several MED seam mismatches in the DDR-03 ⇄ DDR-04 completion-hook handshake are worth resolving together in the morning, but none make the set incoherent.

---

## Per-DDR snapshot

**DDR-02 (backend seam)** — Solid anchor. Defines `AsyncBackend` submit/poll/fetch, `Capabilities`, `schema_version`, characterization-first. One internal contradiction: §6 instructs "bump DDR-01 PROPOSED→ACCEPTED," but DDR-01 already reads `Status: ACCEPTED` (and DDR-02's own header says DDR-01 is DONE). Stale instruction; harmless but confusing.

**DDR-03 (Groq batch)** — Correctly anchors to DDR-02 §3 (signatures match exactly). Strong process-restart discipline. Two internal seam issues feeding into DDR-04 (below). D6 (does Groq Batch even support `/audio/transcriptions`?) is a genuine project risk but is properly flagged as the gating pre-condition, not asserted as settled — good.

**DDR-04 (webhook)** — Well-structured. The one DDR that touches every other surface. Its consumption of DDR-03's completion hook is described from one side only and does not fully match what DDR-03 actually exposes (see cross-cutting C1–C3).

**DDR-05 (diarization)** — Cleanly builds on DDR-02 §4 (additive `speaker`, schema_version). Capability flags fully specified. Honest about its own risks (dep hell, ToS). The schema_version-bump-to-2 question is correctly deferred but is coupled to an unresolved DDR-02 decision (C4).

**DDR-06 (PyPI)** — Sensibly sequenced last; depends on DDR-05 for surface stability. Self-contained, no seam conflicts. Mostly independent infra.

---

## Cross-cutting issues

> **Resolution status (2026-06-14, after Danny's PR #3 review + Frank's calls).** The findings
> below are the original review record, preserved as-found. Current dispositions:
> **C1, C2, C3 — RESOLVED in DDR-04 §1/§7:** the hook contract is settled in DDR-04 (built first
> per the `02 → 04 → 03` re-sequence). The payload carries canonical `started_at`/`finished_at`
> ISO-8601 timestamps (`wall_sec` derived), the hook signature
> `(cfg, src, info_or_exc, started_at, finished_at)` covers the failure/expiry branch, and the
> `time.time() - t_start` wall-clock fabrication is removed — DDR-03's drain supplies the two
> instants from `JobRecord.submitted_at`/`completed_at` with no schema change.
> **C4 — RESOLVED in DDR-02 D4:** `schema_version` is additive at v1; no "v2 sometimes."
> **C5 — RESOLVED:** DDR-04 added to DDR-02's `Blocks` line.

**C1 — Completion-hook signature mismatch (DDR-03 §8 ⇄ DDR-04 §7). Severity: MED.**
DDR-03 §8 exposes `_fire_completion_hook(cfg, record, info)`. DDR-04 §7 states it needs the hook to receive `(cfg, src_path, info_or_exception, t_start)` and its `build_done_payload(cfg, src, info, output_stems, t_start)` additionally requires `output_stems`. DDR-03's hook passes neither `output_stems` nor `t_start`, and passes `record` rather than `src`. Both DDRs defer to the other ("DDR-04 owns the payload" / "hook signature is DDR-03's decision"), so nothing is asserted-as-settled-but-wrong — but the two ends do not currently fit. Resolve the exact hook signature once, in whichever DDR is implemented first.

**C2 — Failure/expiry hook is promised but not fired (DDR-03 §7 ⇄ §8/D5 ⇄ DDR-04 §7). Severity: MED.**
DDR-04 §7 relies on the hook being "called after `fetch()` succeeds **or a job expires**." DDR-03's own D5 also says failure/expiry should "fire hook with error payload." But the actual drain code in DDR-03 §7 calls `_fire_completion_hook(...)` **only** in the `status.succeeded` branch; the failure/expiry `else` branch just `log.error`s. So the failed-payload path DDR-04 expects has no call site. Internal to DDR-03 and a DDR-03→DDR-04 gap.

**C3 — `notify()` signature: DDR-03 uses the old shape DDR-04 retires. Severity: LOW (acknowledged).**
DDR-03 §8 calls `notify(cfg, text, meta_dict)`; DDR-04 §6 retires that signature for `notify(cfg, payload)` and lists "DDR-03 drain × 1" as a call site it will update. Consistent in intent and explicitly acknowledged on the DDR-04 side; flagged only so the morning read knows DDR-03's §8 code block is provisional. Related: DDR-04's `wall_sec = time.time() - t_start` is meaningless across a batch job's ~24h / process-restart boundary — the async DONE payload should derive timing from `JobRecord.submitted_at`/`completed_at`, which neither DDR's payload schema currently accommodates. Worth a line in DDR-04 D1. (Severity for the wall_sec gap: MED.)

**C4 — schema_version bump policy is split across two unresolved decisions. Severity: MED.**
DDR-02 §4 + D4 own "schema_version starting value + increment policy." DDR-05 §3 + D3(a) independently ask whether diarized output bumps to `2` or stays additive at `1`. DDR-05 D3(a) cannot be answered without DDR-02 D4's policy. They are consistent (both flag it, neither contradicts) but should be resolved as one decision, in DDR-02, before DDR-05 implements. Note DDR-02 §4's stated intent ("avoid a breaking change... keep speaker fields optional/additive") leans toward *not* bumping, which slightly tensions with DDR-05's proposed `2`.

**C5 — DDR-02 "Blocks" list is incomplete. Severity: LOW.**
DDR-02 header lists `Blocks: DDR-03, DDR-05`. But DDR-04 (and transitively DDR-06) also depend on DDR-02; DDR-04's header correctly lists DDR-02 as a dependency. Add DDR-04 to DDR-02's Blocks line for a clean graph. No cycle exists; the intended order seam→batch→webhook→diarization→pypi holds, with the one acceptable slack that DDR-05 hard-depends only on DDR-02 (not DDR-04), so 05 could land before 04 even though 04's "started" event is pitched as 05's beneficiary.

**C6 — DDR-03 capability flags under-specified vs DDR-02 §2. Severity: LOW.**
DDR-02 §2 declares five flags. DDR-03 §1 sets `is_async`, `needs_network`, `max_upload_mb`, `needs_gpu_recommended` but omits `supports_diarization` (should be explicit `False`), and writes `capabilities: Capabilities` as a bare annotation+comment rather than instantiating `Capabilities(...)` the way DDR-05 §1 correctly does. Cosmetic; align with DDR-05's form.

**C7 — API-key Config field name not pinned consistently. Severity: LOW.**
DDR-04 §1/§8 references `cfg.api_key`; DDR-03 §9 introduces `cfg.batch_api_key` with env fallback to `WHISPER_API_KEY`; DDR-02 §5 refers to env `WHISPER_API_KEY`. The actual `Config` attribute name for the sync API key (`api_key`? something else?) is assumed, not stated. No collision among the new fields (batch_*, notify_*, hf_token/diarize_* are all disjoint), but the existing field's name should be confirmed so DDR-04's redaction test (`cfg.api_key`) references a real attribute.

---

## Format consistency (all clean)

- Status `PROPOSED`, Author `reed`, Date `2026-06-14`: consistent across DDR-02–06.
- Section structure (Context / Principle / Decision / Sequencing / Risks / "Open questions / DECISIONS TO FLAG"): present in all five.
- "DECISIONS TO FLAG" sections present and well-formed in all five.
- Only nit: DDR-02 §6's stale "bump DDR-01 to ACCEPTED" (see DDR-02 snapshot) — a content inconsistency, not a format one.

---

## Suggested morning order of attention

1. Settle the DDR-03 ⇄ DDR-04 completion-hook contract once: signature, the failure/expiry call site (C2), and async timing fields (C3 wall_sec). One conversation closes C1–C3.
2. Decide schema_version policy in DDR-02 D4, then DDR-05 D3(a) falls out (C4).
3. Trivial cleanups: DDR-02 §6 stale note, DDR-02 Blocks line (C5), DDR-03 capability instantiation (C6), confirm api-key field name (C7).
4. Project risks already correctly flagged (not review defects): DDR-03 D6 (Groq batch audio support — verify before sprint), DDR-05 D1/D7 (whisperx dep matrix), DDR-06 D1 (PyPI name availability).
