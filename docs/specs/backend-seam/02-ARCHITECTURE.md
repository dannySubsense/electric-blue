# Architecture: backend-seam

- **Sprint:** backend-seam
- **DDR:** DDR-02 (ACCEPTED, 2026-06-14)
- **Issue:** #4
- **Author:** reed
- **Date:** 2026-06-14
- **Status:** COMPLETE

---

## 1. Overview

This document specifies the concrete technical design for the synchronous Backend seam.
The refactor introduces `backends/base.py` (Protocol + dataclasses), a registry and factory
in `backends/__init__.py`, and Protocol-conformant `LocalBackend` / `ApiBackend` classes.
The public `transcribe(cfg, src)` signature and all callers are untouched. Characterization
tests are written first against current code to prove behavior-preservation.

---

## 2. Current State (ground truth)

### 2.1 backends/__init__.py — current dispatch

```python
def transcribe(cfg: Config, src: Path) -> tuple[list[Segment], TranscriptInfo]:
    if cfg.backend == "api":
        from .api import transcribe_api
        return transcribe_api(cfg, src)
    else:
        from .local import transcribe_local
        return transcribe_local(cfg, src)
```

Callers that depend on the tuple return type (all must remain unmodified):

| File | Line | Call |
|------|------|------|
| `watcher.py` | 35 | `segments, info = transcribe(cfg, src)` |
| `test_smoke.py` | 77 | `segments, info = transcribe(cfg, clip)` |
| `conftest.py` | 84–87 | `fake_transcribe` returns `(fake_segments, fake_info)` |

### 2.2 backends/api.py — current HTTP seam (authoritative)

`transcribe_api(cfg, src) -> tuple[list[Segment], TranscriptInfo]`

Key facts used to design characterization tests:

- `requests` is imported **lazily inside the function**: `import requests` on line 14
- HTTP call: `requests.post(url, headers=..., data=..., files=..., timeout=600)`
  - URL: `f"{cfg.api_base_url}/audio/transcriptions"` — positional arg
  - Headers: `{"Authorization": f"Bearer {cfg.api_key}"}`
  - Data: `{"model": cfg.api_model, "response_format": "verbose_json", "timestamp_granularities[]": "segment"}`
  - Optional data key: `"language"` — present only when `bool(cfg.language)` is True
  - Files: `{"file": ("a.mp3", fh, "audio/mpeg")}`
  - Timeout: `600`
- `extract()` is imported at module level: `from ..audio import extract`
- Guard order: (1) `api_key` check → (2) `extract()` → (3) size check → (4) HTTP POST
- Size check: `mp3.stat().st_size / 1e6 > cfg.api_max_mb` (SI megabytes; boundary `>` not `>=`)
- `payload.get("segments") or []` — catches both `None` and empty list
- `language_probability=None` — API does not return a confidence score; `None` serializes as JSON `null`
- `r.raise_for_status()` is called immediately after the POST (api.py:42)

### 2.3 backends/local.py — current model seam

`transcribe_local(cfg, src) -> tuple[list[Segment], TranscriptInfo]`

- `WhisperModel` imported lazily **inside `_get_model()`**: `from faster_whisper import WhisperModel`
- Module-level `_model = None` cache persists across calls
- Mock seam: `electric_blue.backends.local._get_model`

### 2.4 outputs.py — current JSON assembly (line 52)

```python
payload = {**info.to_dict(), "text": full, "segments": seg_dicts}
```

This is the exact insertion point for `schema_version: 1`.

---

## 3. Flags — Current Behavior Deviations Worth Noting

These are not blockers but must be pinned by characterization tests as-is.

**FLAG-A — Lazy `import requests`**
`requests` is imported inside `transcribe_api()`, not at module top. The refactor moves it
to module level in `ApiBackend`. The mock target `monkeypatch.setattr("requests.post", ...)`
works for both the pre-refactor lazy import and the post-refactor module-level import
(both cases access `requests.post` via the same module object). No change to test assertions.

**FLAG-B — Size check uses SI megabytes (`/ 1e6`)**
The cap is 24,000,000 bytes, not 25,165,824 (MiB). `cfg.api_max_mb = 24` and
`ApiBackend.capabilities.max_upload_mb = 24` must document this as SI megabytes.
The characterization test must not assume MiB.

