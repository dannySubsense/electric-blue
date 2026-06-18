# Architecture: whisperx-diarization (DDR-05)

- **Status:** DRAFT
- **Author:** reed
- **Date:** 2026-06-18
- **Spec session:** whisperx-diarization
- **Requirements:** `docs/specs/whisperx-diarization/01-REQUIREMENTS.md`
- **DDR:** `docs/specs/electric-blue-ddrs/DDR-05-whisperx-diarization.md`

All locked decisions (D1–D7) are final; this document does not reopen them.

---

## Components

| Component | Type | Location | Responsibility |
|-----------|------|----------|----------------|
| `ConfigurationError` | exception class | `src/electric_blue/exceptions.py` (NEW) | Named exception for absent/invalid config; raised by both `config.py` and `diarize.py` |
| `WhisperXBackend` | Backend implementor | `src/electric_blue/backends/diarize.py` (NEW) | Four-stage pipeline: transcribe → align → diarize → assign; conforms to `Backend` Protocol |
| `Segment` | data schema | `src/electric_blue/models.py` (MODIFIED) | Gains `speaker: str | None = None`; `to_dict()` omits key when `None` |
| `Config` | config dataclass | `src/electric_blue/config.py` (MODIFIED) | Gains `hf_token: str` and `diarize_num_speakers: int | None`; validation in `from_env()` |
| `write_outputs` | output writer | `src/electric_blue/outputs.py` (MODIFIED) | SRT/VTT cue text gains `[SPEAKER_NN]` prefix when `segment.speaker is not None`; TXT unchanged |
| `_REGISTRY` / `_FACTORIES` | dispatch dicts | `src/electric_blue/backends/__init__.py` (MODIFIED) | `_REGISTRY` unchanged; `_FACTORIES = {"diarize": WhisperXBackend}` added; `get_backend` constructs `WhisperXBackend(cfg)` on demand |
| `[diarize]` extra | dependency | `pyproject.toml` (MODIFIED) | `whisperx>=3.8.6,<4.0` only; torch/pyannote transitive |
| `test_diarize_pipeline.py` | hermetic tests | `tests/test_diarize_pipeline.py` (NEW) | Gate-included; mocks whisperX via `sys.modules`; no torch/HF token required |
| `test_smoke_diarize.py` | smoke tests | `tests/test_smoke_diarize.py` (NEW) | `@pytest.mark.diarize_smoke`; skipped without HF_TOKEN or `[diarize]` |

---

## Data Schemas

### `ConfigurationError` — `src/electric_blue/exceptions.py`

```python
class ConfigurationError(Exception):
    """Raised when a required configuration value is absent or invalid.

    Used by Config.from_env() (invalid env vars) and WhisperXBackend.__init__()
    (missing HF_TOKEN). Not caught inside electric_blue — propagates to watcher.handle()
    which routes the file to failed/.
    """
```

### `Segment` — updated `src/electric_blue/models.py`

```python
@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None  # None when no diarization was run; matches SPEAKER_NN pattern

    def to_dict(self) -> dict:
        d = {"start": self.start, "end": self.end, "text": self.text}
        if self.speaker is not None:
            d["speaker"] = self.speaker  # key absent when None; never "speaker": null
        return d
```

Backward-compatibility guarantee: existing callers constructing `Segment(start, end, text)` positionally or as keyword args are unaffected. The `speaker` field is keyword-only by position (it follows three required fields) and defaults to `None`. `schema_version` stays at `1` (INV-10).

### `Config` new fields — `src/electric_blue/config.py`

Two fields added to the `Config` dataclass in a new `# Diarize backend` group after the existing `# Batch fields` group:

```python
# Diarize backend
hf_token: str              # HF_TOKEN env var; default ""; never logged or serialized (INV-7)
diarize_num_speakers: int | None  # WHISPER_DIARIZE_NUM_SPEAKERS; default None = auto-detect
```

`from_env()` additions:

```python
hf_token=os.environ.get("HF_TOKEN", ""),
diarize_num_speakers=_parse_diarize_num_speakers(
    os.environ.get("WHISPER_DIARIZE_NUM_SPEAKERS")
),
```

Module-level validation helper (in `config.py`, called by `from_env()`):

```python
def _parse_diarize_num_speakers(raw: str | None) -> int | None:
    """Parse WHISPER_DIARIZE_NUM_SPEAKERS.

    Returns None for auto-detect, a positive int when set, or raises
    ConfigurationError for non-integer or non-positive values.
    """
    if raw is None:
        return None
    try:
        val = int(raw)
    except ValueError:
        raise ConfigurationError(
            f"WHISPER_DIARIZE_NUM_SPEAKERS must be a positive integer, got {raw!r}"
        )
    if val <= 0:
        raise ConfigurationError(
            f"WHISPER_DIARIZE_NUM_SPEAKERS must be a positive integer, got {val}"
        )
    return val
```

`config.py` gains `from .exceptions import ConfigurationError` at the top-level import block.
The `backend` field comment gains `"diarize"` as a valid value.

### `WhisperXBackend.capabilities` schema

```python
Capabilities(
    supports_diarization=True,
    is_async=False,
    needs_network=False,      # post model-cache; first run downloads models
    needs_gpu_recommended=True,
    max_upload_mb=None,
)
```

`needs_gpu_recommended=True` is a declarative hint only. CPU execution is fully supported
(D5); no runtime warning, no error, no degraded code path when `device` resolves to `"cpu"`.

### JSON segment output schema (no version bump)

Non-diarized segment dict (unchanged):
```json
{"start": 0.0, "end": 1.5, "text": "Hello world."}
```

Diarized segment dict (additive; `schema_version` stays `1`):
```json
{"start": 0.0, "end": 1.5, "text": "Hello world.", "speaker": "SPEAKER_00"}
```

---

## API Contracts

### `src/electric_blue/backends/diarize.py`

```python
class WhisperXBackend:
    name: str = "diarize"
    capabilities: Capabilities = Capabilities(...)   # see schema above

    def __init__(self, cfg: Config) -> None:
        """
        Validate HF_TOKEN presence at construction time.

        Called by get_backend(cfg) when cfg.backend == "diarize". The watcher calls
        get_backend during initialisation, before the watch loop, so this check fires
        at service startup — the operator learns of broken config immediately, not
        when the first file drops hours later.

        Raises:
            ConfigurationError: if cfg.hf_token is absent or empty.
        """

    def transcribe(self, cfg: Config, src: Path) -> Transcript:
        """
        Execute the four-stage whisperX pipeline on src.

        Raises:
            ImportError: if [diarize] extra is not installed (lazy import fails).
            OSError / EnvironmentError: if pyannote model ToS not accepted on HF
                (propagates from DiarizationPipeline; not suppressed).
        """
```

Module-level helpers (package-private; directly patchable in tests):

```python
def _resolve_device(cfg: Config) -> str:
    """
    Return the effective device string ("cuda" | "cpu").
    Mirrors local.py logic: if cfg.device == "auto", probe torch.cuda;
    fall back to "cpu" on ImportError or unavailability.
    CPU is a valid first-class target; no warning emitted.
    """

def _resolve_compute(cfg: Config) -> str:
    """
    Return the effective compute_type string.
    Returns cfg.compute_type if it is not "auto", otherwise returns "int8"
    (CPU is the primary target per D5; int8 is the CPU-safe default).
    """

def _get_whisperx():
    """
    Lazy import with module-level cache (_whisperx global).
    Returns the whisperx module object.
    Raises ImportError if whisperx is not installed.
    This is the hermetic seam: gate tests patch sys.modules['whisperx']
    before calling transcribe(); this function picks up the patched module.
    Note: DiarizationPipeline is NOT on the top-level whisperx namespace in v3.8.6;
    import it directly via `from whisperx.diarize import DiarizationPipeline`.
    """

def _assign_majority_speaker(segment_dict: dict) -> str | None:
    """
    Given a whisperX segment dict (post assign_word_speakers), return the
    majority-time speaker label.

    Strategy:
      1. If the segment dict has a top-level "speaker" key, return it directly
         (whisperX may populate this when word-level data is present).
      2. Otherwise, sum elapsed duration per speaker across the "words" list
         using each word's "start"/"end" interval.
      3. Return the speaker with the greatest accumulated duration.
      4. Tie-break: alphabetically first speaker label (e.g., SPEAKER_00 before
         SPEAKER_01). This is deterministic and must be documented in code.
      5. If no words carry speaker data and no segment-level key exists, return None.
    """
```

