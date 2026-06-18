# Implementation Roadmap: whisperx-diarization (DDR-05)

- **Status:** PLANNING
- **Author:** reed (planner)
- **Date:** 2026-06-18
- **Requirements:** `docs/specs/whisperx-diarization/01-REQUIREMENTS.md`
- **Architecture:** `docs/specs/whisperx-diarization/02-ARCHITECTURE.md`
- **DDR:** `docs/specs/electric-blue-ddrs/DDR-05-whisperx-diarization.md`

All locked DDR-05 decisions (D1–D7) are carried into this plan without re-litigation.

---

## Overview

Ten slices, no circular dependencies. Char-test-first ordering enforced for every
modified existing source file. Each slice leaves the gate green.

```
S1 → S2 → S3 → S5 → S6 → S7 → S8 → S9
          ↑               ↑    ↓
S4 ───────┘               │   S10
S4 ────────────────────────┘
```

Readable as:
- S1 (exceptions.py) unblocks S2, S4, and S6
- S2 (char tests) must be green before S3 (models.py change)
- S3 unblocks S5 and S6
- S4 (config) unblocks S6
- S6 (backend) unblocks S7 and S9
- S7 (registry) unblocks S10
- S8 (pyproject + Makefile) unblocks S9

---

## Dependency Map

| Slice | Depends On |
|-------|------------|
| S1 — `exceptions.py` | — |
| S2 — Characterization tests (baseline) | S1 |
| S3 — `Segment.speaker` in `models.py` | S2 (char tests must be green pre-change) |
| S4 — Diarize fields in `config.py` | S1 |
| S5 — Speaker rendering in `outputs.py` | S3 |
| S6 — `backends/diarize.py` | S1, S3, S4 |
| S7 — Registry entry in `backends/__init__.py` | S6 |
| S8 — `pyproject.toml` extra + marker + Makefile gate filter | — (sequenced after S7 for clarity) |
| S9 — `tests/test_smoke_diarize.py` | S6, S8 |
| S10 — README documentation | S7 (backend name `"diarize"` confirmed) |

---

## Slice Overview

| Slice | Goal | Depends On | New Files | Modified Files |
|-------|------|------------|-----------|----------------|
| S1 | `ConfigurationError` exception class | — | `exceptions.py`, `test_diarize_pipeline.py` (skeleton) | — |
| S2 | Char tests pin baseline behavior | S1 | — | `test_diarize_pipeline.py` |
| S3 | `Segment.speaker` field + `to_dict()` | S2 | — | `models.py`, `test_diarize_pipeline.py` |
| S4 | `hf_token` + `diarize_num_speakers` in Config | S1 | — | `config.py`, `test_diarize_pipeline.py` |
| S5 | SRT/VTT speaker prefix rendering | S3 | — | `outputs.py`, `test_diarize_pipeline.py` |
| S6 | `WhisperXBackend` four-stage pipeline | S1, S3, S4 | `backends/diarize.py` | `test_diarize_pipeline.py` |
| S7 | `"diarize"` factory entry + watcher startup validation | S6 | — | `backends/__init__.py`, `watcher.py`, `test_diarize_pipeline.py` |
| S8 | `[diarize]` extra, marker, gate filter | — | — | `pyproject.toml`, `Makefile` |
| S9 | Diarize smoke test | S6, S8 | `tests/test_smoke_diarize.py` | — |
| S10 | README documentation for diarize backend | S7 | — | `README.md` |

---

## Slice Details

### S1 — `exceptions.py` (new exception class)

**Goal:** Create the `ConfigurationError` exception used by both `config.py` and
`backends/diarize.py`. Establishes the import-safe foundation before any source files
that depend on it are modified.

**Depends On:** —

**Agent Lane:** code-executor creates `exceptions.py`; test-writer creates skeleton
`test_diarize_pipeline.py` with import test. Orchestrator runs `make gate`.

**Files:**
- `src/electric_blue/exceptions.py` — create
- `tests/test_diarize_pipeline.py` — create (skeleton with one test)

**Implementation Notes:**
- Class body: `class ConfigurationError(Exception)`. Docstring must state it is raised
  by `Config.from_env()` (invalid env vars) and `WhisperXBackend.__init__()`
  (missing HF_TOKEN); not caught inside electric_blue; propagates to `watcher.handle()`.
- No imports from any other electric_blue module (keeps the import-graph acyclic:
  `exceptions.py` sits at the root, imported by both `config.py` and `backends/diarize.py`
  without creating cycles).
- `test_diarize_pipeline.py` skeleton: module docstring + one test only; no unresolved
  imports from modules not yet created.

**Tests (added this slice):**
- `test_configuration_error_importable` — `from electric_blue.exceptions import ConfigurationError`
  succeeds; `issubclass(ConfigurationError, Exception)` is True.

