# Implementation Roadmap: backend-seam

- **Sprint:** backend-seam
- **DDR:** DDR-02 (ACCEPTED, 2026-06-14)
- **Issue:** #4
- **Author:** reed
- **Date:** 2026-06-14
- **Status:** READY

---

## Overview

Five ordered slices implement the backend seam. The sequencing constraint is non-negotiable
(DDR-02 §5, §Sequencing): characterization tests run green against the **current unrefactored
code** before any seam code is touched. Every subsequent slice boundary must leave those same
tests green. The Frank gate is the final acceptance checkpoint — verdict must be SHIP.

---

## Dependency Order Summary

```
Slice 1 (char tests, pre-refactor)
    └─► Slice 2 (base.py — Protocol + types)
            └─► Slice 3 (LocalBackend + ApiBackend + registry + thin wrapper)
                    └─► Slice 4 (schema_version: 1 + test)
                            └─► Slice 5 (full gate + smoke + Frank)
```

No circular dependencies. Each slice has exactly one set of predecessors.

---

## Slice Overview

| Slice | Title | Depends On | Files Created/Modified |
|-------|-------|------------|------------------------|
| S1 | Characterization Tests (Pre-Refactor) | — | `tests/test_char_api.py` (new), `tests/test_char_local.py` (new) |
| S2 | Backend Protocol, Capabilities, Transcript | S1 | `src/electric_blue/backends/base.py` (new) |
| S3 | Registry, get_backend(), LocalBackend, ApiBackend | S1, S2 | `backends/__init__.py` (mod), `backends/local.py` (mod), `backends/api.py` (mod), `tests/test_backends_registry.py` (new), `tests/test_char_local.py` (mod) |
| S4 | schema_version: 1 in JSON Output | S1, S2, S3 | `src/electric_blue/outputs.py` (mod), `tests/test_outputs.py` (mod) |
| S5 | Full Gate + Smoke + Frank | S1–S4 | (none — verification only) |

---

## Behavior-Preservation Checkpoints

Char tests must be green at the end of **every** slice boundary:

| After Slice | Checkpoint | Significance |
|-------------|------------|--------------|
| S1 | All 22 char tests green vs. pre-refactor code | Establishes the behavioral baseline |
| S3 | 21 surviving char tests green vs. refactored code; `test_dispatch_unknown_backend_routes_local` removed (expected) | Proves behavior-preservation through the seam; one owned exception |
| S4 | 21 char tests green after schema_version addition | Confirms output change does not break backends |
| S5 | 21 char tests green under `make gate` | Final confirmation before Frank review |

The mechanism that makes this work: all char tests call through the stable
`backends.transcribe(cfg, src)` public entry point. All 22 char tests are written and passing
against the pre-refactor code in S1. ALL survive the refactor unchanged EXCEPT
`test_dispatch_unknown_backend_routes_local` (in `tests/test_char_local.py`), which is the ONE
deliberately-replaced test: it pins the current silent-local-fallback behavior (the `else`
catch-all in `__init__.py` routes any non-`"api"` value to local), and is removed in S3 when
the registry refactor makes it break as expected. The remaining 21 char tests — the 20 API
tests in `test_char_api.py` and `test_local_dispatch_returns_segments_and_info` in
`test_char_local.py` — require zero edits across the refactor, so the comparison is exact.

---

## Slice Definitions

---

### Slice 1 — Characterization Tests (Pre-Refactor)

**Goal:** Write and commit characterization tests for the `api` backend (mocked HTTP) and the
`local` dispatch (mocked model) that pass green against the current unrefactored code, establishing
a behavioral baseline before any seam code is changed.

**Depends On:** — (none)

**Files:**
- `tests/test_char_api.py` — CREATE — 20 API characterization test functions (mocked `requests.post` and `extract`)
- `tests/test_char_local.py` — CREATE — 2 local dispatch characterization tests (mocked `_get_model` and `extract`)

**Concrete Steps:**

1. Create `tests/test_char_api.py`. Add a module-level fixture that builds a base `cfg` with
   `backend="api"`, `api_key="sk-test"`, `api_model="whisper-large-v3-turbo"`,
   `api_base_url="https://api.groq.com/openai/v1"` using `dataclasses.replace(Config.from_env(), ...)`.