**FLAG-C — `language_probability=None` in API response**
`TranscriptInfo.language_probability` is `float | None`. The API backend always sets it to
`None`. The JSON output contains `"language_probability": null`. Downstream consumers must
handle `null`. This is correct existing behavior — the API does not expose a confidence score.

**FLAG-D — Guard order: extract before size check**
`api_key` is checked before extraction (fast fail), but the size check occurs AFTER encoding
to MP3. A caller cannot know if a file exceeds the cap without encoding it first. This is
correct behavior — the cap applies to the ENCODED file, not the source. Characterization
tests must encode (or simulate encoding) before asserting the size error path.

---

## 4. Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `Backend` | `backends/base.py` | `typing.Protocol` declaring the sync seam contract |
| `Capabilities` | `backends/base.py` | Declarative capability record per backend |
| `Transcript` | `backends/base.py` | Return type of `Backend.transcribe()` |
| `LocalBackend` | `backends/local.py` | Protocol implementation wrapping faster-whisper |
| `ApiBackend` | `backends/api.py` | Protocol implementation wrapping HTTP/OpenAI API |
| `_REGISTRY` | `backends/__init__.py` | Module-level dict of pre-instantiated backend singletons |
| `get_backend` | `backends/__init__.py` | Factory: resolves `cfg.backend` → `Backend` instance |
| `transcribe` | `backends/__init__.py` | Public thin wrapper; signature unchanged |

---

## 5. Data Schemas

All defined in Python with exact types. Language: Python 3.10+.

### 5.1 `backends/base.py` — full file contents

```python
"""Backend Protocol, Capabilities, and Transcript — the synchronous seam contract.

Import direction: base.py → models.py (never reverse).
No imports from local.py, api.py, or __init__.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import Config
from ..models import Segment, TranscriptInfo


@dataclass
class Capabilities:
    """Declarative capability record. Every Backend exposes one."""
    supports_diarization: bool
    max_upload_mb: int | None       # None = no cap (local); 24 = SI megabytes (api)
    needs_network: bool
    needs_gpu_recommended: bool
    # is_async intentionally absent — deferred to DDR-03 with AsyncBackend


@dataclass
class Transcript:
    """Typed return value of Backend.transcribe().

    Reuses existing dataclasses from models.py — no duplication.
    The public transcribe() in __init__.py unpacks this as (segments, info).
    """
    segments: list[Segment]
    info: TranscriptInfo


class Backend(Protocol):
    """Structural protocol for synchronous transcription backends.

    Implementors require no explicit inheritance — structural match suffices.
    """
    name: str
    capabilities: Capabilities

    def transcribe(self, cfg: Config, src: Path) -> Transcript: ...
```

### 5.2 `Transcript` — relationship to existing models

`Segment` and `TranscriptInfo` are defined in `models.py` and imported by `base.py`.
`Transcript` is a thin wrapper used only as the Protocol method return type.
`models.py` is NOT modified this sprint (constraint from requirements).

```
models.py           Segment, TranscriptInfo      (unchanged)
    ↑
base.py             Capabilities, Transcript, Backend Protocol
```

---

## 6. API Contracts

### 6.1 `get_backend(cfg: Config) -> Backend`

Location: `backends/__init__.py`

```python
def get_backend(cfg: Config) -> Backend:
    """Return the singleton backend for cfg.backend.

    Raises RuntimeError (not KeyError) on unknown backend name so that callers
    see a descriptive message rather than a raw key traceback.
    """
    name = cfg.backend
    if name not in _REGISTRY:
        available = list(_REGISTRY)
        raise RuntimeError(
            f"Unknown backend {name!r}. Available backends: {available}. "
            f"Set WHISPER_BACKEND to one of {available}."
        )
    return _REGISTRY[name]
```

#### Behavior change (owned)

Pre-refactor, `config.py:63` reads `backend=os.environ.get("WHISPER_BACKEND", "local").lower()`
with no validation, and `backends/__init__.py` uses an `else` catch-all (line 17) that silently
routes ANY value not equal to `"api"` — including unknown strings like `"batch"`, typos, or `""` —
to the local backend. Post-refactor, `get_backend()` raises `RuntimeError` for any key not in
`{"local", "api"}`.

