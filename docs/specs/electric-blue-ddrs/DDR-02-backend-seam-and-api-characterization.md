# DDR-02 — Backend Seam + API Characterization Tests

- **Status:** ACCEPTED (Danny review 2026-06-14, PR #3) — decisions resolved below
- **Author:** reed
- **Date:** 2026-06-14
- **Sprint (on approval):** `backend-seam` (next sprint per re-sequence 02 → 04 → 03 → 05 → 06)
- **Depends on:** DDR-01 (scaffolding) — DONE
- **Blocks:** DDR-04 (webhook — built next, on this sync seam), DDR-03 (Groq Batch), DDR-05 (WhisperX)
- **Supersedes:** —

---

## Context

After DDR-01, transcription lives in `src/electric_blue/backends/`:
`backends/__init__.py` exposes `transcribe(cfg, src) -> (segments, info)` and dispatches on
`cfg.backend` to `local.py` (faster-whisper) or `api.py` (OpenAI-compatible HTTP). This is a
thin `if/else`, not an interface. More backends are known-incoming:

- **DDR-05 WhisperX diarization** — a *synchronous* backend that adds *speaker labels*,
  evolving the output schema. Fits the sync seam directly; it is the concrete consumer that
  justifies defining the seam now.
- **DDR-03 Groq Batch** — *asynchronous*: submit a job, poll, retrieve later (~24h window).
  This one does **not** fit a synchronous dispatch — but its accommodation is **deferred** (see
  §3 / D3): it rests on an unverified external (does Groq Batch accept audio?), so the async
  seam is designed in the DDR-03 sprint, not cemented here.

The `api` backend also has **no real test coverage** today — only `local` is exercised
end-to-end by the smoke test, so any refactor of the backend layer is currently unguarded on
the `api` side.

## Principle

Define the extension point *before* extending it — but only for the extension you can see
clearly. A concrete *synchronous* consumer (DDR-05 diarization) plus the untested `api` path
justify defining and pinning the sync seam now; that is not speculative abstraction. The
*asynchronous* extension is deferred until its external dependency is verified, rather than
shaped to an imagined lifecycle. Pin existing behavior with characterization tests *first*, so
the seam refactor is provably behavior-preserving.

## Decision

### 1. A `Backend` interface + registry

Introduce an explicit backend contract — a **`Protocol`** (D1 resolved) — in
`backends/base.py`, and a registry/factory `get_backend(cfg) -> Backend`, an **internal dict**
keyed by `cfg.backend` (D2 resolved). `local` and `api` are refactored to implement it.
`transcribe(cfg, src)` becomes a thin wrapper that resolves the backend and calls it.

Contract:

```python
class Backend(Protocol):
    name: str                         # "local" | "api" | "batch" | "whisperx"
    capabilities: Capabilities        # see below

    def transcribe(self, cfg, src: Path) -> Transcript: ...
```

Where `Transcript` carries `segments: list[Segment]` and `info: TranscriptInfo`
(the dataclasses already exist in `models.py`).

### 2. `Capabilities` flags

A small declarative record each backend exposes, so the watcher/CLI can reason about a
backend without special-casing it:

- `supports_diarization: bool` — speaker labels? (DDR-05 = True)
- `max_upload_mb: int | None` — encode/size guard (api = 24; local = None)
- `needs_network: bool`, `needs_gpu_recommended: bool` — for docs/routing.

> **`is_async` is deferred to DDR-03** (D5 resolution). It only has meaning once an async
> backend exists, and it pairs with the `AsyncBackend` sub-protocol that this DDR no longer
> introduces (D3). DDR-03 adds both `AsyncBackend` and the `is_async` capability together.

### 3. Async seam — DEFERRED to DDR-03 (D3 resolution)

**This DDR defines a synchronous seam only.** The `AsyncBackend` (`submit/poll/fetch`)
sub-protocol originally proposed here is **cut** and moves to the DDR-03 (`groq-batch`) sprint,
to be designed once Groq Batch audio support is verified for real (DDR-03 D6).

Rationale (Danny + Frank, 2026-06-14): the async shape was justified *solely* by DDR-03, whose
lifecycle rests on the unverified assumption that Groq Batch accepts audio transcription.
Cementing a speculative sub-protocol into the foundation is the one real foot-gun here. The
sync `Backend` Protocol, the registry, `Capabilities`, `schema_version`, and the API
characterization tests all stand on their own and need nothing from DDR-03.

All backends in this DDR (`local`, `api`) implement only `transcribe()`. DDR-03 introduces
`AsyncBackend` + the `is_async` capability + the drain/poll path together, anchored to the
*then-proven* batch lifecycle rather than to an imagined one.

### 4. Output-schema versioning (anticipating DDR-05) — policy fixed (D4 resolution, resolves C4)

**Add `"schema_version": 1` to the JSON output now, and the version is data-independent:**

- The number tracks the **schema shape**, never the *content* of a given file. A transcript
  does not get a different `schema_version` because it happens to contain speaker labels.
- **Speaker fields are optional and additive at v1.** When DDR-05 lands diarization, the
  `speaker` field is simply present-or-absent on segments at the *same* `schema_version: 1` —
  adding an optional field is not a breaking change and does not bump the version.
- `schema_version` bumps to 2 only on a **breaking** change (removing/renaming a field,
  changing a type, changing required-ness) — and that is a *future* DDR's decision, not DDR-05's.

This explicitly overrides DDR-05's earlier "diarized docs are v2" proposal (cross-issue **C4**):
there is no "v2 sometimes." DDR-05 must conform — diarization is additive at v1.

### 5. API characterization tests (do these FIRST in the sprint)

Before refactoring, pin the `api` backend with mocked HTTP (no live Groq calls):
- Request shape: multipart upload, `model`, `response_format=verbose_json`,
  `timestamp_granularities[]=segment`, auth header, optional `language`.
- Response parsing: `segments[]` → `Segment`s; fallback to single segment from `text` when no
  timestamps; `duration`/`language` into `TranscriptInfo`; `backend = "api:<model>"`.
- Size-cap: encoded > `max_upload_mb` raises the documented "route to local/batch" error.
- Missing `WHISPER_API_KEY` raises the documented error.
Pin `local` selection/dispatch with a mocked model (the real run stays in the smoke test).

### 6. Ride-along housekeeping

DDR-01 `Status` is now **ACCEPTED** (it was stale at `PROPOSED`; corrected on this branch since
DDR-01's sprint is merged). Done — no remaining action.

---

## Sequencing (within the sprint)

1. Write characterization tests against the *current* `api`/`local` code — all green.
2. Introduce `base.py` (`Backend`/`Capabilities`/`Transcript` — **sync seam only, no `AsyncBackend`**), `get_backend()`.
3. Refactor `local.py`/`api.py` to implement `Backend`; `transcribe()` becomes the wrapper.
4. Add `schema_version: 1` to JSON output, speaker fields optional/additive (+ test).
5. Characterization tests still green (behavior-preserving). Frank gate.

## Risks

- **Premature abstraction** — mitigated: the remaining seam has two concrete sync consumers
  today (`local`, `api`); the one speculative piece (`AsyncBackend`) was cut to DDR-03 per the
  review, so nothing in this DDR is shaped to an unverified consumer.
- ~~Async sub-protocol over-design~~ — **eliminated**: the async seam is deferred to DDR-03
  (D3), where it will be designed against a verified Groq Batch lifecycle.
- **Characterization tests cementing a bug** — call out any current `api` behavior that looks
  wrong during test-writing rather than blindly pinning it.

## Decisions — RESOLVED (Danny review, PR #3, 2026-06-14)

- **D1 — Protocol vs ABC** → **Protocol.** Structural, lighter, Pythonic; the documented lean,
  unchallenged in review. (Revisit only if we later want hard runtime registration guarantees.)
- **D2 — Registry mechanism** → **internal dict** (`{"local": LocalBackend, ...}`).
  Entry-points plugin system is a future DDR if external backends are ever wanted.
- **D3 — Async seam** → **DEFER to DDR-03** (Danny's explicit preference, condition 1). The
  `AsyncBackend` sub-protocol is cut from this DDR; see §3. Removes the only speculative piece
  of the foundation.
- **D4 — `schema_version`** → **start at `1`, data-independent, additive; speakers optional at
  v1** (Danny's condition 2). No "v2 sometimes." See §4. Resolves cross-issue **C4**.
- **D5 — Capability-flag set** → keep `supports_diarization`, `max_upload_mb`, `needs_network`,
  `needs_gpu_recommended`; **`is_async` moves to DDR-03** with `AsyncBackend` (it has no meaning
  without an async backend). See §2.

### Forward note — DDR-03 ⇄ DDR-04 completion-hook contract (C1–C3)

Not in this DDR's scope, but tracked here for the foundation. **Resolved (Frank's call,
2026-06-14):** because the re-sequence builds DDR-04 first — the sprint that *freezes* the
notification payload — the timing contract is decided **in DDR-04 now**, not deferred to "the
second DDR." DDR-04 v1 carries `started_at` / `finished_at` as canonical ISO-8601 timestamps
with `wall_sec` derived as their difference; this is async-safe by construction, so DDR-03's
drain simply supplies the two instants from `JobRecord.submitted_at` / `completed_at` with **no
schema change**. The earlier `now - t_start` wall-clock — a fabrication across a ~24h batch
boundary — is gone. (C1–C3 closed in DDR-04 §1/§7.)