2. Add module-level helpers `make_response(payload)` (returns `MagicMock` with `.json()` and
   `.raise_for_status()`), and `fake_extract(cfg, src, dst, *, compressed)` (writes
   `b"x" * 100` to `dst`). Both are documented in architecture §8.2–§8.3.
3. Write the following 20 test functions. Each patches `electric_blue.backends.api.extract`
   with `fake_extract` and `requests.post` with `make_response(...)` (except `test_api_missing_key_raises`
   which needs no extract patch because the guard fires first, and `test_api_size_limit_si_boundary`
   which uses a custom extract stub that writes a precise byte count — see note below):
   - `test_api_post_url` — assert `mock_post.call_args[0][0] == f"{cfg.api_base_url}/audio/transcriptions"`
   - `test_api_post_form_data` — assert `data["model"]`, `data["response_format"] == "verbose_json"`,
     `data["timestamp_granularities[]"] == "segment"`
   - `test_api_post_auth_header` — assert `headers["Authorization"] == "Bearer sk-test"`
   - `test_api_post_language_when_set` — `dataclasses.replace(cfg, language="fr")` → `data["language"] == "fr"`
   - `test_api_post_language_absent_when_none` — `language=None` → `"language" not in data`
   - `test_api_response_segments_parsed` — response with `segments` list → returned `list[Segment]`
     with matching `.start`, `.end`, `.text.strip()`
   - `test_api_response_fallback_single_segment` — response with no `segments` but `text` and
     `duration` → `[Segment(start=0.0, end=duration, text=text.strip())]`
   - `test_api_response_empty_segments_empty_text` — both absent/empty → `[]`, no exception,
     `TranscriptInfo` still populated
   - `test_api_info_language_from_response` — response `language` field → `info.language` matches
   - `test_api_info_language_fallback_cfg` — response missing `language`, `cfg.language="en"` →
     `info.language == "en"`
   - `test_api_info_language_fallback_unknown` — response missing `language`, `cfg.language=None` →
     `info.language == "unknown"`
   - `test_api_info_duration` — response `duration: 42.5` → `info.duration == 42.5`
   - `test_api_info_duration_missing` — response missing `duration` → `info.duration == 0.0`
   - `test_api_info_backend_string` — `info.backend == f"api:{cfg.api_model}"`
   - `test_api_info_language_probability_none` — any successful API response → assert
     `info.language_probability is None`; pins FLAG-C (architecture §3): the API path never
     receives a confidence score from the Groq/OpenAI endpoint, so `TranscriptInfo.language_probability`
     must be `None` (serializes to JSON `null`). The refactor must not silently change this to a
     default float. (Maps to US-01 AC — behavior-preservation of the info fields.)
   - `test_api_size_limit_raises` — `dataclasses.replace(cfg, api_max_mb=0)` → `RuntimeError`
     with `"Route this one to the local/batch folder"` in message and file size (in MB) in message
   - `test_api_size_limit_si_boundary` — pins the SI-MB (`/ 1e6`) semantics of the size check
     (FLAG-B, architecture §3). Use a custom extract stub that writes exactly **1,048,576 bytes**
     (= 1 MiB) to `dst`, and `dataclasses.replace(cfg, api_max_mb=1)`. Assert `RuntimeError` is
     raised, because `1_048_576 / 1e6 = 1.048576 > 1.0` (SI). If the implementation used MiB
     division (`/ (1024 * 1024)`), the check would yield `1.0 > 1.0 = False` and no error would
     be raised — the test would fail. This concretely pins SI-MB and would catch a silent change
     from `/1e6` to `/(1024*1024)`. (Maps to US-01 AC — size-limit enforcement.)
   - `test_api_missing_key_raises` — `dataclasses.replace(cfg, api_key="")` → `RuntimeError`
     with `"WHISPER_API_KEY is not set"` in message
   - `test_api_post_files_and_timeout` — via `mock_post.call_args.kwargs`: assert
     `files["file"][0] == "a.mp3"` (filename tuple element), `files["file"][2] == "audio/mpeg"`
     (MIME type tuple element), and `timeout == 600`; pins the verbatim POST shape that the
     refactor must copy exactly (api.py:35–41)
   - `test_api_raise_for_status_called` — assert
     `mock_post.return_value.raise_for_status.assert_called_once()`; confirms that HTTP errors
     surface rather than being swallowed (api.py:42)

   **Note on test 15 (size_limit_raises):** the error message template is
   `f"{src.name}: encoded audio is {size_mb:.0f} MB (> {cfg.api_max_mb} MB cap). Route this one
   to the local/batch folder, or chunk it."` — pin the exact phrase `"Route this one to the
   local/batch folder"`.

   **Note on test 16 (missing_key):** the `api_key` check fires before `extract()` is even called,
   so the extract mock is not needed for this test.

   **Note on hermeticity (G7):** All characterization tests in `test_char_api.py` must be hermetic
   — no live network calls, no real `WHISPER_API_KEY` required. `requests.post` is always replaced
   by `MagicMock`; `Config` fields are set via `dataclasses.replace`, never read from the real
   environment. Tests must be deterministic in CI with no secrets present. Additionally,
   `Config.from_env()` reads the REAL `os.environ` at call time; each test MUST
   `dataclasses.replace` every field it asserts on and never rely on an env-derived default, so
   CI runs with stray `WHISPER_*` environment variables remain deterministic.