Pipeline execution sequence inside `transcribe()`:

```
1. Resolve device via _resolve_device(cfg).

2. Extract audio: audio.extract(cfg, src, wav_path, compressed=False)
   into a temp directory (same pattern as local.py).

3. Lazy import: wx = _get_whisperx()

4. Stage 1 — Transcription:
   audio_array = wx.load_audio(str(wav_path))
   model = wx.load_model(cfg.model_size, device, compute_type=_resolve_compute(cfg))
   result = model.transcribe(audio_array, language=cfg.language or None, batch_size=16)
   language = result["language"]

5. Stage 2 — Alignment:
   align_model, metadata = wx.load_align_model(language_code=language, device=device)
   result = wx.align(result["segments"], align_model, metadata, audio_array, device)

6. Stage 3 — Diarization:
   diarize_kwargs = {}
   if cfg.diarize_num_speakers is not None:
       diarize_kwargs["num_speakers"] = cfg.diarize_num_speakers
   from whisperx.diarize import DiarizationPipeline
   diarize_pipeline = DiarizationPipeline(
       model_name=None, token=cfg.hf_token, device=device
   )
   diarize_segments = diarize_pipeline(audio_array, **diarize_kwargs)

7. Stage 4 — Assignment:
   result = wx.assign_word_speakers(diarize_segments, result)

8. Convert to Segment list:
   segments = [
       Segment(
           start=s["start"],
           end=s["end"],
           text=s.get("text", "").strip(),
           speaker=_assign_majority_speaker(s),
       )
       for s in result["segments"]
   ]

9. Build TranscriptInfo:
   info = TranscriptInfo(
       language=language,
       language_probability=None,   # whisperX does not expose this; omitted
       duration=round(float(result.get("duration", segments[-1].end if segments else 0.0)), 2),
       backend=f"diarize:{cfg.model_size}",
   )

10. Return Transcript(segments=segments, info=info)
```

Note: `language_probability` is `None` because whisperX's `transcribe()` does not expose
a confidence score at the transcript level. `TranscriptInfo.language_probability` is already
typed `float | None`, so `None` is valid.

### `src/electric_blue/outputs.py` — modified cue rendering

`write_outputs` signature is UNCHANGED. Internal change to SRT and VTT writers only.

SRT (replace `s.text` with):
```python
cue_text = f"[{s.speaker}] {s.text}" if s.speaker is not None else s.text
```

VTT (same replacement):
```python
cue_text = f"[{s.speaker}] {s.text}" if s.speaker is not None else s.text
```

TXT: no change. Continues to use `" ".join(s.text for s in segments)`.
JSON: no change to `write_outputs`. Speaker appears in segment dicts via `s.to_dict()`.

When no segment carries a speaker (all `speaker=None`), all four output formats are
byte-for-byte identical to their current output. No new branch on backend name anywhere
in `outputs.py`.

### `src/electric_blue/backends/__init__.py` — updated registry