**Done When:**
- `src/electric_blue/exceptions.py` exists and is importable.
- `ConfigurationError` is a subclass of `Exception`.
- `tests/test_diarize_pipeline.py` exists with at least one passing test.
- `make gate` green.

---

### S2 — Characterization tests (baseline behavior lock)

**Goal:** Pin the current observable behavior of `Segment.to_dict()` and
`write_outputs()` (SRT/VTT/TXT) for segments without speaker labels. These tests must
be green against the **pre-change** code and must remain green at every subsequent slice
boundary. This is the char-test-first gate for S3 and S5.

**Depends On:** S1

**Agent Lane:** test-writer adds to `test_diarize_pipeline.py`. Orchestrator verifies
tests are green against current (unmodified) `models.py` and `outputs.py`.

**Files:**
- `tests/test_diarize_pipeline.py` — add char-tests section

**Implementation Notes:**
- All tests in this slice use `Segment(start, end, text)` — the current three-arg
  constructor. After S3 adds `speaker=None` default, this constructor form still works.
- The SRT/VTT char tests should use `write_outputs()` with standard no-speaker segments
  and assert the absence of `[SPEAKER_` in the output. This will remain true after S5
  because `s.speaker is None` → cue text unchanged.
- Do NOT import anything from modules not yet created (`backends/diarize.py` does not
  exist yet — no import of it here).

**Tests (added this slice):**
- `test_char_segment_to_dict_no_speaker_field` — `Segment(0.0, 1.0, "hello").to_dict()`
  equals `{"start": 0.0, "end": 1.0, "text": "hello"}` with no `"speaker"` key. Pins
  the pre-S3 `to_dict()` output shape.
- `test_char_srt_no_speaker_prefix` — `write_outputs()` with two no-speaker segments;
  SRT output contains no `"[SPEAKER_"` substring.
- `test_char_vtt_no_speaker_prefix` — same assertion for VTT output.
- `test_char_txt_no_speaker_prefix` — TXT output contains no `"[SPEAKER_"` substring.

**Done When:**
- All four char tests pass against the unmodified codebase.
- `make gate` green.

---

### S3 — `Segment.speaker` field in `models.py`

**Goal:** Add `speaker: str | None = None` to the `Segment` dataclass and update
`to_dict()` to omit the `"speaker"` key when `None`. Additive change — existing
callers unaffected.

**Depends On:** S2 (char tests must be green pre-change)

**Agent Lane:** code-executor modifies `models.py`; test-writer adds tests to
`test_diarize_pipeline.py`. Orchestrator runs `make gate`.

**Files:**
- `src/electric_blue/models.py` — modify
- `tests/test_diarize_pipeline.py` — add segment tests

**Implementation Notes:**
- `speaker: str | None = None` is a keyword-with-default field. In a dataclass,
  fields with defaults must follow fields without defaults. `start`, `end`, `text` have
  no defaults; `speaker` has `None`. Order: `start`, `end`, `text`, `speaker`. This is
  consistent with all existing `Segment(start, end, text)` construction sites.
- `to_dict()`: build `d = {"start": ..., "end": ..., "text": ...}` first, then
  `if self.speaker is not None: d["speaker"] = self.speaker`. Never emit `"speaker": null`.
- Verify: no existing `Segment` construction uses positional args in a way that would
  break (the new field is at position 4; no existing caller passes 4 positional args).
- `schema_version` stays `1` — this change is additive; no bump (INV-10).

**Tests (added this slice):**
- `test_segment_to_dict_omits_speaker_when_none` — `Segment(0.0, 1.0, "x").to_dict()`
  has no `"speaker"` key. (The char test from S2 already covers this form; this test
  is explicitly typed post-change using `speaker=None` kwarg form as well.)
- `test_segment_to_dict_includes_speaker_when_set` — `Segment(0.0, 1.0, "x",
  speaker="SPEAKER_00").to_dict()["speaker"] == "SPEAKER_00"`.

**Done When:**
- All S2 char tests still pass.
- `Segment(0, 1, "x").to_dict()` returns no `"speaker"` key.
- `Segment(0, 1, "x", speaker="SPEAKER_00").to_dict()["speaker"] == "SPEAKER_00"`.
- `make gate` green.

---

### S4 — Diarize fields in `config.py`

**Goal:** Add `hf_token` and `diarize_num_speakers` to `Config`; add
`_parse_diarize_num_speakers()` validation helper; import `ConfigurationError` from
`exceptions.py`. These changes are additive to `Config.from_env()` — existing tests
pass unchanged.

**Depends On:** S1 (`ConfigurationError` must exist to import)

**Agent Lane:** code-executor modifies `config.py`; test-writer adds config tests to
`test_diarize_pipeline.py`. Orchestrator runs `make gate`.

**Files:**
- `src/electric_blue/config.py` — modify
- `tests/test_diarize_pipeline.py` — add config tests