4. Create `tests/test_char_local.py`. Add the `FakeSegmentInfo`, `FakeSegment`, `FakeWhisperModel`
   helpers documented in architecture §8.4.
5. Write the following 2 local dispatch test functions:

   **`test_local_dispatch_returns_segments_and_info`:** patch
   `electric_blue.backends.local.extract` with `fake_extract` and
   `electric_blue.backends.local._get_model` with `lambda cfg: FakeWhisperModel()`. Call
   `transcribe(cfg, src)` with `backend="local"`. Assert returned value is
   `tuple[list[Segment], TranscriptInfo]`, all segments are `Segment` instances, and
   `info.backend.startswith("local:")`.

   **`test_dispatch_unknown_backend_routes_local` (PRE-REFACTOR ONLY):** patch
   `electric_blue.backends.local.extract` with `fake_extract` and
   `electric_blue.backends.local._get_model` with `lambda cfg: FakeWhisperModel()`. Build
   `cfg = dataclasses.replace(Config.from_env(), backend="bogus")`. Call `transcribe(cfg, src)`
   and assert it returns without raising, `isinstance(segments, list)`,
   `isinstance(info, TranscriptInfo)`, and `info.backend.startswith("local:")` — confirming
   the `else` catch-all silently routes the unknown backend to local. Include a docstring
   marking this as PRE-REFACTOR ONLY: this test is EXPECTED to break in slice S3 (after the
   registry lands, `get_backend()` raises `RuntimeError` for `"bogus"`). It is superseded by
   `test_get_backend_unknown_raises` in `tests/test_backends_registry.py`, which encodes the
   ONE deliberately-replaced behavior change. Do not attempt to keep this test green past S3.

6. Run the test suite once to confirm all 22 new tests pass and no existing tests regress.

**Verification Gate:**

```bash
pytest tests/test_char_api.py tests/test_char_local.py -v
```

Pass condition: all 22 tests collect and pass (0 failures, 0 errors). No live HTTP calls
are made; the mock seam intercepts all `requests.post` calls. No real model is loaded.

```bash
pytest -m "not smoke"
```

Pass condition: all pre-existing tests plus the 22 new ones pass. This confirms the
characterization tests do not disturb any existing test.

Maps to requirements: US-01 all ACs (including FLAG-B SI-MB semantics and FLAG-C
`language_probability=None`), US-02 all ACs.

**Rollback/Safety Note:** This slice creates new files only. Rollback = delete the two new
test files. Zero risk to existing code.

---

### Slice 2 — Backend Protocol, Capabilities, Transcript (base.py)

