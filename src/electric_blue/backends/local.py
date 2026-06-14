"""Local faster-whisper backend."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from ..audio import extract
from ..config import Config
from ..models import Segment, TranscriptInfo
from .base import Capabilities, Transcript

log = logging.getLogger("electric_blue")

_model = None


def _get_model(cfg: Config):
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        dev, comp = cfg.device, cfg.compute_type
        if dev == "auto":
            try:
                import torch

                dev = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                dev = "cpu"
        if comp == "auto":
            comp = "float16" if dev == "cuda" else "int8"
        log.info("Loading %s on %s (%s)...", cfg.model_size, dev, comp)
        _model = WhisperModel(cfg.model_size, device=dev, compute_type=comp)
    return _model


class LocalBackend:
    name: str = "local"
    capabilities: Capabilities = Capabilities(
        supports_diarization=False,
        max_upload_mb=None,
        needs_network=False,
        needs_gpu_recommended=True,
    )

    def transcribe(self, cfg: Config, src: Path) -> Transcript:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "a.wav"
            extract(cfg, src, wav, compressed=False)
            model = _get_model(cfg)
            seg_gen, info = model.transcribe(
                str(wav),
                language=cfg.language,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            segments = [Segment(start=s.start, end=s.end, text=s.text.strip()) for s in seg_gen]
        transcript_info = TranscriptInfo(
            language=info.language,
            language_probability=round(info.language_probability, 3),
            duration=round(info.duration, 2),
            backend=f"local:{cfg.model_size}",
        )
        return Transcript(segments=segments, info=transcript_info)