**Implementation Notes:**
- Add `from .exceptions import ConfigurationError` to the import block in `config.py`.
- Add to `Config` dataclass after the `# Batch fields` group, a new `# Diarize backend`
  group with two fields: `hf_token: str` and `diarize_num_speakers: int | None`. These
  have no default values in the dataclass definition itself — their defaults live in
  `from_env()` (`""` and `None` respectively).
- `Config` is a frozen dataclass. Adding fields at the END is safe because no code
  constructs `Config(...)` positionally with the full field list — all construction goes
  through `from_env()`.
- `_parse_diarize_num_speakers(raw: str | None) -> int | None`: module-level function
  (not a method). Returns `None` for `None` input; raises `ConfigurationError` for
  non-integer string; raises `ConfigurationError` for `val <= 0`.
- `from_env()` gains `hf_token=os.environ.get("HF_TOKEN", "")` and
  `diarize_num_speakers=_parse_diarize_num_speakers(os.environ.get("WHISPER_DIARIZE_NUM_SPEAKERS"))`.
- Update `backend: str` field comment to list `"diarize"` as a valid value alongside
  `"local"` and `"api"`.
- `hf_token` must never appear in any log call. INV-7 applies. The error message
  raised by `ConfigurationError` when the token is missing must not contain the token
  value (it directs the operator to the HuggingFace setup docs instead).

**Tests (added this slice):**
- `test_config_hf_token_default_empty` — `Config.from_env()` with `HF_TOKEN` unset
  returns `cfg.hf_token == ""`.
- `test_config_diarize_num_speakers_default_none` — with `WHISPER_DIARIZE_NUM_SPEAKERS`
  unset, `cfg.diarize_num_speakers is None`.
- `test_config_num_speakers_valid` — `WHISPER_DIARIZE_NUM_SPEAKERS=2` →
  `cfg.diarize_num_speakers == 2` and `isinstance(cfg.diarize_num_speakers, int)`.
- `test_config_invalid_num_speakers_zero` — `WHISPER_DIARIZE_NUM_SPEAKERS=0` →
  `ConfigurationError` from `Config.from_env()`.
- `test_config_invalid_num_speakers_negative` — `WHISPER_DIARIZE_NUM_SPEAKERS=-1` →
  `ConfigurationError`.
- `test_config_invalid_num_speakers_string` — `WHISPER_DIARIZE_NUM_SPEAKERS=two` →
  `ConfigurationError`.
- `test_config_hf_token_not_logged` — `monkeypatch.setenv("HF_TOKEN", "hf-secret-xyz")`
  + `caplog.at_level(logging.DEBUG)`; `Config.from_env()`; assert `"hf-secret-xyz"` not
  in `caplog.text` (INV-7).

**Done When:**
- All existing `tests/test_config.py` tests pass.
- New config tests pass.
- `ConfigurationError` raised for zero, negative, and non-integer `num_speakers`.
- `hf_token` default is empty string.
- `make gate` green.

---

### S5 — Speaker prefix rendering in `outputs.py`

**Goal:** Add `[SPEAKER_NN]` prefix to SRT and VTT cue text when `segment.speaker is
not None`. TXT and JSON are unchanged. The change is purely data-driven — no branch on
backend name (INV-11).

**Depends On:** S3 (`Segment.speaker` field exists)

**Agent Lane:** code-executor modifies `outputs.py`; test-writer adds output rendering
tests to `test_diarize_pipeline.py`. Orchestrator runs `make gate`.

**Files:**
- `src/electric_blue/outputs.py` — modify
- `tests/test_diarize_pipeline.py` — add output rendering tests

**Implementation Notes:**
- In the SRT writer, replace the bare `s.text` in the cue line with:
  `cue_text = f"[{s.speaker}] {s.text}" if s.speaker is not None else s.text`
  then use `cue_text` in the `lines` append.
- In the VTT writer, same substitution.
- TXT writer: unchanged. Continues to use `" ".join(s.text for s in segments)`.
- JSON writer: unchanged. Speaker appears via `s.to_dict()` (S3 handles this).
- `write_outputs` signature is UNCHANGED. No new parameter, no backend-name branch.
- When all segments have `speaker=None`, all four output formats must be byte-for-byte
  identical to the pre-S5 output. The S2 char tests verify this.

**Tests (added this slice):**
- `test_srt_speaker_prefix` — SRT cue text for `speaker="SPEAKER_00"` starts with
  `"[SPEAKER_00]"`.
- `test_vtt_speaker_prefix` — VTT cue text for `speaker="SPEAKER_01"` starts with
  `"[SPEAKER_01]"`.
- `test_txt_no_speaker_prefix` — TXT output for diarized segments contains no
  `"[SPEAKER_"` substring.
- `test_json_speaker_field_present` — JSON segment dict has `"speaker"` key when
  diarized; value matches expected label.