**Goal:** Create `backends/base.py` with the `Backend` Protocol, `Capabilities` dataclass,
and `Transcript` dataclass — the typed contract for the sync seam — with no behavior change.

**Depends On:** S1

**Files:**
- `src/electric_blue/backends/base.py` — CREATE — `Backend`, `Capabilities`, `Transcript`

**Concrete Steps:**

1. Create `src/electric_blue/backends/base.py` with the exact content from architecture §5.1:
   - Module docstring noting import direction: `base.py → models.py`, never reverse.
   - Import: `from __future__ import annotations`, `dataclasses.dataclass`, `pathlib.Path`,
     `typing.Protocol`, `..config.Config`, `..models.Segment, TranscriptInfo`.
   - `@dataclass class Capabilities` with fields: `supports_diarization: bool`,
     `max_upload_mb: int | None`, `needs_network: bool`, `needs_gpu_recommended: bool`.
     No `is_async` field (D5, locked).
   - `@dataclass class Transcript` with fields: `segments: list[Segment]`, `info: TranscriptInfo`.
   - `class Backend(Protocol)` with attributes `name: str`, `capabilities: Capabilities`,
     and method `def transcribe(self, cfg: Config, src: Path) -> Transcript: ...`.
2. Do NOT modify `backends/__init__.py`, `backends/local.py`, or `backends/api.py` in this slice.
   The if/else dispatch in `__init__.py` remains intact.
3. Run the verification gate (below) to confirm clean imports and no regressions.

**Verification Gate:**

```bash
python -c "from electric_blue.backends.base import Backend, Capabilities, Transcript; print('OK')"
```

Pass condition: prints `OK` with no import error or `TypeError`.

```bash
pytest tests/test_char_api.py tests/test_char_local.py -v
```

Pass condition: all 22 char tests still pass (no change to behavior — backends untouched).

```bash
make gate
```

Pass condition: `black --check .` clean, `ruff check .` clean, `pytest -m "not smoke"` all green.

Maps to requirements: US-03 all ACs (D1 — Protocol not ABC, D5 — no `is_async`, exact field set).

**Rollback/Safety Note:** This slice creates one new file with no side effects. Rollback = delete
`base.py`. The if/else dispatch still works unmodified.

---

### Slice 3 — Registry, get_backend(), LocalBackend, ApiBackend

**Goal:** Refactor `local.py` and `api.py` to introduce `LocalBackend` and `ApiBackend` classes
implementing the `Backend` Protocol; wire `backends/__init__.py` to dispatch through a
`_REGISTRY` dict via `get_backend(cfg)`, with `transcribe()` becoming the thin wrapper — and
prove behavior-preservation by keeping all 21 surviving char tests green after removing
`test_dispatch_unknown_backend_routes_local` (which breaks at this step as expected).

**Depends On:** S1, S2

**Files:**
- `src/electric_blue/backends/local.py` — MODIFY — Add `LocalBackend` class; remove standalone `transcribe_local()`
- `src/electric_blue/backends/api.py` — MODIFY — Add `ApiBackend` class; move `import requests` to module top; remove standalone `transcribe_api()`
- `src/electric_blue/backends/__init__.py` — MODIFY — Remove if/else block; add `_REGISTRY`, `get_backend()`, thin `transcribe()` wrapper
- `tests/test_backends_registry.py` — CREATE — `get_backend()` error-path test
- `tests/test_char_local.py` — MODIFY — Remove `test_dispatch_unknown_backend_routes_local` (expected break; superseded by `test_get_backend_unknown_raises`)

**Concrete Steps:**

1. **`backends/local.py`:** Add `LocalBackend` class as specified in architecture §6.3.
   - Class attributes (not instance): `name: str = "local"`, `capabilities: Capabilities =
     Capabilities(supports_diarization=False, max_upload_mb=None, needs_network=False, needs_gpu_recommended=True)`.
   - `def transcribe(self, cfg: Config, src: Path) -> Transcript`: body is the current
     `transcribe_local()` logic verbatim, with the final return changed from
     `return segments, transcript_info` to `return Transcript(segments=segments, info=transcript_info)`.
   - The module-level `_model = None` cache and `_get_model(cfg)` helper function remain at
     module level (not instance state). This preserves the mock seam at
     `electric_blue.backends.local._get_model` that the char test patches.
   - Remove the standalone `transcribe_local()` function after `LocalBackend` is in place.
   - Add imports: `from .base import Capabilities, Transcript`.

