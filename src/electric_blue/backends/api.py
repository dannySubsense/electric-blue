"""OpenAI-compatible API backend."""

from __future__ import annotations

import tempfile
from pathlib import Path

import requests

from ..audio import extract
from ..config import Config
from ..models import Segment, TranscriptInfo
from .base import Capabilities, Transcript


class ApiBackend:
    name: str = "api"
    capabilities: Capabilities = Capabilities(
        supports_diarization=False,
        max_upload_mb=24,  # SI megabytes (1e6 bytes); matches cfg.api_max_mb default
        needs_network=True,
        needs_gpu_recommended=False,
        is_async=False,
    )

    def transcribe(self, cfg: Config, src: Path) -> Transcript:
        if not cfg.api_key:
            raise RuntimeError("WHISPER_API_KEY is not set for the api backend.")
        with tempfile.TemporaryDirectory() as tmp:
            mp3 = Path(tmp) / "a.mp3"
            extract(cfg, src, mp3, compressed=True)
            size_mb = mp3.stat().st_size / 1e6
            if size_mb > cfg.api_max_mb:
                raise RuntimeError(
                    f"{src.name}: encoded audio is {size_mb:.0f} MB (> {cfg.api_max_mb} MB cap). "
                    f"Route this one to the local/batch folder, or chunk it."
                )
            data: dict = {
                "model": cfg.api_model,
                "response_format": "verbose_json",
                "timestamp_granularities[]": "segment",
            }
            if cfg.language:
                data["language"] = cfg.language
            with open(mp3, "rb") as fh:
                r = requests.post(
                    f"{cfg.api_base_url}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {cfg.api_key}"},
                    data=data,
                    files={"file": ("a.mp3", fh, "audio/mpeg")},
                    timeout=600,
                )
            r.raise_for_status()
            payload = r.json()

        segs = payload.get("segments") or []
        segments = [
            Segment(
                start=s.get("start", 0.0),
                end=s.get("end", 0.0),
                text=(s.get("text") or "").strip(),
            )
            for s in segs
        ]
        if not segments and payload.get("text"):
            segments = [
                Segment(
                    start=0.0,
                    end=float(payload.get("duration", 0.0)),
                    text=payload["text"].strip(),
                )
            ]
        info = TranscriptInfo(
            language=payload.get("language", cfg.language or "unknown"),
            language_probability=None,
            duration=round(float(payload.get("duration", 0.0)), 2),
            backend=f"api:{cfg.api_model}",
        )
        return Transcript(segments=segments, info=info)