```python
from .diarize import WhisperXBackend

_REGISTRY: dict[str, Backend] = {
    "local": LocalBackend(),
    "api": ApiBackend(),
}

_FACTORIES: dict[str, type[Backend]] = {
    "diarize": WhisperXBackend,
}

# get_backend checks _REGISTRY first (eager singletons), then _FACTORIES
# (constructed on demand with cfg). WhisperXBackend is never pre-instantiated
# so `import electric_blue.backends` is safe when HF_TOKEN is absent (INV-8).
```

`WhisperXBackend` is NOT pre-instantiated in `_REGISTRY`. `get_backend` checks
`_REGISTRY` first; on a miss it checks `_FACTORIES` and calls `_FACTORIES[name](cfg)`,
constructing the backend with `cfg`. The validation in `WhisperXBackend.__init__(cfg)`
fires at that point. The watcher calls `get_backend` during initialisation (before the
watch loop), so a missing HF_TOKEN raises `ConfigurationError` at service startup.
`import electric_blue.backends` never raises even when HF_TOKEN is absent (INV-8).

---

## Patterns

| Pattern | Usage | Rationale |
|---------|-------|-----------|
| Lazy import with module-level cache | `_get_whisperx()` caches whisperX after first import | Matches `local.py`'s `_model` cache; keeps gate hermetic (INV-8); isolates `[diarize]` from base install |
| Protocol conformance (structural) | `WhisperXBackend` conforms to `Backend` Protocol without inheritance | Consistent with `LocalBackend` and `ApiBackend`; no coupling to base class |
| Registry dispatch | eager backends in `_REGISTRY`; factory backends in `_FACTORIES`; `get_backend` checks both | INV-11; no `if/else` on backend name anywhere |
| Data-driven output rendering | `s.speaker is not None` check in outputs.py | No branch on `cfg.backend` in output layer; works for any future backend that sets `speaker` |
| Additive schema evolution | `speaker` added as optional field, `schema_version` stays 1 | INV-10; backward-compatible; no consumer breakage |
| Fail-loud on missing config | `ConfigurationError` raised in `WhisperXBackend.__init__(cfg)` when `get_backend` constructs it at service startup | INV-2; operator learns of broken config at service startup, not at first file drop |
| Transitive-only ML dep | `[diarize]` declares only `whisperx>=3.8.6,<4.0` | INV-13; whisperX owns torch/pyannote pins; re-declaring creates a conflict surface |

### Anti-Patterns (Do Not Use)

- `if cfg.backend == "diarize":` anywhere in source — INV-11 forbids it; use the registry.
- `import whisperx` at module level in `diarize.py` — breaks hermetic gate (INV-8) and base install isolation.
- `"speaker": null` in segment dict — omit the key entirely when `None` (D3b).
- Speaker prefix in TXT output — D3c; TXT is for plain-text consumers.
- `schema_version: 2` — INV-10; stays at 1; no bump for additive optional fields.
- Logging or printing `cfg.hf_token` — INV-7.
- Declaring `torch`, `torchaudio`, or `pyannote.audio` directly in `[diarize]` deps — creates a conflict surface with whisperX's own tight pins (DDR-05 externals finding).

---

## Dependencies

| Dependency | Version Constraint | Location | Notes |
|------------|-------------------|----------|-------|
| `whisperx` | `>=3.8.6,<4.0` | `[project.optional-dependencies].diarize` | Only direct dep in `[diarize]`; pulls torch~=2.8.0, pyannote-audio>=4.0.0, faster-whisper>=1.2.0 transitively |
| `torch` | transitive via whisperX | — | whisperX pins `torch~=2.8.0`; do NOT re-declare |
| `pyannote.audio` | transitive via whisperX | — | whisperX pins `>=4.0.0`; do NOT re-declare |
| `torchaudio` | transitive via whisperX | — | Do NOT re-declare |
| `faster-whisper` | already in `[local]` as `>=1.2.0,<2.0` | `[local]` extra (unchanged) | whisperX pins `>=1.2.0`; compatible; no conflict |
| `numpy` | transitive via whisperX | — | `>=2.1.0` per whisperX 3.8.6 |
| `triton` | transitive via whisperX | — | `>=3.3.0`; pulled transitively by torch via whisperX; no Windows binary on PyPI — Windows deployments (ASUS ROG) must install torch separately without triton or use WSL2; operator concern for Windows only, not a blocker for R630 (Linux); the S10 README docs slice must include a Windows install note |