2. **`backends/api.py`:** Add `ApiBackend` class as specified in architecture §6.4.
   - Move `import requests` from inside `transcribe_api()` to module top (FLAG-A — note this
     in commit message; the mock target `requests.post` is unaffected because both the lazy
     import and the module-top import access the same `requests` module object).
   - Class attributes: `name: str = "api"`, `capabilities: Capabilities = Capabilities(
     supports_diarization=False, max_upload_mb=24, needs_network=True,
     needs_gpu_recommended=False)`. Value `24` is SI megabytes matching `cfg.api_max_mb` default.
   - `def transcribe(self, cfg: Config, src: Path) -> Transcript`: body is the current
     `transcribe_api()` logic verbatim, return type changed to `Transcript(segments=segments, info=info)`.
   - Remove the standalone `transcribe_api()` function.
   - Add imports: `from .base import Capabilities, Transcript`.

3. **`backends/__init__.py`:** Replace the if/else dispatch block with the registry pattern
   as specified in architecture §6.1–§6.2 and §6.5:
   - Add imports: `from .api import ApiBackend`, `from .local import LocalBackend`,
     `from .base import Backend, Transcript`.
   - Add module-level `_REGISTRY: dict[str, Backend] = {"local": LocalBackend(), "api": ApiBackend()}`.
   - Add `get_backend(cfg: Config) -> Backend` function: looks up `cfg.backend` in `_REGISTRY`,
     raises `RuntimeError` with a descriptive message listing available backends if the key is
     absent (not `KeyError` — per architecture §6.1).
   - Replace the if/else `transcribe()` body with:
     `result: Transcript = get_backend(cfg).transcribe(cfg, src)` and
     `return result.segments, result.info`.
   - The public signature `transcribe(cfg: Config, src: Path) -> tuple[list[Segment], TranscriptInfo]`
     is unchanged. Callers (`watcher.py`, `test_smoke.py`, `conftest.py`) need zero edits.

4. **`tests/test_backends_registry.py`:** Write `test_get_backend_unknown_raises` to pin the
   `get_backend()` error path (architecture §6.1, US-04 AC):
   - Import `get_backend` from `electric_blue.backends` and `Config` from `electric_blue.config`.
   - Build a cfg with an unrecognized backend key: `dataclasses.replace(Config.from_env(), backend="bogus_backend_xyz")`.
   - Use `pytest.raises(RuntimeError) as exc_info` to assert the call raises (not `KeyError`).
   - Assert `"bogus_backend_xyz"` appears in `str(exc_info.value)` — the message must name the bad key.
   - Assert at least one of `"local"` or `"api"` appears in `str(exc_info.value)` — the message must
     list available backends so the caller knows what values are valid.
   - This test can only be written in S3 (after `get_backend()` exists). It is not a char test and
     carries no `@pytest.mark.smoke` marker; it runs under `pytest -m "not smoke"`.
   - Maps to: US-04 AC — `get_backend` raises `RuntimeError` on unknown backend key with a
     descriptive message naming the bad key and listing available backends (architecture §6.1).

   **Owned behavior change:** `test_dispatch_unknown_backend_routes_local` in
   `tests/test_char_local.py` breaks at this point (expected) because `get_backend()` now raises
   `RuntimeError` for `"bogus"`. Remove it from `tests/test_char_local.py` in the same commit
   that introduces `tests/test_backends_registry.py` with `test_get_backend_unknown_raises`.
   Silent-local-fallback → explicit `RuntimeError` is the ONE intentional behavior change in this
   sprint (fail-loud over silent-wrong-backend); do NOT restore the old `else` catch-all. The
   replacement test asserts the `RuntimeError` and its message content, encoding what the sprint
   deliberately changes.

5. Run the verification gate (below). The surviving char tests confirm behavior-preservation.

**Verification Gate:**