This is the ONE intentional behavior change in this sprint: fail-loud over silent-wrong-backend.
It is deliberately owned here; the behavior-preservation guarantee in §15 names the single
characterization test that must be replaced rather than preserved. Do NOT revert to the old
`else` catch-all — that would perpetuate a silent-wrong-backend bug and contradict DDR-02 D2.

### 6.2 `transcribe(cfg: Config, src: Path) -> tuple[list[Segment], TranscriptInfo]`

Location: `backends/__init__.py` — PUBLIC, signature unchanged.

```python
def transcribe(cfg: Config, src: Path) -> tuple[list[Segment], TranscriptInfo]:
    """Dispatch to the configured backend. Public API — signature is stable.

    The if/else block is replaced by a registry lookup. All callers (watcher,
    CLI, smoke test) continue to unpack the result as (segments, info).
    """
    result: Transcript = get_backend(cfg).transcribe(cfg, src)
    return result.segments, result.info
```

The `Transcript` returned by `Backend.transcribe()` is immediately unpacked.
No `Transcript` object leaks into the public API surface.

### 6.3 `LocalBackend.transcribe(self, cfg: Config, src: Path) -> Transcript`

Location: `backends/local.py`

```python
class LocalBackend:
    name: str = "local"
    capabilities: Capabilities = Capabilities(
        supports_diarization=False,
        max_upload_mb=None,
        needs_network=False,
        needs_gpu_recommended=True,
    )

    def transcribe(self, cfg: Config, src: Path) -> Transcript:
        # Body is the current transcribe_local() logic, return type changed to Transcript
        ...
        return Transcript(segments=segments, info=transcript_info)
```

The module-level `_model = None` cache and `_get_model(cfg)` helper function remain
module-level (not instance state). A single `LocalBackend` instance exists in `_REGISTRY`;
the `_model` cache persists for the process lifetime regardless.

### 6.4 `ApiBackend.transcribe(self, cfg: Config, src: Path) -> Transcript`

Location: `backends/api.py`

```python
class ApiBackend:
    name: str = "api"
    capabilities: Capabilities = Capabilities(
        supports_diarization=False,
        max_upload_mb=24,       # SI megabytes (1e6 bytes); matches cfg.api_max_mb default
        needs_network=True,
        needs_gpu_recommended=False,
    )

    def transcribe(self, cfg: Config, src: Path) -> Transcript:
        # Body is the current transcribe_api() logic, return type changed to Transcript
        # import requests moved to module top (FLAG-A)
        ...
        return Transcript(segments=segments, info=info)
```

The `import requests` statement moves from inside the function to module top during this
refactor. The behavioral contract of the HTTP call is preserved exactly.

### 6.5 `_REGISTRY` — module-level dict

Location: `backends/__init__.py`

```python
from .api import ApiBackend
from .local import LocalBackend

_REGISTRY: dict[str, Backend] = {
    "local": LocalBackend(),
    "api": ApiBackend(),
}
```

- Maps string key → pre-instantiated singleton.
- Keys are the same strings `cfg.backend` holds (already lower-cased at `Config.from_env()`).
- `LocalBackend()` and `ApiBackend()` have no-op `__init__` (default); instantiation is free.
- Adding a new backend: implement `Backend` Protocol + insert one entry here. No other changes.

---

## 7. `schema_version: 1` — Exact Insertion Point

File: `src/electric_blue/outputs.py`

Current line 52:
```python
payload = {**info.to_dict(), "text": full, "segments": seg_dicts}
```

After change (one-line diff):
```python
payload = {"schema_version": 1, **info.to_dict(), "text": full, "segments": seg_dicts}
```

Properties of this change:
- `"schema_version": 1` is an integer literal — data-independent by construction.
- Positioned first in the dict literal → appears first in the JSON output (Python 3.7+ dict insertion order).
- No conditions, no branch on content — identical for every output, with or without speaker fields.
- `info.to_dict()` spreads after `schema_version`, so `schema_version` is never overwritten by info fields.
- The existing `test_json_shape` in `test_outputs.py` does not assert the complete key set, so it remains green.
- A new test function `test_json_schema_version` in `test_outputs.py` asserts `data["schema_version"] == 1`.

---

## 8. Characterization Test Strategy

### 8.1 Mock Seams