The `[local]` extra (`faster-whisper>=1.2.0,<2.0`) is unchanged.
The `[dev]` extra is unchanged.

`pyproject.toml` `[tool.pytest.ini_options].markers` gains:
```toml
"diarize_smoke: end-to-end tests requiring HF_TOKEN env var and [diarize] installed"
```

---

## Integration Points

| Existing Component | Integration |
|--------------------|-------------|
| `Backend` Protocol (`backends/base.py`) | `WhisperXBackend` conforms structurally; no changes to `base.py` required |
| `_REGISTRY` / `_FACTORIES` (`backends/__init__.py`) | Add `_FACTORIES = {"diarize": WhisperXBackend}`; extend `get_backend` to check `_FACTORIES` and construct with `cfg`; import `WhisperXBackend` from `.diarize` |
| `Config.from_env()` (`config.py`) | Two new fields: `hf_token`, `diarize_num_speakers`; new import of `ConfigurationError` |
| `Segment.to_dict()` (`models.py`) | Additive change; all existing callers unaffected |
| `write_outputs()` (`outputs.py`) | Inline `s.speaker` check in SRT/VTT writers; signature unchanged |
| `audio.extract()` | Reused unchanged — extracts audio to temp WAV before passing to whisperX |
| `watcher.run_watch()` | ONE line added: `get_backend(cfg)` as the first statement before `run_once(cfg)` and the observer, so validation fires before any backlog files are processed; `handle()` unchanged |
| `TranscriptInfo` (`models.py`) | No change to class; `backend` field format becomes `"diarize:<model_size>"` for this backend |

---

## Gate and Smoke Strategy

### Hermetic gate — `tests/test_diarize_pipeline.py`

Runs under `make gate` (`pytest -m "not smoke and not diarize_smoke"`). Zero network, zero
real models, zero HF token.

**Mock seam:** Pre-populate `sys.modules["whisperx"]` and `sys.modules["whisperx.diarize"]`
with `types.SimpleNamespace` objects before any call to `WhisperXBackend.transcribe()`.
Because the whisperx import is lazy, the gate test installs the fakes before the import
executes and `_get_whisperx()` picks up the patched module. `DiarizationPipeline` is not
on the top-level whisperx namespace in v3.8.6 — it must be patched at `whisperx.diarize`.

**Patch targets for reliable intercept** (use submodule paths, not top-level aliases):

| Symbol | Correct patch target |
|--------|---------------------|
| `DiarizationPipeline` | `whisperx.diarize.DiarizationPipeline` |
| `load_model` | `whisperx.asr.load_model` |
| `load_align_model` | `whisperx.alignment.load_align_model` |
| `align` | `whisperx.alignment.align` |
| `load_audio` | `whisperx.audio.load_audio` |
| `assign_word_speakers` | `whisperx.diarize.assign_word_speakers` |

```python
@pytest.fixture()
def fake_whisperx(monkeypatch):
    import types
    wx = types.SimpleNamespace(
        load_audio=lambda path: b"",           # returns fake audio array
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
    # Also clear the module-level cache so _get_whisperx() picks up the fake
    monkeypatch.setattr("electric_blue.backends.diarize._whisperx", None)
    return wx
```

`FakeDiarizationPipeline`: callable; returns synthetic annotation representing two speakers:
```
SPEAKER_00: 0.0 – 2.5 s
SPEAKER_01: 2.5 – 5.0 s
```

`FakeModel`: has `.transcribe()` returning a dict with `"segments"` and `"language": "en"`.

`fake_assign_word_speakers`: returns the aligned result unchanged but with `"speaker"` keys
injected on each segment dict based on time ranges matching the fake diarization.