```bash
pytest tests/test_char_api.py tests/test_char_local.py -v
```

Pass condition: 21 char tests pass — the 20 API tests and `test_local_dispatch_returns_segments_and_info`
run unedited. `test_dispatch_unknown_backend_routes_local` has been removed from
`tests/test_char_local.py` in this slice and is no longer collected. Any failure in the
remaining 21 char tests means the refactor introduced a regression.

```bash
pytest tests/test_backends_registry.py -v
```

Pass condition: `test_get_backend_unknown_raises` passes — `RuntimeError` raised, bad key named
in message, available backends listed in message.

```bash
make gate
```

Pass condition: `black --check .` clean, `ruff check .` clean, `pytest -m "not smoke"` all green.

Maps to requirements: US-04 all ACs (including `get_backend` error path with descriptive
`RuntimeError`), US-05 all ACs, US-06 all ACs.

**Rollback/Safety Note:** If char tests fail after this slice, revert `__init__.py`, `local.py`,
and `api.py` in full. Do not proceed to S4. The if/else dispatch in the pre-slice version of
`__init__.py` is the safe rollback state.

---

### Slice 4 — schema_version: 1 in JSON Output

**Goal:** Add `"schema_version": 1` as the first key of the JSON output payload in `outputs.py`
(one-line change) and add a dedicated gate test asserting its presence.

**Depends On:** S1, S2, S3

**Files:**
- `src/electric_blue/outputs.py` — MODIFY — Add `"schema_version": 1` to JSON payload dict
- `tests/test_outputs.py` — MODIFY — Add `test_json_schema_version()` function

**Concrete Steps:**

1. **`outputs.py` line 52:** Change the JSON payload assembly from:
   ```python
   payload = {**info.to_dict(), "text": full, "segments": seg_dicts}
   ```
   to:
   ```python
   payload = {"schema_version": 1, **info.to_dict(), "text": full, "segments": seg_dicts}
   ```
   This is the exact insertion point from architecture §7. The integer literal `1` is
   data-independent — no condition, no branch. `info.to_dict()` spreads after `schema_version`
   so no info field can overwrite it.

2. **`tests/test_outputs.py`:** Add `test_json_schema_version()` using the existing fixtures
   `cfg_with_output` and `sample_data` as documented in architecture §8.8:
   ```python
   def test_json_schema_version(cfg_with_output, sample_data):
       cfg, out_dir = cfg_with_output
       out_dir.mkdir(parents=True, exist_ok=True)
       segments, info = sample_data
       write_outputs(cfg, out_dir, "clip", segments, info)
       data = json.loads((out_dir / "clip.json").read_text())
       assert data["schema_version"] == 1
       assert isinstance(data["schema_version"], int)
   ```
   No new fixtures needed — the test reuses the existing test infrastructure.

3. Verify the existing `test_json_shape` test still passes (it does not assert a complete key
   set, so the new `schema_version` key is additive and non-breaking).

**Verification Gate:**

```bash
pytest tests/test_outputs.py -v
```

Pass condition: all pre-existing output tests plus `test_json_schema_version` pass. The
assertion `data["schema_version"] == 1` and `isinstance(data["schema_version"], int)` both hold.

```bash
pytest tests/test_char_api.py tests/test_char_local.py -v
```

Pass condition: all 21 char tests still green (behavior-preservation checkpoint — the
`outputs.py` change must not have disturbed backend behavior).

```bash
make gate
```

Pass condition: `black --check .` clean, `ruff check .` clean, `pytest -m "not smoke"` all green.

Maps to requirements: US-07 all ACs (D4 — data-independent, integer not string,
speaker fields optional/additive at v1).

**Rollback/Safety Note:** Both changes are minimal and isolated. If the test fails, revert
the one-line `outputs.py` change and the new test function.

---

### Slice 5 — Full Gate + Smoke + Frank

**Goal:** Run `make gate` and `make smoke` to completion; confirm both are green; hand to
Frank for SHIP verdict.

**Depends On:** S1, S2, S3, S4

**Files:** None created or modified. This slice is a verification gate.

**Concrete Steps:**

