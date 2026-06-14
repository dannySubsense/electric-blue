"""Frozen configuration dataclass — reads environment variables at construction time."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    # Directories
    base_dir: Path
    input_dir: Path
    output_dir: Path
    done_dir: Path
    failed_dir: Path

    # Backend selection
    backend: str  # "local" | "api"
    language: str | None

    # Local backend
    model_size: str
    device: str
    compute_type: str

    # API backend
    api_base_url: str
    api_model: str
    api_key: str

    # Notifications
    notify_webhook: str

    # FFmpeg
    ffmpeg_bin: str

    # Constants (carried on Config for threading; not env-configurable)
    output_formats: frozenset
    media_exts: frozenset
    api_max_mb: int
    api_bitrate: str
    stability_seconds: float
    poll_interval: float

    @classmethod
    def from_env(cls) -> Config:
        base_dir = Path(os.environ.get("TRANSCRIBE_BASE", Path.home() / "transcribe"))
        input_dir = Path(os.environ.get("TRANSCRIBE_INPUT", base_dir / "inbox"))
        output_dir = Path(os.environ.get("TRANSCRIBE_OUTPUT", base_dir / "transcripts"))
        done_dir = Path(os.environ.get("TRANSCRIBE_DONE", base_dir / "done"))
        failed_dir = Path(os.environ.get("TRANSCRIBE_FAILED", base_dir / "failed"))

        language_raw = os.environ.get("WHISPER_LANG") or None

        return cls(
            base_dir=base_dir,
            input_dir=input_dir,
            output_dir=output_dir,
            done_dir=done_dir,
            failed_dir=failed_dir,
            backend=os.environ.get("WHISPER_BACKEND", "local").lower(),
            language=language_raw,
            model_size=os.environ.get("WHISPER_MODEL", "distil-large-v3"),
            device=os.environ.get("WHISPER_DEVICE", "auto"),
            compute_type=os.environ.get("WHISPER_COMPUTE", "auto"),
            api_base_url=os.environ.get("WHISPER_API_BASE", "https://api.groq.com/openai/v1"),
            api_model=os.environ.get("WHISPER_API_MODEL", "whisper-large-v3-turbo"),
            api_key=os.environ.get("WHISPER_API_KEY", ""),
            notify_webhook=os.environ.get("NOTIFY_WEBHOOK", ""),
            ffmpeg_bin=os.environ.get("FFMPEG_BIN", "ffmpeg"),
            output_formats=frozenset({"txt", "srt", "vtt", "json"}),
            media_exts=frozenset(
                {
                    ".mp4",
                    ".mov",
                    ".mkv",
                    ".avi",
                    ".webm",
                    ".m4v",
                    ".wmv",
                    ".flv",
                    ".mp3",
                    ".wav",
                    ".m4a",
                    ".aac",
                    ".flac",
                    ".ogg",
                    ".opus",
                    ".wma",
                }
            ),
            api_max_mb=24,
            api_bitrate="64k",
            stability_seconds=2.0,
            poll_interval=1.0,
        )