| Seam | Target (monkeypatch path) | What to patch |
|------|---------------------------|---------------|
| API HTTP call | `requests.post` | Replace with `MagicMock` returning fake response |
| API audio extract | `electric_blue.backends.api.extract` | Write `b"x" * 100` to `dst` |
| Local audio extract | `electric_blue.backends.local.extract` | Write `b"x" * 100` to `dst` |
| Local model load | `electric_blue.backends.local._get_model` | Return `FakeWhisperModel()` |

Using `monkeypatch.setattr("requests.post", mock_fn)` is correct for both pre-refactor
(lazy `import requests` inside function) and post-refactor (module-level import) because
both access the `post` attribute on the same `requests` module object.

### 8.2 Fake Response Helper

```python
from unittest.mock import MagicMock

def make_response(payload: dict) -> MagicMock:
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r
```

### 8.3 Fake Extract Helper (for gate tests — no real ffmpeg)

```python
def fake_extract(cfg, src, dst, *, compressed):
    dst.write_bytes(b"x" * 100)   # 0.0001 MB — well under any realistic cap
```

For size-limit tests: use `dataclasses.replace(cfg, api_max_mb=0)` to make the cap 0 MB,
so 100 bytes (0.0001 MB) exceeds it. `Config` is frozen; `dataclasses.replace()` works on
frozen dataclasses.

### 8.4 Fake Whisper Model Helper

```python
from dataclasses import dataclass as dc

@dc
class FakeSegmentInfo:
    language: str = "en"
    language_probability: float = 0.99
    duration: float = 3.0

class FakeSegment:
    def __init__(self, start, end, text):
        self.start = start; self.end = end; self.text = text

class FakeWhisperModel:
    def transcribe(self, audio_path, **kwargs):
        segs = [FakeSegment(0.0, 2.5, " Hello world. ")]
        return iter(segs), FakeSegmentInfo()
```

### 8.5 Test Target — Stable Across Refactor

All characterization tests call the PUBLIC `backends.transcribe(cfg, src)`.
This works before refactor (if/else dispatch → `transcribe_api`) and after refactor
(registry → `ApiBackend.transcribe()`). No test file edits needed between phases.

```python
from electric_blue.backends import transcribe
from electric_blue.config import Config
```

**Hermeticity caveat:** `Config.from_env()` reads the real `os.environ` at call time; each test MUST `dataclasses.replace` every field it asserts on and never rely on an env-derived default, so CI runs with stray `WHISPER_*` environment variables remain deterministic.

### 8.6 US-01 API Characterization Tests — `tests/test_char_api.py`

One fixture builds a base `cfg` with `backend="api"`, `api_key="sk-test"`,
`api_model="whisper-large-v3-turbo"`, `api_base_url="https://api.groq.com/openai/v1"`.
Each test patches extract and `requests.post`, then calls `transcribe(cfg, src)` and
asserts on `mock_post.call_args` and the returned tuple.

Tests to write (one test function per bullet; names are informative) — **20 total**:

1. **`test_api_post_url`** — assert URL arg is `f"{cfg.api_base_url}/audio/transcriptions"`
2. **`test_api_post_form_data`** — assert `data["model"]`, `data["response_format"]`,
   `data["timestamp_granularities[]"]`
3. **`test_api_post_auth_header`** — assert `headers["Authorization"] == "Bearer sk-test"`
4. **`test_api_post_language_when_set`** — `cfg.language = "fr"` → `data["language"] == "fr"`
5. **`test_api_post_language_absent_when_none`** — `cfg.language = None` → `"language"` not in `data`
6. **`test_api_response_segments_parsed`** — response has `segments` list → `list[Segment]`
   with matching `start`, `end`, `text.strip()`
7. **`test_api_response_fallback_single_segment`** — response has no `segments`, has `text` and
   `duration` → one `Segment(start=0.0, end=duration, text=text.strip())`
8. **`test_api_response_empty_segments_empty_text`** — both absent/empty → `[]` returned,
   no exception, `TranscriptInfo` still populated
9. **`test_api_info_language_from_response`** — response has `language` → `info.language` matches
10. **`test_api_info_language_fallback_cfg`** — response missing `language`, `cfg.language="en"` →
    `info.language == "en"`
11. **`test_api_info_language_fallback_unknown`** — response missing `language`, `cfg.language=None` →
    `info.language == "unknown"`
12. **`test_api_info_duration`** — response `duration: 42.5` → `info.duration == 42.5`
    (rounded to 2 places by current code)