1. Run `make gate` (defined as `black --check . && ruff check . && pytest -m "not smoke"`).
   Resolve any remaining formatter or linter findings before the Frank review. No substantive
   logic changes are permitted here — only mechanical formatting fixes.

2. Run `make smoke` (defined as `pytest -m smoke`). The smoke test at `tests/test_smoke.py`
   calls `backends.transcribe(cfg, clip)` with a real tiny faster-whisper model and real ffmpeg.
   This exercises `LocalBackend` end-to-end through the refactored registry path for the first
   time with a real model.

3. Confirm all 21 char tests are included in the `make gate` run and remain green (they carry
   no `@pytest.mark.smoke` marker so they run under `pytest -m "not smoke"`).

4. Submit for Frank review. Frank gate criteria:
   - `make gate` — green (black, ruff, pytest -m "not smoke")
   - `make smoke` — green (real tiny model, real ffmpeg)
   - Verdict: SHIP

**Verification Gate:**

```bash
make gate
```

Pass condition: zero black diffs, zero ruff findings, all non-smoke tests pass (including all
21 char tests, `test_get_backend_unknown_raises`, and `test_json_schema_version`).

```bash
make smoke
```

Pass condition: `pytest -m smoke` exits 0. The smoke test exercises `LocalBackend` through the
registry. No live API calls are required (the smoke test uses the local backend).

Frank gate: SHIP verdict required to close issue #4.

---

## Files NOT Changed This Sprint

The following files are explicitly out of scope. No commit in this sprint may touch them:

| File | Reason |
|------|--------|
| `src/electric_blue/models.py` | `Segment` and `TranscriptInfo` are stable; not modified (US-03 constraint) |
| `src/electric_blue/config.py` | `Config` is consumed, not modified |
| `src/electric_blue/audio.py` | `extract()` is patched in tests, not modified |
| `src/electric_blue/watcher.py` | Caller of `backends.transcribe()` — signature unchanged |
| `src/electric_blue/cli.py` | Routes through `watcher.process()` — unchanged |
| `src/electric_blue/notify.py` | No change |
| `src/electric_blue/__init__.py` | Package root — no change |
| `tests/conftest.py` | `fake_transcribe` patches `electric_blue.watcher.transcribe` — unchanged |
| `tests/test_config.py` | Config tests — unchanged |
| `tests/test_watcher.py` | Patches `electric_blue.watcher.transcribe` — unchanged |
| `tests/test_smoke.py` | End-to-end test — unchanged; exercises registry via `LocalBackend` |
| `pyproject.toml` | No new runtime dependencies added |
| `Makefile` | `gate` and `smoke` targets are already correct |

---

## Deferred Work (Not This Sprint)

The following items are explicitly deferred per DDR-02 decisions and the requirements Out of
Scope section:

| Item | Deferred To |
|------|-------------|
| `AsyncBackend` sub-protocol (`submit` / `poll` / `fetch`) | DDR-03 |
| `is_async` capability flag on `Capabilities` | DDR-03 (added alongside `AsyncBackend`) |
| Groq Batch drain/poll path | DDR-03 |
| Webhook completion payload shape | DDR-04 |
| Diarization / speaker field population on `Segment` | DDR-05 |
| WhisperX backend implementation | DDR-05 |
| `schema_version` bump to 2 or any breaking schema change | Future DDR |
| External plugin system or `entry_points` for backend registration | Future DDR if ever needed |
| Any user-facing UI or CLI surface changes | Not applicable (no UI) |

---

## Sequence Rules

1. Complete each slice fully (gate green) before starting the next.
2. No partial slice work — if a gate fails, fix forward in the same slice before advancing.
3. If blocked (ambiguity, missing information, gate failure not resolvable in-slice) → HALT.
   Do not skip ahead.
4. The char tests in S1 are the behavior-preservation lock. If they fail at any slice boundary
   S3–S5, treat it as a HALT condition: stop, identify the regression, and revert to the last
   green state.
5. No substantive logic changes are permitted in S5 — only mechanical fixes (formatting).
   Any logic change in S5 requires reopening S3 or S4 as appropriate.