**Required hermetic test cases:**

| Test | Assertion |
|------|-----------|
| `test_speaker_assignment_basic` | Given fake aligned segments + fake diarizer, `Segment.speaker` is `"SPEAKER_00"` or `"SPEAKER_01"` per time range |
| `test_majority_speaker_wins` | Segment spanning 0.0–3.5 s with `SPEAKER_00` for 2.5 s, `SPEAKER_01` for 1.0 s → `speaker="SPEAKER_00"` |
| `test_tie_break_alphabetical` | Segment split exactly 50/50 between two speakers → alphabetically first label returned |
| `test_missing_hf_token_raises` | HF_TOKEN env var absent or empty at construction → `ConfigurationError` raised from `WhisperXBackend.__init__(cfg)` |
| `test_backend_name` | `WhisperXBackend.name == "diarize"` |
| `test_backend_supports_diarization` | `WhisperXBackend.capabilities.supports_diarization is True` |
| `test_registry_contains_diarize` | `"diarize" in _FACTORIES` (or `get_backend(cfg_diarize)` returns a `WhisperXBackend`) |
| `test_transcript_info_backend_format` | `info.backend == f"diarize:{cfg.model_size}"` |
| `test_segment_to_dict_omits_speaker_when_none` | `Segment(0,1,"x").to_dict()` has no `"speaker"` key |
| `test_segment_to_dict_includes_speaker_when_set` | `Segment(0,1,"x",speaker="SPEAKER_00").to_dict()["speaker"] == "SPEAKER_00"` |
| `test_srt_speaker_prefix` | SRT cue text for `speaker="SPEAKER_00"` starts with `"[SPEAKER_00]"` |
| `test_vtt_speaker_prefix` | VTT cue text for `speaker="SPEAKER_01"` starts with `"[SPEAKER_01]"` |
| `test_txt_no_speaker_prefix` | TXT output contains no `"[SPEAKER_"` substring |
| `test_json_speaker_field_present` | JSON segment dict has `"speaker"` key when diarized |
| `test_json_schema_version_still_1` | `data["schema_version"] == 1` for diarized output |
| `test_no_speaker_output_identical` | All-`None` speaker list → output byte-for-byte identical to non-diarized baseline |
| `test_num_speakers_passed_to_pipeline` | `cfg.diarize_num_speakers=2` → `DiarizationPipeline.__call__` receives `num_speakers=2` |
| `test_num_speakers_absent_in_auto_mode` | `cfg.diarize_num_speakers=None` → `DiarizationPipeline.__call__` called without `num_speakers` kwarg |
| `test_config_invalid_num_speakers_zero` | `WHISPER_DIARIZE_NUM_SPEAKERS=0` in env → `ConfigurationError` from `Config.from_env()` |
| `test_config_invalid_num_speakers_negative` | `WHISPER_DIARIZE_NUM_SPEAKERS=-1` → `ConfigurationError` |
| `test_config_invalid_num_speakers_string` | `WHISPER_DIARIZE_NUM_SPEAKERS=two` → `ConfigurationError` |

### Smoke — `tests/test_smoke_diarize.py`

Marked `@pytest.mark.diarize_smoke`. Excluded from `make gate` and from the standard `make smoke`
(which uses `-m smoke`). Run separately with `pytest -m diarize_smoke`.

Skip conditions (top of each test):
```python
pytest.importorskip("whisperx")                   # skips if [diarize] not installed
if not os.environ.get("HF_TOKEN"):
    pytest.skip("HF_TOKEN not set")
```

The smoke test:
1. Generates a minimal synthetic WAV using `imageio-ffmpeg` (already in `[dev]`): 5 seconds of
   sine tones with a 1-second silence gap simulating a speaker turn.
2. Calls `WhisperXBackend(cfg).transcribe(cfg, wav_path)` with real whisperX, real pyannote.
3. Asserts: `Transcript` returned without exception; `info.backend.startswith("diarize:")`;
   `len(info.backend.split(":")) == 2`; JSON output written; `schema_version == 1`.
