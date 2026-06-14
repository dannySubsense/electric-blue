# DDR Index — electric-blue

The backlog, in **dependency order**. Each DDR is a design decision record; once you approve
one it converts to a sprint: DDR → GitHub issue → `/spec-start` → Frank → `/forge-start` →
Frank → PR. DDR-01 (scaffolding) shipped as the bootstrap exception; **DDR-02 onward use the
full loop.**

> **Build order (re-sequenced, Danny + Frank 2026-06-14): `02 → 04 → 03 → 05 → 06`.**
> The dependency table below is unchanged, but DDR-04 (webhook) is built *before* DDR-03
> (Groq Batch): 04 is fully implementable today on DDR-02's sync seam, while 03 is blocked
> behind an unverified external (does Groq Batch accept audio? — DDR-03 D6). Don't stall the
> queue behind Groq verification — do the webhook while the Groq docs get checked.

## The list

| DDR | Title | Status | Sprint | Depends on | Scope (one line) |
|-----|-------|--------|--------|-----------|------------------|
| 01 | Project scaffolding | ✅ ACCEPTED (shipped, PR #2) | `project-scaffolding` | — | Installable package, test gate, CI, public README. |
| 02 | Backend seam + API characterization | ✅ ACCEPTED (PR #3, decisions resolved) | `backend-seam` | 01 | Define the **sync** `Backend` interface + registry; pin the untested `api` path; add `schema_version: 1`. `AsyncBackend` deferred to 03. **Foundation — blocks 03 & 05.** |
| 03 | Groq Batch backend | PROPOSED | `groq-batch` | 02 | Async (submit/poll/fetch) backend: ~50% cheaper bulk, ~24h turnaround; job-state store + `--drain-batch`. |
| 04 | Completion-ping webhook | PROPOSED | `completion-webhook` | 02 (03/05 fire it) | Formalize `notify()`: versioned payload, success/failure events, retries, redaction, provider formatters. |
| 05 | WhisperX diarization | PROPOSED | `whisperx-diarization` | 02 | Speaker labels via WhisperX + pyannote; evolves output schema (optional `speaker`); heavy optional deps, GPU, HF-gated models. |
| 06 | Publish to PyPI | PROPOSED | `pypi-publish` | 05 (schema stable) | `pip install electric-blue`: metadata, semver, OIDC Trusted Publishing, TestPyPI gate. **Last — freezes the public surface.** |

## Why this build order: `02 → 04 → 03 → 05 → 06`

(Re-sequenced from the original dependency order; DDR-04 moved ahead of DDR-03.)

1. **Seam first (02)** — design the *sync* extension point and pin the untested `api` path
   *before* extending, or we build backends ad hoc and refactor later. (`AsyncBackend` is **not**
   built here — deferred to 03, see DDR-02 §3.)
2. **Webhook (04)** — fully implementable today on DDR-02's sync seam, and it freezes the
   notification payload schema, so it must settle the timing contract (`started_at`/`finished_at`)
   that DDR-03's batch path depends on. Observability you want *before* you lean on jobs you
   don't sit and watch (overnight batches, long diarization runs).
3. **Batch (03)** — async (submit/poll/fetch). **Blocked behind an external unknown** (does
   Groq Batch accept audio? — D6); defines `AsyncBackend` + `is_async` once that's verified, and
   adapts to DDR-04's already-frozen payload. Sequenced after 04 so the queue doesn't stall
   behind Groq verification.
4. **Diarization (05)** — biggest lift, sync, adds optional `speaker` (additive at
   `schema_version: 1`); do it once the seam is proven and notifications exist. Last *feature*.
5. **PyPI (06)** — publishing freezes a semver public surface; do it after the schema settles.

The dependency *graph* still admits `02 → 03 → 04`; we deliberately build `04` before `03`
because `03` is gated on Groq verification and `04` is not.

## Decisions to pre-resolve (so sprints don't stall)

**DDR-02's decisions are RESOLVED** (Danny review, PR #3, 2026-06-14 — see DDR-02 "Decisions"):
- **D1** Protocol vs ABC → **Protocol**
- **D2** Registry → **internal dict** (entry-points = future DDR)
- **D3** Async seam → **DEFER to DDR-03** (`AsyncBackend` cut from the foundation)
- **D4** `schema_version` → **start at 1, data-independent, additive; speakers optional at v1** (resolves **C4**)
- **D5** Capability set → keep diarization/upload/network/gpu flags; **`is_async` moves to DDR-03**

Then the per-DDR decisions: **03** has D1–D10 (most critical: *verify Groq Batch supports the
audio endpoint* before any code), **04** D1–D6 (payload/providers/retries/HMAC), **05** D1–D7
(WhisperX vs alternatives; HF gated-model ToS on a public repo), **06** D1–D8 (PyPI name
availability; OIDC vs token).

## Cross-cutting issues (from `DDR-REVIEW.md` — no HIGH blockers)

- **C1–C3 (MED) — RESOLVED** (Frank's call, 2026-06-14, in DDR-04 §1/§7): the completion-hook
  contract is settled **in DDR-04** (built first), not deferred. The payload carries canonical
  `started_at`/`finished_at` ISO-8601 timestamps with `wall_sec` *derived* as their difference —
  async-safe by construction, so DDR-03's drain supplies the two instants from
  `JobRecord.submitted_at`/`completed_at` with no schema change. The `now - t_start` wall-clock
  fabrication is gone, and the hook signature `(cfg, src, info_or_exc, started_at, finished_at)`
  covers the failure/expiry branch.
- **C4 (MED) — RESOLVED** in DDR-02 D4: `schema_version` is additive at v1; no "v2 sometimes."
- **4 × LOW** cleanups noted in `DDR-REVIEW.md`.

## Next move

DDR-02 is resolved and ACCEPTED; DDR-04's timing/payload contract is resolved (C1–C4 closed).
Next: open the `backend-seam` GitHub issue and run the first full-loop sprint (`/spec-start` →
Frank → `/forge-start` → Frank → PR). 04/03/05 unblock from there (build order `04 → 03 → 05`).

In parallel (cheap externals, ~1h, de-risk later sprints — Frank/Danny condition 4):
verify **Groq Batch audio** support (DDR-03 D6), **PyPI name** availability (DDR-06 D1), and a
dry `pip install ".[local,diarize]"` torch-matrix smoke (DDR-05). None block `backend-seam`.

## Files

- `DDR-01..06-*.md` — the records.
- `DDR-REVIEW.md` — independent cross-consistency review.
- `00-DDR-INDEX.md` — this file.
