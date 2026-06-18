# Requirements: whisperx-diarization (DDR-05)

## Summary

Add a `"diarize"` backend to electric-blue that runs whisperX end-to-end
(transcribe → align → diarize → assign) to produce speaker-labelled transcripts.
The backend is strictly opt-in, CPU-primary, and conforms to the DDR-02 `Backend`
Protocol. Speaker labels appear in JSON, SRT, and VTT outputs; TXT is unchanged.

---

## User Stories

### US-1 — Speaker-labelled transcripts from the drop folder

As a pipeline operator,
I want to drop an audio or video file into the watched folder with `WHISPER_BACKEND=diarize`
and receive transcript files that attribute each segment to a speaker,
so that meeting recordings and multi-speaker audio are usable for search, summarisation,
and note-taking.

### US-2 — Clear failure when prerequisites are absent

As a pipeline operator,
I want the backend to raise a clear error at process startup if `HF_TOKEN` is not set
or if the `[diarize]` extra is not installed,
so that I know immediately what is missing rather than discovering a silent failure
mid-processing.

### US-3 — Opt-in installation; base install unaffected

As a pipeline operator maintaining the base install on the R630,
I want the diarization stack (whisperX, pyannote, torch) to be isolated behind a
`[diarize]` install extra that I must explicitly request,
so that the base `electric-blue` and `electric-blue[local]` installs remain lightweight
and unaffected by torch version constraints.

### US-4 — Speaker labels in structured output formats only

As a downstream transcript consumer,
I want speaker labels in JSON, SRT, and VTT output but not in the plain-text TXT file,
so that existing plain-text consumers are unaffected by the new field.

### US-5 — Configurable speaker count

As a pipeline operator,
I want to run the backend in auto-detect mode (no hint) or supply a fixed speaker count
via `WHISPER_DIARIZE_NUM_SPEAKERS`,
so that I can improve diarization accuracy for recordings where the speaker count is known.

### US-6 — Backward-compatible JSON schema

As a downstream transcript consumer whose tooling depends on the JSON output,
I want the JSON schema to remain at `schema_version: 1` and the `speaker` key to appear
only when diarization was run,
so that existing parsers are not broken by the new optional field.

### US-7 — Backend dispatched through the standard registry

As an operator using the watcher or CLI,
I want to select the diarize backend with `WHISPER_BACKEND=diarize` using the same
mechanism as all other backends,
so that there are no special-case dispatch paths in the codebase.

---

## Acceptance Criteria

### US-1 — Speaker-labelled transcripts from the drop folder

- [ ] Given a valid audio or video file in the watched directory with `WHISPER_BACKEND=diarize`,
  when the watcher picks it up, then all four pipeline stages execute
  (transcribe → align → diarize → assign) and output files are written before the
  source is moved to `done/`.
- [ ] Given a completed diarization run, when JSON output is read, then each segment
  that was assigned a speaker contains a `"speaker"` key whose value matches the
  pattern `SPEAKER_NN` (e.g., `SPEAKER_00`, `SPEAKER_01`).
- [ ] Given a completed diarization run, when SRT output is read, then each cue whose
  segment has a speaker is prefixed with `[SPEAKER_NN]` in the cue text.
- [ ] Given a completed diarization run, when VTT output is read, then each cue whose
  segment has a speaker is prefixed with `[SPEAKER_NN]` in the cue text.
- [ ] Given a completed diarization run, when TXT output is read, then no speaker prefix
  or label appears anywhere in the file.
- [ ] Given a completed diarization run, when `TranscriptInfo.backend` is read, then it
  equals `"diarize:<model_size>"` (e.g., `"diarize:distil-large-v3"`).
- [ ] Given a segment that spans a speaker-turn boundary (majority of its duration belongs
  to one speaker), when speaker assignment completes, then the segment's `speaker` field
  is set to the majority-time speaker.

### US-2 — Clear failure when prerequisites are absent

