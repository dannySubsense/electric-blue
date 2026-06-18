# DDR-05 — WhisperX Speaker Diarization Backend

- **Status:** ACCEPTED — locked 2026-06-18 (Danny)
- **Author:** reed
- **Date:** 2026-06-14
- **Sprint (on approval):** `whisperx-diarization`
- **Depends on:** DDR-02 (backend seam + `Backend` Protocol, `base.py`, `Capabilities`, `schema_version`) — must be merged first
- **Blocks:** —
- **Supersedes:** —

---

## Sprint Decisions — LOCKED 2026-06-18 (Danny)

All D-flags from the Open Questions section are resolved. These are locked; do not reopen.

- **D1 = whisperX end-to-end** — transcribe → align → diarize → assign via the `whisperx`
  library. Backend registered as `"diarize"`. Option B (pyannote-direct) deferred as a future
  alternative.
- **D2 = segment-level speaker assignment for v1** — one `speaker` label per `Segment`; word-level
  deferred to a future DDR.
- **D3b = omit `speaker` key when `None`** — `to_dict()` omits the key entirely when no diarization
  was run; does not emit `"speaker": null`.
- **D3c = no speaker prefix in TXT** — speaker labels appear in JSON/SRT/VTT only; plain TXT is
  unchanged.
- **D3d = majority-speaker label for mid-cue** — a subtitle cue spanning two speakers is labelled
  with the majority speaker; cue-splitting deferred.
- **D4 = strictly opt-in** — `[diarize]` extra required; `HF_TOKEN` env var required; README must
  direct users to accept pyannote model ToS on HuggingFace before use. No ToS burden on the repo.
- **D5 = CPU is the primary deployment target** — R630 (always-on Linux server, CPU-only) is the
  production host. Batch/overnight latency is acceptable. No GPU warnings or GPU-first assumptions.
- **D6 = auto-detect + fixed count only** — expose `WHISPER_DIARIZE_NUM_SPEAKERS` for fixed count;
  auto-detect when unset. `min_speakers`/`max_speakers` deferred to a future DDR.
- **D7 = pin whisperX release** — `whisperx>=3.8.6,<4.0` in `[diarize]` extra (or nearest
  verified available release — confirm against PyPI at sprint start); torch/pyannote are
  transitive dependencies, not re-declared.
- **Startup validation** — `ConfigurationError` for missing `HF_TOKEN` is raised at backend
  instantiation (service startup), not at first `transcribe()` call.

---

## Context

The README "Optional next steps" names speaker diarization as the highest-value next capability.
The gap: today all transcripts are speaker-blind. A 90-minute meeting produces one wall of text;
downstream consumers (search, summarization, note-takers) have no way to attribute speech.

DDR-02 was designed explicitly anticipating this sprint. It added:
- the `Backend` Protocol with `capabilities.supports_diarization` flag
- `schema_version` in JSON output (starting at 1)
- a principle that speaker fields stay optional/additive, so the schema evolution happens without
  breaking existing consumers

This DDR delivers on that anticipation: a new `backends/whisperx.py` that implements the DDR-02
`Backend` seam, runs a transcribe → align → diarize → assign-speakers pipeline, and forces the
first schema evolution. It is the heaviest and riskiest feature in the current backlog. The
existing `local` and `api` backends must not change.

---

## Principle

Implement diarization as a self-contained optional backend — not as a mode flag bolted onto the
local backend — so the complexity is isolated and the base install remains light. Accept that
this backend is GPU-preferred and has a non-trivial auth/licensing setup; document honestly and
fail clearly when prerequisites are absent rather than degrading silently.

---

## Decision

### 1. Backend location and seam

New file: `src/electric_blue/backends/whisperx.py`.

Implements the `Backend` Protocol defined in DDR-02 `backends/base.py`:

```python
class WhisperXBackend:
    name = "whisperx"
    capabilities = Capabilities(
        is_async=False,
        supports_diarization=True,
        needs_network=False,       # after model cache is populated
        needs_gpu_recommended=True,
        max_upload_mb=None,
    )

    def transcribe(self, cfg: Config, src: Path) -> Transcript: ...
```