- `test_json_schema_version_still_1` — `data["schema_version"] == 1` for diarized output.
- `test_no_speaker_output_identical` — All-`None` speaker list produces byte-for-byte
  identical SRT, VTT, TXT, JSON to a baseline run (the S2 char tests already cover this
  implicitly; this test makes it explicit with a direct comparison).

**Done When:**
- All S2 char tests still pass.
- All existing `tests/test_outputs.py` tests still pass.
- Speaker-prefixed SRT/VTT tests pass.
- TXT has no `[SPEAKER_` for any input.
- `schema_version` is `1` for diarized output.
- `make gate` green.

---

### S6 — `backends/diarize.py` (`WhisperXBackend`)

**Goal:** Implement the four-stage whisperX pipeline as `WhisperXBackend` with lazy
imports, the `_get_whisperx()` cache seam, `_resolve_device()`, and
`_assign_majority_speaker()`. All hermetic tests use `sys.modules` mock; zero real
whisperX import required in the gate.

**Depends On:** S1 (`ConfigurationError`), S3 (`Segment.speaker`), S4 (`Config.hf_token`,
`Config.diarize_num_speakers`)

**Agent Lane:** code-executor creates `backends/diarize.py`; test-writer adds pipeline
tests (fixture + test cases) to `test_diarize_pipeline.py`. Orchestrator runs `make gate`.

**Files:**
- `src/electric_blue/backends/diarize.py` — create
- `tests/test_diarize_pipeline.py` — add `fake_whisperx` fixture + 10 pipeline tests

**Implementation Notes:**

Module-level cache: `_whisperx = None` (package-private global). `_get_whisperx()`
returns `_whisperx` if already set, otherwise `import whisperx; _whisperx = whisperx;
return _whisperx`. The gate mock patches both `sys.modules["whisperx"]` and the
`_whisperx` global so the lazy import picks up the fake on the next call.

`_resolve_device(cfg)`: mirrors `local.py` logic — if `cfg.device == "auto"`, probe
`torch.cuda.is_available()` (catching `ImportError` for CPU-only installs) and fall
back to `"cpu"`. If `cfg.device` is already a concrete string (`"cpu"`, `"cuda"`), return
it directly. No warning emitted for CPU (D5).

`_resolve_compute(cfg: Config) -> str`: returns `cfg.compute_type` if it is not `"auto"`,
otherwise `"int8"`. Module-level helper used in Stage 1.

`_assign_majority_speaker(segment_dict)` strategy (document in code):
1. If segment dict has top-level `"speaker"` key, return it directly.
2. Otherwise, sum elapsed duration per speaker across the `"words"` list
   (`word["end"] - word["start"]` per speaker label in `word["speaker"]`).
3. Return the speaker with greatest accumulated duration.
4. Tie-break: alphabetically first speaker label (deterministic; documented).
5. If no words carry speaker data and no segment-level key, return `None`.

`WhisperXBackend.__init__(self, cfg: Config)`: validates `cfg.hf_token`; raises
`ConfigurationError` if empty. Called lazily by `get_backend(cfg)` when
`cfg.backend == "diarize"` — NOT at module import.

`transcribe()` execution ordering:
1. `_resolve_device(cfg)`.
2. `audio.extract(...)` into temp dir.
3. `wx = _get_whisperx()`.
4. Stages 1–4 per architecture spec (whisperX API calls).
5. Build `Segment` list via `_assign_majority_speaker`.
6. Build `TranscriptInfo` with `backend=f"diarize:{cfg.model_size}"`.
7. Return `Transcript(segments=segments, info=info)`.

`WhisperXBackend` is NOT registered in `_REGISTRY` or `_FACTORIES` in this slice — that
happens in S7. The class is standalone and can be imported and tested directly.

`fake_whisperx` fixture design (in `test_diarize_pipeline.py`):
```python
@pytest.fixture()
def fake_whisperx(monkeypatch):
    import sys, types
    wx = types.SimpleNamespace(
        load_audio=lambda path: b"",
        load_model=lambda *a, **kw: FakeModel(),
        load_align_model=lambda **kw: (FakeAlignModel(), {}),
        align=lambda segs, model, meta, audio, device: {"segments": segs, "language": "en"},
        assign_word_speakers=fake_assign_word_speakers,
    )
    wx_diarize = types.SimpleNamespace(
        DiarizationPipeline=FakeDiarizationPipeline,
        assign_word_speakers=fake_assign_word_speakers,
    )
    monkeypatch.setitem(sys.modules, "whisperx", wx)
    monkeypatch.setitem(sys.modules, "whisperx.diarize", wx_diarize)
    monkeypatch.setattr("electric_blue.backends.diarize._whisperx", None)
    return wx
```

`FakeDiarizationPipeline`: a class whose `__call__` returns a synthetic annotation
representing SPEAKER_00 for 0.0–2.5 s, SPEAKER_01 for 2.5–5.0 s. Must record kwargs
so tests can assert `num_speakers` was passed or not.