- [ ] Given `WHISPER_BACKEND=diarize` and `HF_TOKEN` not set (empty string or absent),
  when `WhisperXBackend` is instantiated (at service startup), then a `ConfigurationError`
  is raised with a message directing the operator to the HF token setup documentation;
  no file is processed silently.
- [ ] Given `WHISPER_BACKEND=diarize` and the `[diarize]` extra not installed,
  when the backend attempts the lazy whisperX import, then an `ImportError` (or wrapped
  `ConfigurationError`) is raised with a message indicating the missing extra; the
  error is logged and the source file is routed to `failed/`.
- [ ] Given either prerequisite failure, when the watcher's `handle()` processes the file,
  then the source file is moved to `failed/` and a notification is sent (INV-1, INV-2).

### US-3 — Opt-in installation; base install unaffected

- [ ] Given a fresh `pip install electric-blue` (no extras), when the install completes,
  then neither whisperX, pyannote, nor torch is present in the environment.
- [ ] Given a fresh `pip install "electric-blue[local]"`, when the install completes,
  then neither whisperX, pyannote, nor torch is present (faster-whisper uses ctranslate2,
  not torch).
- [ ] Given `pip install "electric-blue[diarize]"`, when the install completes, then
  whisperX `>=3.8.6,<4.0` and its transitive dependencies (including torch and pyannote)
  are present.
- [ ] Given `pip install "electric-blue[local,diarize]"`, when the install resolves,
  then the resolution succeeds without conflict (faster-whisper `>=1.2.0,<2.0` is
  compatible with whisperX's `>=1.2.0` floor).
- [ ] Given the `[diarize]` extra pinned to `whisperx>=3.8.6,<4.0`, when pyproject.toml
  is read, then torch, pyannote, and torchaudio are NOT listed as direct dependencies
  of `[diarize]` (they are transitive; re-declaring them creates a conflict surface).

### US-4 — Speaker labels in structured output formats only

- [ ] Given a `Segment` with `speaker=None`, when `to_dict()` is called, then the
  returned dict does not contain a `"speaker"` key.
- [ ] Given a `Segment` with `speaker="SPEAKER_00"`, when `to_dict()` is called, then
  the returned dict contains `"speaker": "SPEAKER_00"`.
- [ ] Given a list of segments where no segment has a speaker (all `speaker=None`),
  when any output format is written, then the output is byte-for-byte identical to the
  output produced by the existing `local` backend for the same segments.
- [ ] Given TXT output from a diarized run, when the file is read, then it contains no
  `[SPEAKER_` substring anywhere.

### US-5 — Configurable speaker count

- [ ] Given `WHISPER_DIARIZE_NUM_SPEAKERS` not set, when the diarization pipeline runs,
  then pyannote's DiarizationPipeline is invoked in auto-detect mode (no `num_speakers`
  argument passed).
- [ ] Given `WHISPER_DIARIZE_NUM_SPEAKERS=2`, when the diarization pipeline runs,
  then pyannote's DiarizationPipeline is invoked with `num_speakers=2`.
- [ ] Given `WHISPER_DIARIZE_NUM_SPEAKERS=0` or a negative integer, when `Config.from_env()`
  is called, then a `ConfigurationError` is raised at startup.

### US-6 — Backward-compatible JSON schema

- [ ] Given JSON output from a diarized run, when the file is parsed, then
  `schema_version` equals `1` (integer, not `2` or any other value).
- [ ] Given JSON output from a non-diarized run (local or api backend), when the file
  is parsed, then `schema_version` equals `1` — unchanged by the addition of the
  optional `speaker` field to `Segment`.
- [ ] Given a segment dict from a diarized JSON, when the keys are read, then `"speaker"`
  is present; given a segment dict from a non-diarized JSON, then `"speaker"` is absent
  (not `null`).

### US-7 — Backend dispatched through the standard registry