13. **`test_api_info_duration_missing`** — response missing `duration` → `info.duration == 0.0`
14. **`test_api_info_backend_string`** — `info.backend == f"api:{cfg.api_model}"`
15. **`test_api_size_limit_raises`** — `dataclasses.replace(cfg, api_max_mb=0)` → `RuntimeError`
    with file size (in MB) and `"Route this one to the local/batch folder"` in message
16. **`test_api_missing_key_raises`** — `cfg.api_key = ""` (use `dataclasses.replace`) →
    `RuntimeError` with `"WHISPER_API_KEY is not set"` in message
17. **`test_api_info_language_probability_none`** — any successful API response →
    `info.language_probability is None`; pins FLAG-C: the API path never returns a confidence
    score, so `language_probability` stays `None` (JSON `null`)
18. **`test_api_size_limit_si_boundary`** — custom extract stub writes exactly 1,048,576 bytes
    (1 MiB) with `dataclasses.replace(cfg, api_max_mb=1)` → `RuntimeError`; `1_048_576 / 1e6 =
    1.048576 > 1.0` (SI); would NOT raise if `/1e6` changed to `/(1024*1024)`; pins FLAG-B
19. **`test_api_post_files_and_timeout`** — via `mock_post.call_args.kwargs`: assert
    `files["file"][0] == "a.mp3"` (filename tuple element), `files["file"][2] == "audio/mpeg"`
    (MIME type tuple element), and `timeout == 600`; pins the verbatim POST shape that the
    refactor must copy exactly (api.py:35–41)
20. **`test_api_raise_for_status_called`** — assert
    `mock_post.return_value.raise_for_status.assert_called_once()`; confirms that HTTP errors
    surface rather than being swallowed (api.py:42)

Note on test 15: the error message template is `f"{src.name}: encoded audio is {size_mb:.0f} MB
(> {cfg.api_max_mb} MB cap). Route this one to the local/batch folder, or chunk it."` —
pin this exact phrase `"Route this one to the local/batch folder"`.

Note on test 16: the `api_key` check fires before `extract()` is even called, so the extract
mock is not needed for this test.

### 8.7 US-02 Local Dispatch Characterization Tests — `tests/test_char_local.py`

**Happy-path test (survives refactor unchanged):**

```python
def test_local_dispatch_returns_segments_and_info(monkeypatch, tmp_path):
    monkeypatch.setattr("electric_blue.backends.local.extract", fake_extract)
    monkeypatch.setattr("electric_blue.backends.local._get_model", lambda cfg: FakeWhisperModel())
    # ...
    cfg = dataclasses.replace(Config.from_env(), backend="local")
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    segments, info = transcribe(cfg, src)

    assert isinstance(segments, list)
    assert all(isinstance(s, Segment) for s in segments)
    assert isinstance(info, TranscriptInfo)
    assert info.backend.startswith("local:")
```

The test passes pre-refactor (calls `transcribe_local()` via if/else) and post-refactor
(calls `LocalBackend.transcribe()` via registry). The mock seam is identical in both cases.

**Unknown-backend characterization test (slice S1 — PRE-REFACTOR ONLY):**

```python
def test_dispatch_unknown_backend_routes_local(monkeypatch, tmp_path):
    """PRE-REFACTOR ONLY (slice S1) — pins current silent-local-fallback behavior.

    This test is EXPECTED to break in slice S3 (post-refactor):
    get_backend() will raise RuntimeError for "bogus". It is superseded by
    test_get_backend_unknown_raises in tests/test_backends_registry.py,
    which encodes the ONE deliberately-replaced behavior.
    """
    monkeypatch.setattr("electric_blue.backends.local.extract", fake_extract)
    monkeypatch.setattr("electric_blue.backends.local._get_model", lambda cfg: FakeWhisperModel())

    cfg = dataclasses.replace(Config.from_env(), backend="bogus")
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    segments, info = transcribe(cfg, src)  # must NOT raise pre-refactor

    assert isinstance(segments, list)
    assert isinstance(info, TranscriptInfo)
    assert info.backend.startswith("local:")   # silently routed to local via else catch-all
```