`FakeModel`: has `.transcribe()` returning
`{"segments": [{"start": 0.0, "end": 2.5, "text": "hello", "words": []},
               {"start": 2.5, "end": 5.0, "text": "goodbye", "words": []}],
  "language": "en"}`.

`fake_assign_word_speakers(diarize_segs, result)`: returns the result dict with
`"speaker"` key injected on each segment based on time overlap with the fake annotation.

**Tests (added this slice):**
- `test_backend_name` — `WhisperXBackend.name == "diarize"`.
- `test_backend_supports_diarization` — `WhisperXBackend.capabilities.supports_diarization is True`.
- `test_missing_hf_token_raises` — `cfg.hf_token = ""` → `ConfigurationError` raised by
  `WhisperXBackend(cfg)` instantiation. Use `monkeypatch` to set `HF_TOKEN=""` and
  verify the error message references the pyannote model ToS URL.
- `test_speaker_assignment_basic` — with `fake_whisperx`, both segments get speaker labels
  matching the fake annotation time ranges.
- `test_majority_speaker_wins` — `_assign_majority_speaker` with a segment where
  SPEAKER_00 has 2.5 s of words and SPEAKER_01 has 1.0 s → returns `"SPEAKER_00"`.
- `test_tie_break_alphabetical` — `_assign_majority_speaker` with exactly equal durations
  for SPEAKER_00 and SPEAKER_01 → returns `"SPEAKER_00"` (alphabetically first).
- `test_transcript_info_backend_format` — `info.backend == f"diarize:{cfg.model_size}"`.
- `test_num_speakers_passed_to_pipeline` — `cfg.diarize_num_speakers=2` →
  `FakeDiarizationPipeline.__call__` receives `num_speakers=2`.
- `test_num_speakers_absent_in_auto_mode` — `cfg.diarize_num_speakers=None` →
  `FakeDiarizationPipeline.__call__` called without `num_speakers` kwarg.
- `test_no_whisperx_import_before_hf_guard` — verifies `ConfigurationError` from missing
  token is raised by `WhisperXBackend(cfg)` without calling `_get_whisperx()` (i.e.,
  `"whisperx"` is NOT in `sys.modules` after the guard fires).

**Done When:**
- `WhisperXBackend` exists in `backends/diarize.py`.
- All 10 pipeline tests pass with `fake_whisperx` (zero real whisperX import).
- `ConfigurationError` raised before any import when `hf_token=""`.
- Majority-speaker and tie-break logic verified.
- Existing tests for `local`, `api`, and `groq-batch` backends pass unchanged.
- `make gate` green.

---

### S7 — Register `"diarize"` in `backends/__init__.py` + watcher startup validation

**Goal:** Add `_FACTORIES: dict[str, type] = {"diarize": WhisperXBackend}` alongside
`_REGISTRY`. Extend `get_backend()` to check `_FACTORIES` after `_REGISTRY` and construct
the backend on demand with `cfg`. `WhisperXBackend` is never pre-instantiated, so
`import electric_blue.backends` is safe when `HF_TOKEN` is absent (INV-8). Completes
INV-11 compliance for the diarize backend. Also adds one line to `run_watch()` in
`watcher.py` to validate backend config at service startup (fail-fast before the watch
loop begins, not at first-file-drop).

**Depends On:** S6

**Agent Lane:** code-executor modifies `backends/__init__.py` and `watcher.py`;
test-writer adds registry and startup tests to `test_diarize_pipeline.py`.
Orchestrator runs `make gate`.

**Files:**
- `src/electric_blue/backends/__init__.py` — modify
- `src/electric_blue/watcher.py` — modify
- `tests/test_diarize_pipeline.py` — add registry and startup tests

**Implementation Notes:**
- Add `from .diarize import WhisperXBackend` to the import block.
- Add `_FACTORIES: dict[str, type] = {"diarize": WhisperXBackend}` as a module-level dict
  alongside (not inside) `_REGISTRY`. Do NOT add `"diarize": WhisperXBackend()` to
  `_REGISTRY` — eager instantiation would require a `cfg` arg not available at module
  scope and reintroduces the INV-8 defect (import-time HF_TOKEN check breaks `make gate`).
- Extend `get_backend()`: after the `_REGISTRY` lookup, add a check for `_FACTORIES`:
  ```python
  if name in _FACTORIES:
      return _FACTORIES[name](cfg)
  ```
  The existing `RuntimeError` for unknown backends must still fire for names in neither
  `_REGISTRY` nor `_FACTORIES`. Update the `available` list and error path accordingly.
- The existing `test_get_backend_unknown_raises` asserts `"local" in msg or "api" in msg`
  — this remains true; no change to that test required.
- No `if/else` branching on backend name — dispatch via `_REGISTRY` and `_FACTORIES` only
  (INV-11).