- [ ] Given `WHISPER_BACKEND=diarize`, when `get_backend(cfg)` is called, then it returns
  a `WhisperXBackend` instance without any `if/else` on backend name in dispatch code.
- [ ] Given `backends/__init__.py`, when the file is read, then the registry dict
  contains a `"diarize"` entry and no inline `if cfg.backend == "diarize"` branching exists.
- [ ] Given `WhisperXBackend`, when its `capabilities` are read, then
  `supports_diarization=True`, `is_async=False`, `needs_network=False` (post-cache),
  `needs_gpu_recommended=True`.
- [ ] Given `WhisperXBackend.name`, when read, then it equals `"diarize"`.

---

## Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| `HF_TOKEN` set but user has not accepted pyannote model ToS on HuggingFace | pyannote raises an `OSError` or `EnvironmentError`; the backend does NOT suppress it; the error propagates to `handle()` which routes the file to `failed/` |
| Audio file contains no detectable speech | Pipeline completes; zero segments returned; output files written (empty body); source moved to `done/` — same behavior as non-diarized backends |
| All audio attributed to a single speaker | Normal completion; all segments carry `SPEAKER_00`; no error |
| Segment whose duration is split exactly 50/50 between two speakers | Implementation chooses one deterministically (first-speaker or tie-break rule must be documented in code); behavior is consistent across runs |
| `WHISPER_DIARIZE_NUM_SPEAKERS` set to a non-integer string (e.g., `"two"`) | `ConfigurationError` raised at startup with a clear message |
| `[diarize]` installed but `torch` or `pyannote` missing from the transitive tree (broken install) | `ImportError` surfaces; not swallowed; file routed to `failed/` |
| Audio shorter than 1 second | Pipeline completes without crash; zero or one segment returned; no error |
| `WHISPER_DEVICE=cpu` (explicit or resolved from `auto` on a CPU-only host) | Backend runs normally on CPU; no warning emitted; no error raised — CPU is the primary target |

---

## Out of Scope

- NOT: Word-level speaker assignment within segments (deferred — D2)
- NOT: `WHISPER_DIARIZE_MIN_SPEAKERS` and `WHISPER_DIARIZE_MAX_SPEAKERS` env vars (deferred — D6)
- NOT: Mid-cue speaker-change splitting in SRT/VTT output (deferred — D3d)
- NOT: Runtime warning or error when `WHISPER_DEVICE` resolves to CPU (CPU is primary — D5)
- NOT: GPU-routing hints in the watcher or CLI (e.g., "route files longer than N minutes to the 4090")
- NOT: Evaluation or integration of pyannote CC-BY `community-1` model as a non-gated alternative (D4)
- NOT: NeMo or any diarization backend other than pyannote via whisperX
- NOT: VRAM management, model quantization, or sequential model unloading for limited-VRAM GPUs
- NOT: Speaker accuracy benchmarking or validation against labelled test audio
- NOT: Changes to the `local`, `api`, or `groq-batch` backends
- NOT: Word-level speaker data in `TranscriptInfo` or JSON (segment-level only — D2)
- NOT: Speaker prefix in TXT output (D3c)
- NOT: `schema_version` bump — stays at `1` (INV-10, DDR-02 D4)
- Deferred: `min_speakers` / `max_speakers` configuration modes — future DDR

---

## Constraints

### Hard requirements

- Must: DDR-02 (backend seam, `Backend` Protocol, `base.py`, `Capabilities`) must be merged to
  `main` before this sprint begins (DDR-05 dependency).
- Must: `WhisperXBackend` implements the `Backend` Protocol from `backends/base.py` structurally
  (no explicit inheritance required).