This test pins the CURRENT behavior (the `else` catch-all in `__init__.py` line 17 silently
routes any non-`"api"` value to local). When the registry refactor lands in slice S3, this
test breaks — that break is expected and deliberate. It is then removed and replaced by
`test_get_backend_unknown_raises` in `tests/test_backends_registry.py`, which asserts the
new `RuntimeError` and verifies its message content.

### 8.8 US-07 `schema_version` Test — addition to `tests/test_outputs.py`

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

This is a gate test (no `@pytest.mark.smoke`). It tests `write_outputs()` directly,
the same approach as existing `test_json_shape`.

---

## 9. Import Graph

```
pathlib, typing, dataclasses     (stdlib)
     │
     ▼
models.py           Segment, TranscriptInfo          ← no package imports
config.py           Config                           ← no package imports
audio.py            extract()                        ← config.py
     │                    │
     ▼                    │
backends/base.py    Backend, Capabilities, Transcript
   ├── imports: models.py, config.py
   └── (no imports from local.py, api.py, __init__.py)
     │
     ├──► backends/local.py   LocalBackend
     │      imports: audio.py, config.py, models.py, backends/base.py
     │
     └──► backends/api.py    ApiBackend
            imports: audio.py, config.py, models.py, backends/base.py, requests
     │
     ▼
backends/__init__.py   _REGISTRY, get_backend(), transcribe()
   imports: backends/base.py, backends/local.py, backends/api.py, config.py, models.py
     │
     ▼
watcher.py, cli.py, outputs.py   (unchanged importers)
```

No circular imports. The DAG is: stdlib → models/config → audio → base → local/api → __init__.

---

## 10. File-by-File Change Map

| File | Action | What Changes |
|------|--------|-------------|
| `src/electric_blue/backends/base.py` | **CREATE** | `Backend` Protocol, `Capabilities` dataclass, `Transcript` dataclass |
| `src/electric_blue/backends/__init__.py` | **MODIFY** | Remove if/else; add `_REGISTRY`, `get_backend()`, thin wrapper |
| `src/electric_blue/backends/local.py` | **MODIFY** | Add `LocalBackend` class; remove standalone `transcribe_local()` |
| `src/electric_blue/backends/api.py` | **MODIFY** | Add `ApiBackend` class; move `import requests` to top; remove standalone `transcribe_api()` |
| `src/electric_blue/outputs.py` | **MODIFY** | Add `"schema_version": 1` to JSON payload dict (one-line change) |
| `tests/test_char_api.py` | **CREATE** | US-01 — 20 API characterization tests (mocked HTTP + extract) |
| `tests/test_char_local.py` | **CREATE** | US-02 — local dispatch characterization tests (mocked model + extract); includes `test_dispatch_unknown_backend_routes_local` (S1 only, expected to break in S3) |
| `tests/test_backends_registry.py` | **CREATE** | Registry tests including `test_get_backend_unknown_raises` (asserts RuntimeError + message content on unknown backend); supersedes `test_dispatch_unknown_backend_routes_local` at S3 |
| `tests/test_outputs.py` | **MODIFY** | Add `test_json_schema_version()` function |

Files NOT changed: `models.py`, `config.py`, `audio.py`, `watcher.py`, `cli.py`, `notify.py`,
`__init__.py` (package root), `conftest.py`, `test_config.py`, `test_watcher.py`,
`test_smoke.py`, `pyproject.toml`, `Makefile`.

---

## 11. Sprint Sequencing (within codebase)

Per DDR-02 §Sequencing — this is the required commit order:

1. **Char tests first** — `tests/test_char_api.py` + `tests/test_char_local.py` pass green
   against current code (including `test_dispatch_unknown_backend_routes_local` which asserts
   the silent-local-fallback). Commit.
2. **`base.py` + registry** — introduce `backends/base.py`, add `_REGISTRY` and `get_backend()`
   to `backends/__init__.py`, keep standalone `transcribe_api()` / `transcribe_local()`
   alive temporarily. Commit.
3. **Refactor `local.py` / `api.py`** — introduce `LocalBackend` / `ApiBackend`, remove
   standalone functions, `transcribe()` wrapper calls through registry. At this point
   `test_dispatch_unknown_backend_routes_local` breaks (expected); remove it and commit
   `tests/test_backends_registry.py` with `test_get_backend_unknown_raises` in the same
   commit. All other char tests must remain green. Commit.