- **Watcher startup validation:** In `watcher.py`, extend the existing import on the
  `from .backends import transcribe` line to `from .backends import get_backend, transcribe`.
  Then add one line to `run_watch()` as the FIRST statement in the function body, before
  `run_once(cfg)` and before the observer is created:
  ```python
  get_backend(cfg)  # validate backend config at startup; raises ConfigurationError early
  ```
  Exact placement: as the first line of `run_watch()`, before `run_once(cfg)`. This
  ensures validation fires before any backlog files are processed. Placing it after
  `run_once()` (e.g. before `obs.start()`) would allow the pre-existing file backlog to
  drain first — which means ConfigurationError fires mid-backlog, not before any work.
  Without this line, a misconfigured backend (e.g. `backend="diarize"` with no `HF_TOKEN`)
  raises `ConfigurationError` only at the first file drop, not at service startup.

**Tests (added this slice):**
- `test_registry_contains_diarize` — import `_FACTORIES` and `_REGISTRY` from
  `electric_blue.backends`; assert `"diarize" in _FACTORIES`; assert
  `"diarize" not in _REGISTRY`.
- `test_get_backend_returns_whisperx_backend` — use a `cfg` fixture with
  `backend="diarize"` and a non-empty `hf_token` (e.g. `"hf-test-token"`);
  `get_backend(cfg)` returns a `WhisperXBackend` instance. (Constructing
  `WhisperXBackend(cfg)` validates `hf_token`, so the fixture must supply a non-empty
  value.)
- `test_run_watch_validates_backend_at_startup` — monkeypatch `Observer` to a no-op
  (so the watch loop never starts); `monkeypatch.delenv("HF_TOKEN", raising=False)`;
  build a `cfg` with `backend="diarize"`; call `run_watch(cfg)` and assert
  `ConfigurationError` is raised before any files are processed. This confirms the
  startup validation line fires immediately, not deferred to first-file-drop.

**Done When:**
- `"diarize" in _FACTORIES`.
- `"diarize" not in _REGISTRY`.
- `get_backend(cfg_diarize)` returns a `WhisperXBackend` instance.
- `import electric_blue.backends` does not raise when `HF_TOKEN` is unset.
- `test_get_backend_unknown_raises` still passes (RuntimeError for names in neither dict).
- No `if cfg.backend == "diarize"` in any source file.
- `run_watch()` raises `ConfigurationError` immediately when `cfg.backend == "diarize"`
  and `HF_TOKEN` is absent (startup validation, before the watch loop starts).
- `make gate` green.

---

### S8 — `pyproject.toml` extras + marker + Makefile gate filter

**Goal:** Declare the `[diarize]` optional-dependency (`whisperx>=3.8.6,<4.0` only;
torch/pyannote transitive), register the `diarize_smoke` pytest marker, and update
`make gate` to explicitly exclude `diarize_smoke`-marked tests. This is a config-only
slice — no source code logic changes.

**Depends On:** — (independent; sequenced after S7 to keep the sprint tidy)

**Agent Lane:** code-executor edits `pyproject.toml` and `Makefile`. No test additions
required (gate verifies pyproject syntax implicitly; the marker test is the smoke test
in S9). Orchestrator runs `make gate`.

**Files:**
- `pyproject.toml` — modify
- `Makefile` — modify

**Implementation Notes:**

`pyproject.toml` changes:
```toml
[project.optional-dependencies]
diarize = ["whisperx>=3.8.6,<4.0"]
```
torch, torchaudio, and pyannote.audio must NOT be listed — they enter as transitives
via whisperX's own `pyproject.toml`. Re-declaring them creates a conflict surface with
whisperX's tight `torch~=2.8.0` pin (INV-13, DDR-05 externals finding).

`[tool.pytest.ini_options]` gains:
```toml
markers = [
    "smoke: end-to-end tests requiring ffmpeg and faster-whisper",
    "diarize_smoke: end-to-end tests requiring HF_TOKEN env var and [diarize] installed",
]
```
The existing `smoke` marker string must be preserved exactly.

`Makefile` gate target update:
```makefile
gate:
	black --check .
	ruff check .
	pytest -m "not smoke and not diarize_smoke"
```
This ensures that when `test_smoke_diarize.py` (S9) exists, its `diarize_smoke`-marked
tests are excluded from `make gate` even if skip guards somehow fail (belt-and-suspenders
for INV-8).

**Done When:**
- `pyproject.toml` contains `[diarize]` under `[project.optional-dependencies]`.
- `whisperx>=3.8.6,<4.0` is the only entry in `[diarize]`.
- `diarize_smoke` marker is registered in `[tool.pytest.ini_options].markers`.
- `Makefile` gate target uses `pytest -m "not smoke and not diarize_smoke"`.
- `make gate` green.

---

### S9 — `tests/test_smoke_diarize.py` (diarize smoke test)

