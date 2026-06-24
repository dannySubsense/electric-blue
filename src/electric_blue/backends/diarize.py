"""WhisperX diarization backend — four-stage pipeline (transcribe → align → diarize → assign)."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from ..audio import extract
from ..config import Config
from ..exceptions import ConfigurationError
from ..models import Segment, TranscriptInfo
from .base import Capabilities, Transcript

log = logging.getLogger("electric_blue")

# Module-level whisperx cache — populated lazily on the first transcribe() call.
# Gate tests clear this via monkeypatch.setattr and pre-populate sys.modules["whisperx"]
# so _get_whisperx() picks up the fake module without a real whisperx installation.
_whisperx = None


def _get_whisperx():
    """Return the whisperx module, importing it on first call.

    Subsequent calls return the cached module object with no import overhead.
    Raises ImportError naturally if the [diarize] extra is not installed — the
    error propagates to watcher.handle() which routes the file to failed/.

    Note: DiarizationPipeline is NOT on the top-level whisperx namespace in
    v3.8.6; import it directly via ``from whisperx.diarize import
    DiarizationPipeline`` inside transcribe().
    """
    global _whisperx
    if _whisperx is None:
        import whisperx

        _whisperx = whisperx
    return _whisperx


def _resolve_device(cfg: Config) -> str:
    """Return the effective device string ("cuda" | "cpu").

    Mirrors local.py: when cfg.device is "auto", probe torch.cuda.is_available();
    fall back to "cpu" on ImportError or any other exception (covers CPU-only
    installs where torch is absent or CUDA is unavailable).
    CPU is a valid first-class target; no warning is emitted (D5).
    """
    if cfg.device != "auto":
        return cfg.device
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _resolve_compute(cfg: Config) -> str:
    """Return the effective compute_type string.

    Returns cfg.compute_type unchanged unless it is "auto", in which case
    returns "int8" — the CPU-safe default (D5; int8 is whisperX's recommended
    compute type for CPU inference).
    """
    if cfg.compute_type != "auto":
        return cfg.compute_type
    return "int8"


def _assign_majority_speaker(segment_dict: dict) -> str | None:
    """Return the majority-time speaker label for a whisperX segment dict.

    Strategy (in order):
    1. If the segment dict has a top-level "speaker" key, return it directly.
       whisperX may populate this when word-level data is present.
    2. Otherwise, sum elapsed duration per speaker across the "words" list
       using each word's "start"/"end" interval and "speaker" label.
    3. Return the speaker with the greatest accumulated duration.
    4. Tie-break: alphabetically first speaker label (e.g. SPEAKER_00 beats
       SPEAKER_01). This is deterministic and documented here per spec.
    5. If no words carry speaker data and no segment-level "speaker" key exists,
       return None.
    """
    # Step 1: fast path — segment-level speaker key already set by whisperX
    if "speaker" in segment_dict:
        return segment_dict["speaker"]

    # Steps 2–4: aggregate per-speaker word durations
    durations: dict[str, float] = {}
    for word in segment_dict.get("words", []):
        if not word:
            continue
        speaker = word.get("speaker")
        if not speaker:
            continue
        start = word.get("start")
        end = word.get("end")
        if start is None or end is None:
            continue
        try:
            durations[speaker] = durations.get(speaker, 0.0) + (float(end) - float(start))
        except (TypeError, ValueError):
            continue

    if not durations:
        return None  # Step 5: no usable speaker data

    # Step 3 + 4: descending duration; alphabetically first label on tie
    return sorted(durations.keys(), key=lambda s: (-durations[s], s))[0]


class WhisperXBackend:
    """whisperX diarization backend.

    Implements the four-stage pipeline: transcribe → align → diarize → assign.
    Conforms to the Backend Protocol structurally (no inheritance required).
    Not registered in _REGISTRY — registered in _FACTORIES (S7) so it is
    constructed on demand with cfg and never pre-instantiated at import time.
    """

    name: str = "diarize"
    capabilities: Capabilities = Capabilities(
        supports_diarization=True,
        max_upload_mb=None,
        needs_network=False,
        needs_gpu_recommended=True,
        is_async=False,
    )

    def __init__(self, cfg: Config) -> None:
        """Validate HF_TOKEN presence at construction time.

        Called by get_backend(cfg) when cfg.backend == "diarize". The watcher
        calls get_backend() as the first statement of run_watch(), before the
        watch loop, so this check fires at service startup — the operator learns
        of broken config immediately, not when the first file drops.

        whisperx is NOT imported here. The guard fires before any lazy import
        so test_no_whisperx_import_before_hf_guard can assert "whisperx" is not
        in sys.modules after ConfigurationError is raised.

        Raises:
            ConfigurationError: if cfg.hf_token is absent or empty.
        """
        if not cfg.hf_token:
            raise ConfigurationError(
                "HF_TOKEN is required for the diarize backend. "
                "Accept the pyannote speaker-diarization model Terms of Service at "
                "https://huggingface.co/pyannote/speaker-diarization-3.1 "
                "then set the HF_TOKEN environment variable to your HuggingFace access token."
            )

    def transcribe(self, cfg: Config, src: Path) -> Transcript:
        """Execute the four-stage whisperX pipeline on src.

        Raises:
            ImportError: if [diarize] extra is not installed (lazy import fails).
            OSError / EnvironmentError: if the pyannote model ToS has not been
                accepted on HuggingFace (propagates from DiarizationPipeline;
                not suppressed).
        """
        # Step 1: resolve device
        device = _resolve_device(cfg)

        with tempfile.TemporaryDirectory() as tmp:
            # Step 2: extract audio to temp WAV
            wav = Path(tmp) / "a.wav"
            extract(cfg, src, wav, compressed=False)

            # Step 3: lazy import
            wx = _get_whisperx()

            # Step 4 — Stage 1: Transcription
            audio_array = wx.load_audio(str(wav))
            model = wx.load_model(cfg.model_size, device, compute_type=_resolve_compute(cfg))
            result = model.transcribe(audio_array, language=cfg.language or None, batch_size=16)
            language = result["language"]

            # Step 5 — Stage 2: Alignment
            align_model, metadata = wx.load_align_model(language_code=language, device=device)
            result = wx.align(result["segments"], align_model, metadata, audio_array, device)

            # Step 6 — Stage 3: Diarization
            diarize_kwargs: dict = {}
            if cfg.diarize_num_speakers is not None:
                diarize_kwargs["num_speakers"] = cfg.diarize_num_speakers
            from whisperx.diarize import DiarizationPipeline

            diarize_pipeline = DiarizationPipeline(
                model_name=None, token=cfg.hf_token, device=device
            )
            diarize_segments = diarize_pipeline(audio_array, **diarize_kwargs)

            # Step 7 — Stage 4: Speaker assignment
            result = wx.assign_word_speakers(diarize_segments, result)

            # Step 8: Convert to Segment list
            segments = [
                Segment(
                    start=s["start"],
                    end=s["end"],
                    text=s.get("text", "").strip(),
                    speaker=_assign_majority_speaker(s),
                )
                for s in result["segments"]
            ]

        # Step 9: Build TranscriptInfo
        info = TranscriptInfo(
            language=language,
            language_probability=None,
            duration=round(
                float(result.get("duration", segments[-1].end if segments else 0.0)),
                2,
            ),
            backend=f"diarize:{cfg.model_size}",
        )

        # Step 10: Return
        return Transcript(segments=segments, info=info)
