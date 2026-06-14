# Requirements: backend-seam

- **Sprint:** backend-seam
- **DDR:** DDR-02 (ACCEPTED, 2026-06-14)
- **Issue:** #4
- **Author:** reed
- **Date:** 2026-06-14
- **Status:** READY
- **Acceptance Criteria:** 40

---

## Summary

Replace the current if/else backend dispatch in `backends/__init__.py` with an explicit
synchronous `Backend` Protocol, an internal-dict registry, and a `get_backend(cfg)` factory.
Pin the currently-untested `api` path with characterization tests FIRST so the refactor is
provably behavior-preserving. Add `schema_version: 1` to JSON output. This sprint is
behavior-preserving for all currently-working paths EXCEPT one deliberate, owned tightening:
unrecognized `cfg.backend` values that previously fell through silently to the local backend
will now raise a `RuntimeError`. This single exception is tested on both sides and is the
only intentional behavior change in the sprint.

---

## Fixed Constraints (DDR-02 decisions — do not reopen)

| ID | Constraint |
|----|------------|
| D1 | `Backend` uses `typing.Protocol`, not `ABC` |
| D2 | Registry is an internal `dict` keyed by `cfg.backend`; `get_backend(cfg) -> Backend`; `transcribe(cfg, src)` becomes a thin wrapper |
| D3 | No `AsyncBackend` this sprint; deferred to DDR-03 |
| D4 | `schema_version: 1` in JSON output; data-independent; speaker fields optional and additive at v1; no "v2 sometimes" |
| D5 | `Capabilities` fields: `supports_diarization`, `max_upload_mb`, `needs_network`, `needs_gpu_recommended`; no `is_async` this sprint |

---

## User Stories

### US-01 — API Characterization Tests (pre-refactor, mocked HTTP)

As a developer refactoring the backend layer,
I want the `api` backend's current behavior pinned by mocked-HTTP characterization tests
written against the existing code before any refactoring begins,
so that I can prove the refactor is behavior-preserving and catch any regression immediately.

### US-02 — Local Backend Dispatch Characterization Test (pre-refactor, mocked model)

As a developer refactoring the backend layer,
I want the current `local` backend dispatch pinned by a characterization test that uses a
mocked `WhisperModel` (no real model load),
so that the registry switch cannot silently break local dispatch without a test failure.

### US-03 — Backend Protocol and Capabilities in base.py

As a developer adding a new transcription backend,
I want a `Backend` Protocol and a `Capabilities` dataclass defined in `backends/base.py`,
so that I have a clear, structurally-typed contract to implement with no inheritance required
and no external plugin registration.

### US-04 — Internal Registry and get_backend() Factory

As the drop-folder pipeline,
I want `get_backend(cfg) -> Backend` to resolve the correct backend from an internal dict
keyed by `cfg.backend`,
so that adding or switching backends never requires changing the dispatch call-site.

**Owned behavior change (deliberate, not a regression):** The current if/else dispatch in
`backends/__init__.py` uses `else: ...local...` as a catch-all, so any `cfg.backend` value
that is not `"api"` — including typos, unsupported strings like `"batch"` or `"whisperx"`,
or an empty string — silently executes the local path and returns a normal transcript with
no error. The new registry `get_backend(cfg)` raises `RuntimeError` on any key not in
`{"local", "api"}`. This is a deliberate fail-loud change: silent misdispatch is worse than
an explicit error. It is the ONLY intentional behavior change in this otherwise
behavior-preserving sprint, and it is tested on both sides (pre-refactor characterization
test pins the silent-fallback; post-refactor test asserts the RuntimeError).

**Blast-radius rationale (context, not an AC):** Via `watcher.handle()`, an unhandled
exception routes the dropped file to `failed/` and fires a failure notification. Any
deployment currently relying on the silent-local fallback for a non-canonical
`WHISPER_BACKEND` value (e.g., `WHISPER_BACKEND=batch`) would see every file fail after
this ships. That user impact is why this change must be owned, documented, and tested
rather than buried as a side-effect of the registry refactor.

### US-05 — transcribe() as Thin Wrapper

