# DDR-02 — Backend Seam + API Characterization Tests

- **Status:** PROPOSED (awaiting Danny review)
- **Author:** reed
- **Date:** 2026-06-14
- **Sprint (on approval):** `backend-seam`
- **Depends on:** DDR-01 (scaffolding) — DONE
- **Blocks:** DDR-03 (Groq Batch), DDR-05 (WhisperX) — both add backends through this seam
- **Supersedes:** —

---

## Context

After DDR-01, transcription lives in `src/electric_blue/backends/`:
`backends/__init__.py` exposes `transcribe(cfg, src) -> (segments, info)` and dispatches on
`cfg.backend` to `local.py` (faster-whisper) or `api.py` (OpenAI-compatible HTTP). This is a
thin `if/else`, not an interface. Two more backends are known-incoming:

- **DDR-03 Groq Batch** — *asynchronous*: submit a job, poll, retrieve later (~24h window).
- **DDR-05 WhisperX diarization** — adds *speaker labels*, changing the output schema.

Neither slots cleanly into a synchronous two-function dispatch. The `api` backend also has
**no real test coverage** today — only `local` is exercised end-to-end by the smoke test, so
any refactor of the backend layer is currently unguarded on the `api` side.

## Principle

Define the extension point *before* extending it. Two concrete backends are coming; designing
the seam now is justified, not speculative abstraction. Pin existing behavior with
characterization tests *first*, so the seam refactor is provably behavior-preserving.

## Decision

### 1. A `Backend` interface + registry

Introduce an explicit backend contract (Protocol or ABC — see Decision D1) in
`backends/base.py`, and a registry/factory `get_backend(cfg) -> Backend` keyed by
`cfg.backend`. `local` and `api` are refactored to implement it. `transcribe(cfg, src)`
becomes a thin wrapper that resolves the backend and calls it.

Proposed contract (shape, not final — fields flagged below):

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

- `is_async: bool` — does it complete in one call, or submit-then-retrieve? (DDR-03 = True)
- `supports_diarization: bool` — speaker labels? (DDR-05 = True)
- `max_upload_mb: int | None` — encode/size guard (api = 24; local = None)
- `needs_network: bool`, `needs_gpu_recommended: bool` — for docs/routing.

### 3. Async-capable seam (the load-bearing decision)

Because DDR-03 is asynchronous, the seam must accommodate a two-phase backend **without**
forcing the synchronous backends to fake it. Proposed: an optional async sub-protocol —

```python
class AsyncBackend(Protocol):           # opt-in; only batch implements it
    def submit(self, cfg, src) -> JobRef: ...
    def poll(self, cfg, job: JobRef) -> JobStatus: ...
    def fetch(self, cfg, job: JobRef) -> Transcript: ...
```

Synchronous backends (`local`, `api`, `whisperx`) implement only `transcribe()`. The watcher
calls `transcribe()` for sync backends; async backends are driven by a separate drain/poll
path defined in DDR-03. **This DDR fixes the *shape* of the async seam so DDR-03 has a stable
anchor; the job-store and polling mechanism are DDR-03's scope.**

### 4. Output-schema versioning (anticipating DDR-05)

DDR-05 will add speaker labels, changing the JSON output. To avoid a breaking change later,
**add a `schema_version` field to the JSON output now** (e.g. `"schema_version": 1`), and keep
`speaker`-type fields optional/additive from the start. This is a one-line addition in DDR-02
that saves a breaking migration in DDR-05.

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

Bump **DDR-01 `Status: PROPOSED` → `ACCEPTED`** in this branch (DDR-01's sprint is merged; the
file is just stale).

---

## Sequencing (within the sprint)

1. Write characterization tests against the *current* `api`/`local` code — all green.
2. Introduce `base.py` (`Backend`/`AsyncBackend`/`Capabilities`/`Transcript`), `get_backend()`.
3. Refactor `local.py`/`api.py` to implement `Backend`; `transcribe()` becomes the wrapper.
4. Add `schema_version` to JSON output (+ test).
5. Characterization tests still green (behavior-preserving). Frank gate.

## Risks

- **Premature abstraction** — mitigated: two concrete consumers (DDR-03/05) define the
  requirements; the seam is shaped to them, not to imagined ones.
- **Async sub-protocol over-design** — mitigated: only the *shape* is fixed here; mechanism is
  DDR-03. If DDR-03 review reshapes it, that's expected and cheap (no backend uses it yet).
- **Characterization tests cementing a bug** — call out any current `api` behavior that looks
  wrong during test-writing rather than blindly pinning it.

## Open questions / DECISIONS TO FLAG (resolve with Danny, do not block drafting)

- **D1 — Protocol vs ABC** for `Backend`. Protocol = structural, lighter, no inheritance;
  ABC = explicit `register`, runtime enforcement. *Lean: Protocol* (simpler, Pythonic), but
  ABC if we want hard runtime guarantees. **DECISION.**
- **D2 — Registry mechanism.** Internal dict (`{"local": LocalBackend, ...}`) vs Python
  entry-points plugin system (third parties can ship backends). *Lean: internal dict now*;
  entry-points is a future DDR if we ever want external backends. **DECISION.**
- **D3 — Async seam now vs defer to DDR-03.** Fix the `submit/poll/fetch` shape here (my
  proposal) so DDR-03 anchors to it, or leave the seam sync-only and let DDR-03 introduce the
  async shape. *Lean: fix the shape here.* **DECISION.**
- **D4 — `schema_version` starting value + policy** (1? semantic? where documented).
  **DECISION.**
- **D5 — Capability-flag set** — is the proposed set (D2 §2) right, or over/under-specified?
  **DECISION.**