4. **`schema_version: 1`** — one-line change in `outputs.py`, new `test_json_schema_version`.
   Commit.
5. **`make gate`** — black + ruff + pytest -m "not smoke" all green.
6. **`make smoke`** — pytest -m smoke green (real tiny model, real ffmpeg).

---

## 12. Patterns

| Pattern | Usage | Rationale |
|---------|-------|-----------|
| `typing.Protocol` | `Backend` structural contract | D1 — structural, no inheritance, Pythonic; easier to satisfy with classes that already exist |
| Module-level singleton dict | `_REGISTRY` | D2 — simple, no dependency injection framework, inspectable; adding a backend is one dict entry |
| Pre-instantiated registry values | `{"local": LocalBackend(), ...}` | No-op constructors; avoids re-instantiation per call; `_model` cache remains module-level |
| `dataclasses.replace()` in tests | Derive Config variants | `Config` is frozen; `replace()` is the idiomatic way to create variants for edge-case tests |
| Public wrapper unpacks Protocol result | `transcribe()` returns tuple | All callers use tuple unpacking; Transcript never leaks into the public surface |
| First-key `schema_version` | JSON output | Integer literal at dict construction time — data-independence is structurally enforced, not documented |

### Anti-Patterns (not used)

- `abc.ABC` / `abstractmethod` — requires explicit inheritance; Protocol is sufficient (D1)
- Entry-points plugin registration — future DDR; internal dict is the right scope now (D2)
- `AsyncBackend` / submit-poll lifecycle — deferred to DDR-03 (D3)
- `is_async` capability flag — deferred to DDR-03 alongside `AsyncBackend` (D5)
- Instance-level `_model` cache on `LocalBackend` — module-level cache already exists and
  works; moving it to the instance would break behavior if `_get_model` is mocked at module scope

---

## 13. Dependencies

No new runtime dependencies. `requests` is already in `pyproject.toml` dependencies.
`typing.Protocol` is in the standard library (Python 3.8+; project requires 3.10+).
`dataclasses` is standard library.

All new test code uses only `unittest.mock.MagicMock` (stdlib) and `pytest` (already in dev deps).

---

## 14. Integration Points

| Existing Component | How It Integrates Post-Refactor |
|--------------------|---------------------------------|
| `watcher.py` — `process()` | Calls `backends.transcribe(cfg, src)` — unchanged import and call site |
| `test_smoke.py` | Calls `backends.transcribe(cfg, clip)` — unchanged; exercises `LocalBackend` end-to-end |
| `conftest.py` — `fake_transcribe` | Patches `electric_blue.watcher.transcribe` — unchanged patch target |
| `test_watcher.py` — `handle` tests | Patches same `electric_blue.watcher.transcribe` — unchanged |
| `outputs.py` — `write_outputs()` | `segments` and `info` are passed from the unpacked tuple — unchanged signature |
| `cli.py` | Calls through `watcher.process()` — unchanged |

---

## 15. Behavior Preservation Guarantee

The property proven by the sequencing constraint:

> All US-01 and US-02 characterization tests are written and passing against the CURRENT
> (pre-refactor) code before any refactoring commits are made.
>
> The refactored code passes the same characterization tests unchanged, with ONE named
> exception: `test_dispatch_unknown_backend_routes_local` (in `tests/test_char_local.py`)
> is the single test that does NOT survive the refactor unedited. It pins the current
> silent-local-fallback behavior (pre-refactor `else` catch-all), which is the one
> intentional behavior change this sprint deliberately replaces. At slice S3, this test
> is removed and superseded by `test_get_backend_unknown_raises` in
> `tests/test_backends_registry.py`, which asserts the new `RuntimeError` and its message
> content. Every other characterization test — the 20 API tests in `test_char_api.py` and
> the local happy-path test `test_local_dispatch_returns_segments_and_info` — survives
> the refactor unchanged.
>
> Therefore, the refactored code exhibits the same observable behavior as the original code
> on every input the characterization tests cover, except for the single owned behavior
> change: unknown `cfg.backend` values now raise `RuntimeError` instead of silently routing
> to the local backend.

The tests call through the stable `backends.transcribe(cfg, src)` public entry point,
which means no test needs to be updated between Phase 1 (pre-refactor) and Phase 3 (post-refactor)
except for the one deliberately-replaced test named above.