As the drop-folder pipeline,
I want `transcribe(cfg, src)` in `backends/__init__.py` to remain the single public entry
point but delegate to `get_backend(cfg).transcribe(cfg, src)`,
so that the public API is unchanged and callers require no modification.

### US-06 — local.py and api.py Implement Backend Protocol

As a developer maintaining the backend layer,
I want `LocalBackend` and `ApiBackend` refactored to satisfy the `Backend` Protocol with
correct `Capabilities` values and no behavior change,
so that all characterization tests written in US-01 and US-02 remain green after the
refactor.

### US-07 — schema_version: 1 in JSON Output

As a downstream consumer parsing JSON transcripts,
I want every JSON output file to contain `"schema_version": 1`,
so that future breaking schema changes can be detected by version number without parsing
content fields.

---

## Acceptance Criteria

### US-01 — API Characterization Tests

- [ ] Given a valid `cfg` with `cfg.backend = "api"` and a source file that encodes below
  `api_max_mb`, when `transcribe(cfg, src)` is called with mocked HTTP returning a response
  with `segments`, then a POST request is issued to `{cfg.api_base_url}/audio/transcriptions`
  as `multipart/form-data`.
- [ ] Given the above call, the request body includes `model=cfg.api_model`,
  `response_format=verbose_json`, and `timestamp_granularities[]=segment`.
- [ ] Given the above call, the request `Authorization` header equals `Bearer {cfg.api_key}`.
- [ ] Given `cfg.language` is set, when the request is made, then `language` is included in
  the form data.
- [ ] Given `cfg.language` is `None`, when the request is made, then `language` is absent
  from the form data.
- [ ] Given a response payload with a non-empty `segments` array, when `transcribe`
  parses it, then it returns a `list[Segment]` where each item has `start`, `end`, and
  `text` (stripped) matching the corresponding response segment.
- [ ] Given a response payload where `segments` is empty or absent but `text` is present,
  when parsed, then a single `Segment(start=0.0, end=duration, text=text.strip())` is
  returned.
- [ ] Given a response payload where both `segments` and `text` are absent, when parsed,
  then an empty `list[Segment]` is returned without raising.
- [ ] Given a successful response, when `TranscriptInfo` is populated, then
  `info.language` comes from the response `language` field (falling back to `cfg.language`
  or `"unknown"` if absent), `info.duration` comes from the response `duration` field
  (defaulting to `0.0`), and `info.backend` equals `f"api:{cfg.api_model}"`.
- [ ] Given the encoded audio file exceeds `cfg.api_max_mb`, when `transcribe(cfg, src)` is
  called (with `cfg.backend = "api"`), then a `RuntimeError` is raised whose message contains
  both the file size in MB and the phrase `"Route this one to the local/batch folder"`.
- [ ] Given `cfg.api_key` is empty or falsy, when `transcribe(cfg, src)` is called
  (with `cfg.backend = "api"`), then a `RuntimeError` is raised whose message contains
  `"WHISPER_API_KEY is not set"`.
- [ ] All US-01 tests pass against the current (pre-refactor) code with no live HTTP calls;
  HTTP is fully mocked at the `requests.post` level.

### US-02 — Local Backend Dispatch Characterization Test

- [ ] Given `cfg.backend == "local"`, when `transcribe(cfg, src)` is called with a mocked
  `WhisperModel`, then the local transcription path is exercised and the result is a
  `tuple[list[Segment], TranscriptInfo]`.
- [ ] The test passes against the current (pre-refactor) code with no real model loaded.

### US-03 — Backend Protocol and Capabilities

- [ ] `backends/base.py` exists and defines `Backend` as `typing.Protocol`.
- [ ] `Backend` declares three members: `name: str`, `capabilities: Capabilities`, and
  `def transcribe(self, cfg: Config, src: Path) -> Transcript`.
- [ ] `Transcript` (defined or imported in `base.py`) carries `segments: list[Segment]`
  and `info: TranscriptInfo`, where `Segment` and `TranscriptInfo` are the existing
  dataclasses from `models.py`.
- [ ] `Capabilities` is defined in `base.py` as a dataclass (or equivalent) with exactly
  these fields: `supports_diarization: bool`, `max_upload_mb: int | None`,
  `needs_network: bool`, `needs_gpu_recommended: bool`.