4. Does NOT assert speaker label accuracy (synthetic tones are not real speech).

CI: runs only via `workflow_dispatch` with `HF_TOKEN` secret configured; excluded from the
push/PR matrix.

---

## Startup Validation (INV-2)

Missing HF_TOKEN surfaces as a `ConfigurationError` raised in `WhisperXBackend.__init__(cfg)`
at backend construction time. `WhisperXBackend` is constructed lazily by `get_backend(cfg)`
when `cfg.backend == "diarize"`. ConfigurationError fires when `get_backend(cfg)` is called as the first statement of
`run_watch()`, before `run_once(cfg)` drains the backlog and before the observer starts —
so no files are processed before validation.
This is the earliest possible validation point that doesn't affect the hermetic gate.
`import electric_blue.backends` never raises (INV-8). Error message: directs operator to
accept pyannote model terms at `https://huggingface.co/pyannote/speaker-diarization-3.1`
and set `HF_TOKEN`.

Missing `[diarize]` extra surfaces as `ImportError` from the lazy `import whisperx` inside
`transcribe()`. Not caught; propagates to `watcher.handle()` which routes the file to `failed/`
and sends notification (INV-1, INV-2).

HF ToS not accepted: pyannote raises `OSError` or `EnvironmentError` from
`DiarizationPipeline(token=...)`. Not caught; same propagation path as `ImportError`.

The `ConfigurationError` class is defined in `exceptions.py` (not in `config.py` or inline)
so both `config.py` and `backends/diarize.py` can import it without circular dependency:

```
exceptions.py        ← no local imports
  ↑
config.py            ← imports ConfigurationError from exceptions
  ↑
backends/diarize.py  ← imports Config from config, ConfigurationError from exceptions
```

`backend` comment in `Config` must list `"diarize"` as a valid value alongside `"local"` and
`"api"`.

---

## Requirement Coverage

| Requirement / Constraint | Architecture Element |
|--------------------------|---------------------|
| US-1 four-stage pipeline | `WhisperXBackend.transcribe()` stages 1–4 |
| US-2 loud failure on missing prereqs | `ConfigurationError` on missing HF_TOKEN in `__init__(cfg)`; `ImportError` propagation |
| US-3 opt-in `[diarize]` extra | `pyproject.toml` `[diarize]` extra; lazy imports |
| US-4 speaker labels in JSON/SRT/VTT only | `to_dict()` + `outputs.py` speaker rendering; TXT unchanged |
| US-5 configurable speaker count | `Config.diarize_num_speakers`; `WHISPER_DIARIZE_NUM_SPEAKERS` env var |
| US-6 backward-compatible schema | `speaker` additive field; `schema_version` stays 1 |
| US-7 registry dispatch | `"diarize"` in `_FACTORIES`; `get_backend` constructs on demand; no `if/else` |
| INV-2 fail loud | `ConfigurationError` in `__init__(cfg)`; no silent substitution |
| INV-7 secrets never in artifacts | `hf_token` never logged or serialized; `ConfigurationError` message contains no token value |
| INV-8 hermetic gate | `sys.modules` mock seam (`whisperx` + `whisperx.diarize`); `_get_whisperx()` cache clearable via monkeypatch |
| INV-10 schema_version stays 1 | Literal `1` in `outputs.py`; `speaker` is additive |
| INV-11 registry-only dispatch | `_FACTORIES["diarize"]`; no `if cfg.backend ==` |
| INV-13 ML stack pinned | `whisperx>=3.8.6,<4.0`; torch/pyannote transitive via whisperX |
| D5 CPU primary target | No GPU guard; `needs_gpu_recommended=True` is declarative only |
| D6 auto + fixed speaker count only | `diarize_num_speakers`; no `min`/`max` fields |
| D7 specific whisperX pin | `>=3.8.6,<4.0` |