**Goal:** Write the diarize smoke test that exercises `WhisperXBackend().transcribe()`
end-to-end with real whisperX and real pyannote. Marked `@pytest.mark.diarize_smoke`;
excluded from `make gate`; skipped if `HF_TOKEN` is absent or `[diarize]` is not
installed.

**Depends On:** S6 (WhisperXBackend exists), S8 (marker registered, gate filter updated)

**Agent Lane:** test-writer creates `tests/test_smoke_diarize.py`. Orchestrator does NOT
run this during the standard gate loop; it is run only manually or via `pytest -m
diarize_smoke` with `HF_TOKEN` set and `[diarize]` installed.

**Files:**
- `tests/test_smoke_diarize.py` — create

**Implementation Notes:**

Skip guard at top of each test (not at module level, so the file is always importable):
```python
pytest.importorskip("whisperx")      # skip if [diarize] not installed
if not os.environ.get("HF_TOKEN"):
    pytest.skip("HF_TOKEN not set")
```

Synthetic WAV generation: use `imageio-ffmpeg` (already in `[dev]`) to generate a 5-second
sine-tone WAV with a 1-second silence gap at 2.5 s. This simulates a speaker turn without
requiring real speech for the smoke's structural assertion.

The smoke test asserts structure, not accuracy:
1. `WhisperXBackend().transcribe(cfg, wav_path)` completes without exception.
2. Result is a `Transcript` with `segments` and `info`.
3. `info.backend.startswith("diarize:")` is True.
4. `len(info.backend.split(":")) == 2`.
5. `write_outputs(...)` writes four files to `tmp_path`.
6. `data["schema_version"] == 1` in the JSON output.

The smoke test does NOT assert speaker label accuracy — synthetic tones are not real
speech; pyannote's output is not deterministic for this input.

CI note (not a code concern): the `diarize_smoke` job runs only via `workflow_dispatch`
with `HF_TOKEN` secret configured — not on every push. This is a deployment/CI concern
outside the scope of this slice.

**Tests (added this slice):**
- `test_diarize_smoke_end_to_end` — `@pytest.mark.diarize_smoke`; runs full pipeline;
  asserts `Transcript` returned, `info.backend` format correct, all four output files
  written, `schema_version == 1`.

**Done When:**
- `tests/test_smoke_diarize.py` exists and is importable.
- Skip guards present: `pytest.importorskip("whisperx")` and `HF_TOKEN` check.
- `@pytest.mark.diarize_smoke` applied to the test function.
- `make gate` green (diarize_smoke excluded by updated filter; file is importable without
  whisperX installed).
- `pytest -m diarize_smoke` runs without collection error when `[diarize]` is installed
  and `HF_TOKEN` is set.

---

### S10 — README documentation for diarize backend

**Goal:** Update `README.md` with the diarize backend row in the backends table, the
`[diarize]` install instructions, `HF_TOKEN` setup steps, and a visible Terms of Service
notice directing users to accept the pyannote model license on HuggingFace before use.

**Depends On:** S7 (backend name `"diarize"` confirmed in registry)

**Agent Lane:** doc-writer (or orchestrator for docs-only). No gate change needed.
Docs-only PR — CADENCE fast-path: branch → PR → self-merge, no review wait.

**Files:**
- `README.md` — modify

**Implementation Notes:**
- Add a row for `diarize` to the existing backends table (alongside `local` and `api`).
  Columns: backend name, description, install command, hardware requirement.
- Add a new section (e.g., `### diarize backend` or inline under an existing
  "Installation" heading) covering:
  - Install: `pip install electric-blue[diarize]`
  - Env var: `HF_TOKEN=<your-token>` (required; not optional)
  - Point to `HF_TOKEN` source: HuggingFace account → Settings → Access Tokens
- Add a visible ToS callout (blockquote or bold notice) directing users to visit
  `https://huggingface.co/pyannote/speaker-diarization-3.1` and accept the model
  license before use. Without acceptance the token will be rejected by the pyannote
  pipeline at runtime.
- Add a Windows note in the `[diarize]` install section: `triton` (a transitive
  dependency via torch/whisperX) has no Windows binary on PyPI. Windows users (e.g. the
  ASUS ROG box) must either use WSL2 or install torch separately with the appropriate
  Windows wheel before running `pip install electric-blue[diarize]`. This note must
  appear in the `[diarize]` install section, not buried elsewhere.
- No source code changes. No gate run required. No Frank BUILD gate required.

**Done When:**
- `README.md` contains a `diarize` row in the backends table.
- `README.md` contains `[diarize]` install instructions with `pip install electric-blue[diarize]`.
- `README.md` contains `HF_TOKEN` setup steps.
- `README.md` contains a visible ToS acceptance notice linking to the pyannote model card.
- `README.md` contains a Windows note in the `[diarize]` install section stating that
  `triton` has no Windows PyPI binary and directing Windows users to WSL2 or a manual
  torch wheel install.

---

## Sequence Rules