- [ ] `Capabilities` does NOT include an `is_async` field.
- [ ] `LocalBackend` and `ApiBackend` satisfy `Backend` structurally (no explicit
  `Backend` inheritance required; `isinstance(backend, Backend)` via Protocol runtime
  check is a nice-to-have, not required).

### US-04 — Internal Registry and get_backend()

- [ ] `base.py` (or `__init__.py`) contains an internal dict mapping the string `"local"`
  to `LocalBackend` and `"api"` to `ApiBackend`.
- [ ] `get_backend(cfg: Config) -> Backend` returns an instantiated backend from the
  registry dict.
- [ ] Given `cfg.backend` is not a key in the registry, `get_backend` raises a `RuntimeError`
  (not `KeyError`) with a message that identifies the unknown backend name and lists the
  available backends (see the US-04 owned-change ACs and architecture §6.1).
- [ ] Adding a new backend requires only: adding a class implementing `Backend` and
  inserting one entry into the registry dict; no other call-site changes are needed.
- [ ] **[OWNED BEHAVIOR CHANGE — pre-refactor side]** Given the current (pre-refactor)
  if/else dispatch is in place and `cfg.backend` is set to an unrecognized value (e.g.,
  `"batch"`), when `transcribe(cfg, src)` is called with a mocked `WhisperModel`, then the
  call silently executes the local (`else`) path and returns a `tuple[list[Segment],
  TranscriptInfo]` with no exception raised. This behavior is pinned by a pre-refactor
  characterization test committed before any refactor changes are made.
- [ ] **[OWNED BEHAVIOR CHANGE — post-refactor side]** Given the registry-based
  `get_backend(cfg)` is in place and `cfg.backend` is set to an unrecognized value (e.g.,
  `"batch"`), when `get_backend(cfg)` is called, then a `RuntimeError` is raised whose
  message names the bad backend key and lists the available backend keys (`"local"`,
  `"api"`). A post-refactor test asserts this. This is a deliberate fail-loud change and
  the ONLY intentional behavior change in this sprint; all other paths are
  behavior-preserving.

### US-05 — transcribe() as Thin Wrapper

- [ ] `backends/__init__.py` exposes `transcribe(cfg: Config, src: Path) -> tuple[list[Segment], TranscriptInfo]` with the same signature as today.
- [ ] The function body calls `get_backend(cfg).transcribe(cfg, src)` and returns its
  result; it contains no backend-specific logic.
- [ ] The if/else dispatch block is removed.

### US-06 — local.py and api.py Implement Backend Protocol

- [ ] `LocalBackend` in `local.py` has `name = "local"` and `capabilities =
  Capabilities(supports_diarization=False, max_upload_mb=None, needs_network=False,
  needs_gpu_recommended=True)`.
- [ ] `ApiBackend` in `api.py` has `name = "api"` and `capabilities =
  Capabilities(supports_diarization=False, max_upload_mb=24, needs_network=True,
  needs_gpu_recommended=False)`.
- [ ] Both classes implement `transcribe(self, cfg: Config, src: Path) -> Transcript`.
- [ ] All US-01 API characterization tests (which call through `transcribe(cfg, src)` with
  `cfg.backend = "api"`) remain green after the refactor.
- [ ] The US-02 local dispatch characterization test remains green after the refactor.
- [ ] `make gate` (`black --check`, `ruff check`, `pytest -m "not smoke"`) is green.
- [ ] `make smoke` (`pytest -m smoke` with a real tiny model) is green.

### US-07 — schema_version: 1 in JSON Output

- [ ] Given a successful transcription that writes a `.json` output file, the top-level
  JSON object contains `"schema_version": 1` (integer, not string).
- [ ] `schema_version` is `1` regardless of whether segments carry a `speaker` field or
  not; the value is data-independent.
- [ ] A dedicated automated test (not smoke) asserts `schema_version == 1` in the JSON
  output.
- [ ] The test passes under `make gate`.

---

## Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| API response: `segments` key present but empty list, `text` present | Single-segment fallback: `Segment(0.0, duration, text.strip())` |
| API response: `segments` key absent entirely, `text` present | Treat same as empty list; single-segment fallback |
| API response: `segments` empty, `text` absent or empty | Return empty `list[Segment]`; `TranscriptInfo` still populated; no exception |
| API response: `language` field absent | `TranscriptInfo.language` falls back to `cfg.language` if set, else `"unknown"` |
| API response: `duration` field absent | `TranscriptInfo.duration` defaults to `0.0` |
| `cfg.api_key` is empty string (falsy) | `RuntimeError` before any HTTP call is made |
| `cfg.backend` value not in registry (post-refactor) | `RuntimeError` naming bad key + listing available backends; no silent fallback. DELIBERATE change from pre-refactor behavior (see US-04 owned-change ACs). |
| `cfg.backend` value not in registry (pre-refactor) | Silent else-branch executes local path; normal transcript returned; no error. Pinned by characterization test before refactor. |
| JSON output for a transcript with no `speaker` field on segments | Valid v1; `schema_version` is still `1`; absence of `speaker` is not an error |
| `cfg.language` is `None` (not set) | `language` field omitted from API request form data; not sent as `"None"` |
| Encoded audio exactly equal to `api_max_mb` (boundary) | Behavior follows current code: check is `> cfg.api_max_mb`, so exactly equal passes |

---

## Out of Scope

- NOT: `AsyncBackend` sub-protocol (`submit` / `poll` / `fetch` lifecycle) — deferred to DDR-03
- NOT: `is_async` capability flag — deferred to DDR-03 alongside `AsyncBackend`
- NOT: Groq Batch drain/poll path — DDR-03
- NOT: Diarization or speaker field population on `Segment` — DDR-05
- NOT: `schema_version` bump to 2 or any breaking schema change — future DDR
- NOT: External plugin system or `entry_points` for backend registration — future DDR if ever needed
- NOT: Webhook completion payload shape — DDR-04 (next sprint after this one)
- NOT: WhisperX backend implementation — DDR-05
- NOT: Any user-facing UI, configuration UI, or CLI surface changes
- NOT: Changes to `Segment` or `TranscriptInfo` dataclass fields in `models.py`
- NOT: Live HTTP calls in automated tests under `make gate`
- NOT: Validation of `WHISPER_BACKEND` env var at config-load time (no range-check added to `config.py` this sprint; the registry raises on dispatch, not at construction)

---

## Constraints

- Must: `Backend` is `typing.Protocol`, not `ABC` (D1 — locked)
- Must: Registry is a plain `dict`; `get_backend(cfg: Config) -> Backend` is the factory;
  `transcribe(cfg, src)` is the thin wrapper (D2 — locked)
- Must: Characterization tests for `api` and `local` are written and pass against the
  current (pre-refactor) code before any refactor commits are made (sequencing constraint
  from DDR-02 §Sequencing)
- Must: Pre-refactor characterization test pins the silent-local-fallback behavior for
  unknown `cfg.backend` values BEFORE the registry is introduced (US-04 owned-change ACs)
- Must: Post-refactor test asserts `RuntimeError` on unknown `cfg.backend` values after the
  registry is in place; the error message must name the bad key and list available backends
- Must: `make gate` and `make smoke` are both green at end of sprint (Frank gate = SHIP)
- Must: `schema_version: 1` is data-independent; value never changes based on content (D4)
- Must: `Capabilities` carries exactly `{supports_diarization, max_upload_mb, needs_network,
  needs_gpu_recommended}` — no `is_async` (D5 — locked)
- Must not: Introduce `AsyncBackend` or any async dispatch path (D3 — locked)
- Must not: Make live HTTP or Groq API calls in any test running under `make gate`
- Must not: Change the public signature of `transcribe(cfg, src) -> tuple[list[Segment], TranscriptInfo]`
- Assumes: `Segment` and `TranscriptInfo` in `models.py` are not structurally changed this sprint
- Assumes: `Config.api_max_mb` remains `24` (set in `Config.from_env`); `ApiBackend.capabilities.max_upload_mb` must match this value
- Assumes: `Config.backend` is already lower-cased at construction time (see `Config.from_env`)
