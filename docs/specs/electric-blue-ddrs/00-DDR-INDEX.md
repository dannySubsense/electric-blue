# DDR Index — electric-blue

The backlog, in **dependency order**. Each DDR is a design decision record; once you approve
one it converts to a sprint: DDR → GitHub issue → `/spec-start` → Frank → `/forge-start` →
Frank → PR. DDR-01 (scaffolding) shipped as the bootstrap exception; **DDR-02 onward use the
full loop.**

## The list

| DDR | Title | Status | Sprint | Depends on | Scope (one line) |
|-----|-------|--------|--------|-----------|------------------|
| 01 | Project scaffolding | ✅ ACCEPTED (shipped, PR #2) | `project-scaffolding` | — | Installable package, test gate, CI, public README. |
| 02 | Backend seam + API characterization | PROPOSED | `backend-seam` | 01 | Define the `Backend`/`AsyncBackend` interface + registry; pin the untested `api` path; add `schema_version`. **Foundation — blocks 03 & 05.** |
| 03 | Groq Batch backend | PROPOSED | `groq-batch` | 02 | Async (submit/poll/fetch) backend: ~50% cheaper bulk, ~24h turnaround; job-state store + `--drain-batch`. |
| 04 | Completion-ping webhook | PROPOSED | `completion-webhook` | 02 (03/05 fire it) | Formalize `notify()`: versioned payload, success/failure events, retries, redaction, provider formatters. |
| 05 | WhisperX diarization | PROPOSED | `whisperx-diarization` | 02 | Speaker labels via WhisperX + pyannote; evolves output schema (optional `speaker`); heavy optional deps, GPU, HF-gated models. |
| 06 | Publish to PyPI | PROPOSED | `pypi-publish` | 05 (schema stable) | `pip install electric-blue`: metadata, semver, OIDC Trusted Publishing, TestPyPI gate. **Last — freezes the public surface.** |

## Why this order (dependency, not convenience)

1. **Seam first (02)** — two new backends are coming; design the extension point and pin the
   untested `api` path *before* extending, or we build two backends ad hoc and refactor later.
2. **Batch (03)** — additive and closest to the existing `api` backend, so it's the cheapest
   way to *validate the seam* (especially the async sub-protocol).
3. **Webhook (04)** — observability you want *before* you lean on jobs you don't sit and watch
   (overnight batches, long diarization runs).
4. **Diarization (05)** — biggest lift, changes the output schema; do it once the seam is
   proven and notifications exist. Last *feature*.
5. **PyPI (06)** — publishing freezes a semver public surface; do it after the schema settles.

The one defensible swap: move **04 before 03** if you'd rather have notifications in hand
before any new backend work.

## Decisions to pre-resolve (so sprints don't stall)

Resolve **DDR-02's** decisions first — it blocks 03 and 05:
- **D1** Protocol vs ABC for `Backend` (lean: Protocol)
- **D2** Registry: internal dict vs entry-points plugin (lean: dict)
- **D3** Fix the async `submit/poll/fetch` shape in 02 vs defer to 03 (lean: fix here)
- **D4** `schema_version` starting value + bump policy — **also resolves cross-issue C4**
- **D5** Capability-flag set

Then the per-DDR decisions: **03** has D1–D10 (most critical: *verify Groq Batch supports the
audio endpoint* before any code), **04** D1–D6 (payload/providers/retries/HMAC), **05** D1–D7
(WhisperX vs alternatives; HF gated-model ToS on a public repo), **06** D1–D8 (PyPI name
availability; OIDC vs token).

## Cross-cutting issues (from `DDR-REVIEW.md` — no HIGH blockers)

- **C1–C3 (MED)** — the **DDR-03 ⇄ DDR-04 completion-hook contract**: signatures don't yet
  align, the failure/expiry branch has no hook call site, and DDR-04's wall-clock timing is
  meaningless across a ~24h batch boundary (use `JobRecord.submitted_at`/`completed_at`).
  Resolve the hook contract for 03 and 04 together.
- **C4 (MED)** — `schema_version` bump policy is split between DDR-02 D4 and DDR-05 D3; decide
  it in DDR-02.
- **4 × LOW** cleanups noted in `DDR-REVIEW.md`.

## Suggested first move tomorrow

Resolve DDR-02 D1–D5 (+ C4), approve DDR-02, open its issue, and run the first full-loop
sprint (`backend-seam`). 03/04/05 unblock from there; settle the C1–C3 hook contract when you
take 03 and 04.

## Files

- `DDR-01..06-*.md` — the records.
- `DDR-REVIEW.md` — independent cross-consistency review.
- `00-DDR-INDEX.md` — this file.