`backends/__init__.py` registry gains `"whisperx": WhisperXBackend`. No other backend file
changes. The seam is DDR-02's; this sprint plugs into it.

### 2. Pipeline

Four sequential stages — each is a discrete unit that can be mocked independently in tests:

**Stage 1 — Transcription.**
`whisperx.load_model(cfg.model_size, cfg.device)` + `model.transcribe(audio)`.
Produces raw segments with approximate word timestamps. This is Whisper transcription through
the whisperX wrapper rather than faster-whisper. (FLAG D1 — see below for the alternative that
reuses `local.py`'s faster-whisper model instead of whisperx's transcription.)

**Stage 2 — Word alignment.**
`whisperx.load_align_model(language_code, device)` + `whisperx.align(segments, ...)`.
Produces tighter per-word timestamps needed for accurate speaker boundary assignment. Alignment
model is language-specific and downloads on first use (small, not gated).

**Stage 3 — Diarization.**
`whisperx.DiarizationPipeline(use_auth_token=cfg.hf_token, device=device)`.
Wraps `pyannote/speaker-diarization-3.1` (or 3.x latest). Produces a turn-taking annotation:
`(start, end, speaker_label)` tuples. Accepts optional `num_speakers` or `min_speakers` /
`max_speakers` hints (see §5).

**Stage 4 — Speaker assignment.**
`whisperx.assign_word_speakers(diarize_segments, aligned_result)`.
Maps diarization turns onto word/segment boundaries, annotating each segment (and optionally
each word) with a speaker label such as `SPEAKER_00`, `SPEAKER_01`, ...

The method returns the full `list[Segment]` and a `TranscriptInfo` with
`backend = "whisperx:<model_size>"`. At Stage 3, if `cfg.hf_token` is empty, raise a
`ConfigurationError` with a clear message directing the user to the HF token setup docs;
do not import pyannote until the method is called (lazy import, same pattern as `local.py`'s
`WhisperModel`).

### 3. Output schema evolution

DDR-02 §4 reserved this moment. The changes are additive and backward-compatible.

**`models.py` — `Segment`:**

```python
@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None          # NEW — None when no diarization was run

    def to_dict(self) -> dict:
        d = {"start": self.start, "end": self.end, "text": self.text}
        if self.speaker is not None:
            d["speaker"] = self.speaker  # omitted from dict when absent (FLAG D3)
        return d
```

Existing `local` and `api` backends instantiate `Segment` without `speaker`; the default
`None` means `to_dict()` produces the same dict they produce today. No existing test changes.