- Must: backend registered under the key `"diarize"` in the `backends/__init__.py` `_REGISTRY` dict.
- Must: `WhisperXBackend.name` equals `"diarize"`.
- Must: all four pipeline stages (transcribe, align, diarize, assign) use whisperX's own APIs
  (resolved D1 — not pyannote-direct, not reusing `local.py`'s faster-whisper stage).
- Must: whisperX and pyannote imports are lazy (inside `transcribe()`, not at module level) —
  same pattern as `local.py`'s `WhisperModel`.
- Must: `ConfigurationError` raised at backend instantiation (`__init__`) when the `cfg`
  constructor argument has an empty `hf_token` field (equivalent to `HF_TOKEN` env var being
  absent or empty at instantiation time); error message must reference HF token setup documentation.
- Must: `Segment.speaker` defaults to `None`; `to_dict()` omits the `"speaker"` key when `None`.
- Must: TXT output from a diarized run is identical in format to TXT output from a non-diarized run.
- Must: SRT and VTT cue text is prefixed with `[SPEAKER_NN]` when `segment.speaker` is not `None`.
- Must: `schema_version` remains `1` in all JSON output regardless of whether diarization was run.
- Must: `[diarize]` extra declares only `whisperx>=3.8.6,<4.0`; torch and pyannote enter as
  transitive deps only (INV-13).
- Must: `[local]` extra (`faster-whisper>=1.2.0,<2.0`) is unchanged.
- Must: `HF_TOKEN` is read from the environment only; never hardcoded, never logged, never written
  to any output artifact (INV-7).
- Must: `make gate` (`pytest -m "not smoke and not diarize_smoke"`) remains hermetic — zero network
  calls, zero real model loads, zero HF token required (INV-8).
- Must: diarize smoke tests are marked `@pytest.mark.diarize_smoke` and skip with `pytest.skip`
  when `HF_TOKEN` is absent or `[diarize]` is not installed.
- Must: existing tests for `local`, `api`, and `groq-batch` backends pass without modification.
- Must: CPU execution (including `WHISPER_DEVICE=cpu`) is fully supported with no runtime
  warning, no error, and no degraded code path — R630 (CPU-only) is the primary deployment host.

### Must-not

- Must not: modify `backends/local.py`, `backends/api.py`, or `backends/groq_batch.py`.
- Must not: add `if/else` dispatch branching on backend name anywhere in the codebase (INV-11).
- Must not: bump `schema_version` beyond `1` for any diarized or non-diarized output (INV-10).
- Must not: emit `"speaker": null` in any segment dict — omit the key entirely when `None`.
- Must not: write `HF_TOKEN` (or any part of it) to logs, transcripts, JSON output, or any
  printed command output (INV-7).
- Must not: import whisperX or pyannote at module load time (lazy import required).
- Must not: declare torch, torchaudio, or pyannote as direct `[diarize]` dependencies in
  `pyproject.toml` (transitive only — direct pins create a conflict surface with whisperX's
  own tight pins).

### Assumptions

- Assumes: DDR-02 is merged to `main` and `Backend` Protocol, `Capabilities`, and `schema_version: 1`
  are live before this sprint's build branch is cut.
- Assumes: the operator deploying with `backend=diarize` has accepted the pyannote model ToS on
  HuggingFace independently; the repo carries no responsibility for ToS enforcement.
- Assumes: the pyannote `speaker-diarization-3.1` model is the target; whisperX's default
  `DiarizationPipeline` selects it.
- Assumes: `WHISPER_DEVICE` (existing `Config` field) is reused for both the whisperX transcription
  model and the pyannote pipeline; no new device config field is needed.
- Assumes: `WHISPER_MODEL` (existing `Config.model_size` field) is reused for the whisperX
  transcription stage model size.
- Assumes: the CI smoke job for `diarize_smoke` runs only via `workflow_dispatch` with a manually
  configured `HF_TOKEN` secret — not on every push.
- Assumes: whisperX 3.8.6 is the verified minimum; the exact upper bound (`<4.0`) is confirmed
  during the sprint and pinned in `pyproject.toml` before merge.
- Assumes: `triton>=3.3.0` (whisperX transitive dep) is Linux x86_64 only; the Windows ASUS ROG
  deployment may require a separate install path not covered by this spec.