1. Complete each slice fully (code + tests + gate green) before beginning the next.
2. No partial slice work — a slice is either complete or not started.
3. If `make gate` fails after a slice: diagnose and fix within the slice boundary.
   Three failed fix attempts on the same issue → **HALT** to human; revert to last
   gate-green commit.
4. `@test-writer` has no shell access — orchestrator runs `black`, `ruff`, and `pytest`
   after every test-authoring step.
5. Gate must remain hermetic at every slice: `pytest -m "not smoke and not diarize_smoke"`
   runs zero network calls, loads zero real models, requires zero HF_TOKEN (INV-8).
6. S2 char tests must be verified green against the unmodified code before any source
   file is changed. Orchestrator should run `make gate` after S2 with no source changes
   to confirm the baseline is captured.
7. The smoke test (S9) is never run as part of the gate loop. It is attested separately
   before the Frank BUILD gate (CADENCE P6).

---

## Requirement Coverage

Every acceptance criterion from `01-REQUIREMENTS.md` is addressed:

| AC | Architecture Element | Verifying Slice |
|----|---------------------|-----------------|
| US-1: four-stage pipeline runs | `WhisperXBackend.transcribe()` stages 1–4 | S6 |
| US-1: SPEAKER_NN in JSON | `Segment.speaker` + `to_dict()` | S3 |
| US-1: `[SPEAKER_NN]` in SRT/VTT | `outputs.py` cue rendering | S5 |
| US-1: TXT unchanged | `outputs.py` TXT path unchanged | S5 |
| US-1: `backend = "diarize:<model>"` | `TranscriptInfo.backend` format | S6 |
| US-1: majority-time speaker | `_assign_majority_speaker()` | S6 |
| US-2: ConfigurationError on no HF_TOKEN | guard in `WhisperXBackend.__init__()` | S6 |
| US-2: ImportError on missing extra | lazy import propagation | S6 |
| US-3: `[diarize]` extra opt-in | `pyproject.toml` | S8 |
| US-3: base install unaffected | lazy import + separate extra | S6, S8 |
| US-4: `to_dict()` omits `"speaker"` when None | `Segment.to_dict()` | S3 |
| US-4: TXT no speaker prefix | `outputs.py` TXT path | S5 |
| US-5: auto-detect mode | no `num_speakers` kwarg | S6 |
| US-5: fixed speaker count | `cfg.diarize_num_speakers` passed to pipeline | S4, S6 |
| US-5: invalid num_speakers raises | `_parse_diarize_num_speakers()` | S4 |
| US-6: `schema_version == 1` for diarized output | `outputs.py` literal | S5 |
| US-6: `"speaker"` absent in non-diarized output | `to_dict()` conditional | S3 |
| US-7: registry dispatch | `_FACTORIES["diarize"]` | S7 |
| US-7: no `if/else` on backend name | registry pattern (INV-11) | S7 |
| INV-7: HF_TOKEN never in artifacts | no logging of `hf_token` | S4, S6 |
| INV-8: gate hermetic | `sys.modules` mock seam | S6, S8 |
| INV-10: schema_version stays 1 | literal in `outputs.py` | S5 |
| INV-11: registry-only dispatch | `_FACTORIES` + `_REGISTRY` + no `if cfg.backend ==` | S7 |
| INV-13: only `whisperx>=3.8.6,<4.0` in `[diarize]` | `pyproject.toml` | S8 |

---

## Deferred Work (not this roadmap)

These items appear in the requirements or DDR as out-of-scope or explicitly deferred:

- **D2 / word-level speaker assignment** — word-level speaker data within segments;
  mid-cue speaker splitting in SRT/VTT. Deferred to a future DDR.
- **D3d / mid-cue speaker-change splitting** — SRT/VTT cue splitting at speaker boundaries.
  Deferred.
- **D3c / speaker prefix in TXT** — inline speaker attribution in plain-text output.
  Explicitly out of scope; TXT is for plain-text consumers.
- **D4 / CC-BY pyannote community-1 model** — non-gated diarization model evaluation.
  Deferred.
- **D6 / `min_speakers` + `max_speakers` config fields** — bounds-mode configuration.
  Deferred to a future DDR. Only `auto` and `num_speakers` are implemented this sprint.
- **Windows ASUS ROG deployment path** — `triton>=3.3.0` is Linux x86_64 only; a
  separate install path is required for the Windows host. The README note (S10) covers
  the user-facing warning; the full separate install path is outside this sprint's scope.
- **GPU routing hints** — backend-routing in watcher/CLI based on file duration or backend
  capability. Out of scope.
- **VRAM management / model quantization** — sequential model unloading for limited-VRAM
  GPUs. Out of scope.
- **Speaker accuracy benchmarking** — validation against labelled test audio. Out of scope.
- **CI auto-trigger for `diarize_smoke`** — adding `pull_request` trigger to the smoke CI
  job. A deployment/CI decision deferred to the Composer.