**`schema_version` — RESOLVED by DDR-02 D4 (Danny review, 2026-06-14): stays at `1`.**
~~JSON output adds `"schema_version": 2` when at least one segment carries a speaker label.~~
The earlier "bump to 2" proposal is **overridden**: `speaker` is an *optional, additive* field,
and adding an optional field is not a breaking change. **All diarized output remains
`schema_version: 1`** — the version tracks schema *shape*, not file *content* (no "v2
sometimes"). FLAG D3's schema-version sub-question is therefore closed; only the rendering
sub-questions (txt/srt/vtt) remain open for the DDR-05 spec session.

**`outputs.py` — speaker rendering:**

```
txt:   Plain text unchanged (speaker labels are in JSON/srt/vtt).  (FLAG D3)
srt:   Cue text prefixed: "[SPEAKER_01] the spoken text"
vtt:   Cue text prefixed: "[SPEAKER_01] the spoken text"
json:  "speaker" key present on each segment when non-null; schema_version: 1 (additive)
```

`write_outputs` detects diarization by checking `any(s.speaker for s in segments)`. When
false, rendering is identical to today. When true, srt/vtt writers prepend the speaker tag to
`s.text`. The caller (watcher/CLI) passes the same `segments` list regardless; outputs.py
handles the conditional rendering internally. No new parameter to `write_outputs` signature.

Word-level speaker data (if retained from Stage 4) is not rendered in subtitle formats in
this sprint — it is available on `TranscriptInfo` or a separate field for future use.
(FLAG D2 — whether to carry word-level speaker data through at all.)

### 4. Dependencies and optional extra

The diarization stack is large (~2–4 GB on disk including model weights) and has a complex
torch/transformers version matrix. It must not bloat the base install.

Proposed `pyproject.toml` addition:

```toml
[project.optional-dependencies]
diarize = [
    "whisperx>=3.1",          # FLAG D7 — see notes on version pinning
    "pyannote.audio>=3.1",
    "torch>=2.0",             # whisperx and pyannote share a torch requirement
]
```

Install path: `pip install "electric-blue[diarize]"`. The base install (`watchdog`,
`requests`) and the `[local]` extra (`faster-whisper`) are untouched.

**Version pinning concern:** `whisperx` has historically required specific `torch` and
`transformers` versions and is not always current on PyPI. Its `pyproject.toml` pins are
sometimes aggressive. The `[local]` extra (`faster-whisper`) also pulls torch on CUDA
systems. These two may conflict. (FLAG D7 — this is the biggest dependency risk; see also
the alternative approach in D1 that avoids whisperx entirely.)

> **✅ FINDING (externals pass, 2026-06-14) — VIABLE but RISKY; three hard constraints.**
> Researched whisperx **3.8.6** (`pyproject.toml` on `main`): `requires-python >=3.10,<3.14`
> (matches our CI), `torch~=2.8.0` (tight), `torchaudio~=2.8.0`, `faster-whisper>=1.2.0`,
> `pyannote-audio>=4.0.0`, `numpy>=2.1.0`, `triton>=3.3.0` (**Linux x86_64 only**).
> - **Co-install `[local,diarize]` RESOLVES.** `[local]` is `faster-whisper>=1.0`; whisperx tightens
>   to `>=1.2.0` (compatible). `faster-whisper` uses **ctranslate2, not torch** — so whisperx's
>   `torch~=2.8.0` is the sole torch pin, no cross-extra conflict.
> - **Constraint 1 — pyannote models are GATED.** `pyannote/speaker-diarization-3.1` + its
>   `segmentation-3.0` dep require an **HF token AND manual per-account license click-through** (not
>   pip-automatable). Deployment/CI needs `HF_TOKEN` injected. (A newer CC-BY `community-1` model
>   exists but whisperx's default pipeline still calls the gated 3.1 unless overridden.) This
>   matches the DDR's own `hf_token`/`ConfigurationError` design — keep it.
> - **Constraint 2 — GPU-required.** Diarization (pyannote) is impractically slow on CPU → the
>   **CPU-only R630 cannot host it; only the ASUS ROG / 4090 can.** Diarization is a
>   **host-conditional** feature, not a universal pipeline step. Reflect in deployment docs.
> - **Constraint 3 — `torch~=2.8.0` tight pin.** A torch 2.9 release breaks `[diarize]` until
>   whisperx updates (maintainers have yanked versions over torch mismatches). Track whisperx releases.
> - **Recommended `[diarize]`:** just `whisperx>=3.8.6,<4.0` (it pulls torch/pyannote transitively —
>   do NOT re-declare them; replaces the proposed `whisperx>=3.1`/`pyannote.audio>=3.1`/`torch>=2.0`).
> - **INV-13 (reproducibility):** bump `[local]` to `faster-whisper>=1.2.0,<2.0`; leave torch
>   transitive (faster-whisper doesn't use it); if gate/smoke need a pinned torch, put it in dev deps.
> Sources: whisperx PyPI 3.8.6 + GitHub `pyproject.toml`; faster-whisper 1.2.1; pyannote 3.1 HF model
> card; whisperX issues #973/#1241/#1051/#542. Dependency facts HIGH confidence; py3.12+torch2.8 edge
> cases MEDIUM.

### 5. Configuration

New fields added to `Config` (all read in `Config.from_env()`):

```python
# WhisperX / diarization backend
hf_token: str                    # HF_TOKEN env var; default ""
diarize_num_speakers: int | None # WHISPER_DIARIZE_NUM_SPEAKERS; default None (auto)
diarize_min_speakers: int | None # WHISPER_DIARIZE_MIN_SPEAKERS; default None
diarize_max_speakers: int | None # WHISPER_DIARIZE_MAX_SPEAKERS; default None
```

`backend` comment in `Config` gains `"whisperx"` as a valid value.

At runtime: if `diarize_num_speakers` is set, it is passed as the sole hint to pyannote
(most accurate when known). If `min`/`max` are set without a fixed count, both bounds are
passed. If none are set, pyannote runs in auto-detect mode. Setting both `num_speakers` and
`min/max` is a configuration error caught at startup. (FLAG D6 — whether all three modes
need to be exposed now, or just auto + fixed count for v1.)

`WHISPER_DEVICE` (already on `Config`) is reused for both the whisperx transcription model
and the pyannote diarization pipeline. If the device is `"auto"`, the same cuda-or-cpu
fallback logic from `local.py` applies.

### 6. Auth, licensing, and HF token handling

**The gated model situation:** `pyannote/speaker-diarization-3.1` and related pyannote models
on Hugging Face require the user to:
1. Create a Hugging Face account.
2. Visit each model card and click "Accept" on the model's terms of use.
3. Generate an HF access token (read-only is sufficient).

These are per-model ToS clicks, not a license incorporated into this project. However, using
this backend in a deployed system means the operator has accepted those terms, and the terms
prohibit certain commercial uses. This is a **public MIT-licensed repo** — the implications
need explicit sign-off. (FLAG D4.)

**Token handling:**
- `HF_TOKEN` is read from environment only, never hardcoded, never committed.
- `.gitignore`, `README.md`, and `docs/` must explicitly warn: "never commit HF_TOKEN".
- If `backend=whisperx` and `hf_token=""`: raise `ConfigurationError` at startup (not at
  first file drop), with a message linking to setup docs.
- No token caching to disk by this code (pyannote's own model cache is in `~/.cache/huggingface`
  and is the user's responsibility).
- CI: the diarize smoke test is gated on `HF_TOKEN` being set in the environment; it is marked
  `@pytest.mark.diarize_smoke` and skipped with `pytest.skip("HF_TOKEN not set")` when absent.
  The standard gate (`make gate`) never touches HF.

### 7. Tests

**Hermetic (run in `make gate`, no models, no HF token):**

`tests/test_whisperx_pipeline.py`:
- `FakeDiarizer`: returns synthetic annotation `[(0.0, 2.5, "SPEAKER_00"), (2.5, 5.0, "SPEAKER_01")]`
- `FakeAlignedResult`: dict matching whisperx's `align()` output shape
- Test speaker assignment: given synthetic aligned segments + fake diarizer annotation, assert
  `segment.speaker` populated correctly on the correct time ranges
- Test boundary edge cases: segment that spans a speaker transition — assert the majority-time
  speaker wins (or the first, if word-level — flag which rule)
- Test `ConfigurationError` raised when `hf_token=""` and `backend="whisperx"`

`tests/test_outputs.py` (extend existing):
- Add fixture: `segments_with_speakers` — list of `Segment` instances with `speaker` set
- Assert SRT output contains `[SPEAKER_00]` prefix on the correct cue
- Assert VTT output contains `[SPEAKER_01]` prefix on the correct cue
- Assert JSON output contains `"speaker": "SPEAKER_00"` on diarized segments; `schema_version: 1`
- Assert JSON output for non-diarized segments (speaker=None): no `"speaker"` key in dict;
  `schema_version: 1` (additive field; version unchanged whether or not speakers are present)
- Assert TXT output is unchanged (plain text, no speaker prefix) — or test the flagged alternative

**Opt-in smoke (`@pytest.mark.diarize_smoke`):**

`tests/test_smoke_diarize.py`:
- Skips if `HF_TOKEN` not in environment or if `[diarize]` extra is not installed
- Generates a minimal synthetic WAV with ffmpeg (two distinct audio segments — silence gap
  simulates speaker turn; real speaker separation is not required for the smoke, just that the
  pipeline runs end-to-end without crashing)
- Asserts: `TranscriptInfo.backend == "whisperx:<model>"`, at least one segment returned,
  JSON output written, `schema_version` field present
- Does NOT assert speaker label accuracy (that would require validated multi-speaker audio)
- Run command: `pytest -m diarize_smoke` (separate from `make smoke`)

---

## Sequencing (within the sprint)

1. DDR-02 must be in `main` (backend seam, `base.py`, `Capabilities`, `schema_version: 1`).
2. Add `Config` fields (`hf_token`, `diarize_*`) and `[diarize]` extra — no behavior change.
3. Write hermetic tests first (mock pipeline, speaker assignment, output rendering) — all green
   before any real backend code.
4. Add `speaker: str | None = None` to `Segment`; update `to_dict()`; update `outputs.py`
   speaker rendering. Hermetic tests drive the implementation.
5. Implement `backends/whisperx.py` — four pipeline stages, lazy imports, `ConfigurationError`
   on missing token.
6. Register `"whisperx"` in backend registry (`backends/__init__.py`).
7. Frank gate: all hermetic tests green, no existing test regressions.
8. Write `test_smoke_diarize.py` — marked `diarize_smoke`, skip-safe.
9. Update README (new backend table row, HF token setup section, `[diarize]` install path,
   GPU recommendation, ToS callout).

## Risks

- **Dependency version hell.** `whisperx` has a history of pinning torch/transformers aggressively
  and lagging PyPI. The `[local]` extra (faster-whisper) and `[diarize]` (whisperx + pyannote)
  may pull conflicting torch builds. This is the highest-probability failure mode. Mitigation:
  test the combined install in CI (a dry `pip install ".[local,diarize]"` step); if they
  conflict, the D1 alternative (pyannote-direct on faster-whisper) avoids this entirely.

- **HF gated model ToS.** The pyannote models have non-trivial terms. Using this backend in
  production means the operator has accepted those terms. The public repo documents this but
  cannot enforce it. Mitigation: prominent README callout; the token is opt-in; CI never
  downloads the gated model.

- **GPU memory.** Running a large Whisper model (large-v3) and the pyannote diarization pipeline
  simultaneously on one GPU requires ~6–10 GB VRAM. The ASUS 4090 (24 GB) is not at risk.
  Smaller VRAM budgets need model quantization or sequential unloading (out of scope this sprint).

- **CI model download.** The diarization models are 1–3 GB. If the smoke ever runs in standard
  CI it will be slow and incur HF rate-limit risk. Mitigation: `diarize_smoke` is a separate
  pytest mark, excluded from the CI `lint-test` matrix, and run only via `workflow_dispatch`
  with a manually configured `HF_TOKEN` secret — not on every push.

- **Accuracy claims.** Speaker diarization degrades noticeably with >6 speakers, overlapping
  speech, noisy recording conditions, and non-English audio with limited pyannote training data.
  The backend should not be presented as universally reliable. README must set expectations.

- **`Segment` dataclass change.** Adding `speaker: str | None = None` is backward-compatible
  in Python (keyword arg with default). However, any code that constructs `Segment` positionally
  with three args is unaffected. Confirm no such call sites exist outside tests before landing.

## Open questions / DECISIONS TO FLAG (resolve with Danny, do not block drafting)

- **D1 — whisperx-as-transcriber vs pyannote-direct.**
  Option A: Use `whisperx` for all four pipeline stages (transcribe → align → diarize → assign).
  This is the documented "whisperx way" and gives word-level alignment. Downside: adds a large
  dependency with a fragile torch version matrix; duplicates transcription capability already in
  `local.py`.
  Option B: Reuse `local.py`'s faster-whisper for transcription (Stage 1), skip whisperx word
  alignment (Stage 2), run `pyannote.audio` directly for diarization (Stage 3), and hand-write
  segment-level speaker assignment by matching pyannote turn annotations to segment time ranges
  (Stage 4). Avoids `whisperx` as a dependency entirely; simpler torch story; loses word-level
  boundary accuracy. The backend name would more honestly be `"diarize"` not `"whisperx"`.
  **DECISION — which approach, and does the name matter?**

- **D2 — Segment-level vs word-level speaker assignment.**
  Segment-level: each `Segment` carries one speaker label (the dominant speaker in that time
  window). Simple to render; inaccurate when a speaker change happens mid-segment.
  Word-level: each word carries a speaker label; segment label is derived from the majority word.
  More accurate for boundary cases; significantly more complex to serialize (word list on each
  segment in JSON; subtitle rendering needs a strategy for mid-cue speaker changes).
  If D1 chooses Option A (whisperx), word-level data is available for free. If D1 chooses
  Option B, word-level is not available without extra work.
  **DECISION — segment-level only for v1, or word-level from day one?**

- **D3 — Exact schema change and rendering.**
  (a) `schema_version` value when diarization is present: **RESOLVED by DDR-02 D4 — keep `1`;
  `speaker` is a purely additive optional field, no bump.** (Closed; not re-litigated here.)
  (b) When `speaker is None`, should `to_dict()` omit the key entirely (current proposal) or
  emit `"speaker": null`? Omitting is cleaner for existing consumers; null is more explicit
  about the field's existence.
  (c) TXT rendering: no speaker prefix (current proposal, speakers only in structured formats),
  or `SPEAKER_00: the spoken text` per speaker run? Mixed-speaker TXT with inline attribution
  is more useful but changes the TXT format for diarized output.
  (d) SRT/VTT speaker change mid-cue: if word-level is adopted (D2), a single subtitle cue
  may span two speakers. Split cue on speaker boundary, or prefix with the first speaker, or
  leave as the majority speaker label?
  **DECISION — all four sub-points.**

- **D4 — HF token handling and gated-model ToS acceptability.**
  The pyannote gated models require per-user ToS acceptance on HuggingFace and prohibit some
  commercial uses. Options:
  (a) Strictly opt-in and documented: the backend is disabled by default, requires `[diarize]`
  install + HF_TOKEN, and README prominently directs users to accept model terms before using
  it. The public repo carries no ToS burden itself.
  (b) Same as (a) but also explore whether pyannote offers a non-gated model or self-hosted
  path that would remove the per-user ToS requirement.
  (c) Evaluate NeMo or another diarizer that has a less restrictive license as the primary
  diarization backend, with pyannote as a documented alternative.
  Is "opt-in + document the ToS" sufficient, or does this need a legal/licensing review before
  the feature ships? **DECISION.**

- **D5 — CPU feasibility vs GPU-only targeting.**
  The ASUS box (RTX 4090, 24 GB VRAM) is the natural production host. The R630 (CPU-only) can
  technically run this pipeline but expect 15–60x real-time factor on a large model — an hour
  of audio could take 4+ hours. Options:
  (a) Advertise as GPU-strongly-recommended; warn at runtime if device resolves to CPU;
  allow it to run anyway (the user decided).
  (b) Refuse to run on CPU (hard error if `device == "cpu"` for this backend).
  (c) Offer a reduced "CPU diarization" mode with a smaller model.
  For homelab routing: should the watcher/CLI have a backend-routing hint ("if file > Xmin,
  route to the 4090 host")?  That is out of scope for this DDR but worth flagging as a
  follow-on. **DECISION — CPU behavior.**

- **D6 — Number-of-speakers configuration model.**
  pyannote supports three modes: auto-detect (no hint), fixed `num_speakers`, or
  `min_speakers`/`max_speakers` bounds. All three are exposed in the proposed Config. However,
  exposing all three via env vars creates a validation surface (what if both `num_speakers` and
  `min_speakers` are set?). For v1: expose only auto (no env vars) and fixed count
  (`WHISPER_DIARIZE_NUM_SPEAKERS`), and leave `min`/`max` for a future DDR? Or all three now?
  **DECISION.**

- **D7 — Dependency weight and whisperx version pinning.**
  `whisperx` on PyPI has had periods of being stale relative to its GitHub HEAD. If the PyPI
  package is too old to work with current pyannote/torch, we may need to pin to a git ref
  in pyproject.toml (unusual and fragile for a published package). Alternatively, if D1 chooses
  Option B (pyannote-direct), `whisperx` is dropped entirely and this risk evaporates.
  If Option A is chosen: should we pin a specific `whisperx` release, accept the PyPI latest,
  or vendor the alignment/assignment code? **DECISION.**
