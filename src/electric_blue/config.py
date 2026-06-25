"""Frozen configuration dataclass — reads environment variables at construction time."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .exceptions import ConfigurationError


def _parse_diarize_num_speakers(raw: str | None) -> int | None:
    """Parse and validate the WHISPER_DIARIZE_NUM_SPEAKERS environment variable.

    Returns None when *raw* is None (auto-detect mode).
    Raises ConfigurationError for non-integer strings or values <= 0.
    """
    if raw is None:
        return None
    try:
        val = int(raw)
    except ValueError:
        raise ConfigurationError(
            f"WHISPER_DIARIZE_NUM_SPEAKERS must be a positive integer; got {raw!r}"
        )
    if val <= 0:
        raise ConfigurationError(
            f"WHISPER_DIARIZE_NUM_SPEAKERS must be a positive integer; got {val}"
        )
    return val


@dataclass(frozen=True)
class Config:
    # Directories
    base_dir: Path
    input_dir: Path
    output_dir: Path
    done_dir: Path
    failed_dir: Path

    # Backend selection
    backend: str  # "local" | "api" | "diarize"
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
    notify_timeout_sec: float
    notify_retries: int
    notify_format: str
    notify_hmac_secret: str

    # FFmpeg
    ffmpeg_bin: str

    # Constants (carried on Config for threading; not env-configurable)
    output_formats: frozenset
    media_exts: frozenset
    api_max_mb: int
    api_bitrate: str
    stability_seconds: float
    poll_interval: float

    # Batch fields (S2 — groq-batch sprint)
    batch_inbox_dir: Path | None  # TRANSCRIBE_BATCH; None = batch disabled
    batch_submitted_dir: Path  # TRANSCRIBE_BATCH_SUBMITTED; default <base>/batch_submitted
    batch_store_path: Path  # TRANSCRIBE_BATCH_STORE; default <base>/batch_store
    batch_api_key: str  # GROQ_BATCH_API_KEY then WHISPER_API_KEY fallback (D10)
    batch_max_mb: int  # TRANSCRIBE_BATCH_MAX_MB; default 25
    batch_completion_window: str  # TRANSCRIBE_BATCH_COMPLETION_WINDOW; default "24h"
    batch_stage_dir: Path  # TRANSCRIBE_BATCH_STAGE_DIR; default <base>/batch_stage
    batch_funnel_base_url: str  # TRANSCRIBE_BATCH_FUNNEL_URL; default ""

    # Diarize backend
    hf_token: str  # HF_TOKEN; required when backend="diarize"
    diarize_num_speakers: int | None  # WHISPER_DIARIZE_NUM_SPEAKERS; None = auto-detect

    @classmethod
    def from_env(cls) -> Config:
        base_dir = Path(os.environ.get("TRANSCRIBE_BASE", Path.cwd() / "data"))
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
            model_size=os.environ.get("WHISPER_MODEL", "base"),
            device=os.environ.get("WHISPER_DEVICE", "auto"),
            compute_type=os.environ.get("WHISPER_COMPUTE", "auto"),
            api_base_url=os.environ.get("WHISPER_API_BASE", "https://api.groq.com/openai/v1"),
            api_model=os.environ.get("WHISPER_API_MODEL", "whisper-large-v3-turbo"),
            api_key=os.environ.get("WHISPER_API_KEY", ""),
            notify_webhook=os.environ.get("NOTIFY_WEBHOOK", ""),
            notify_timeout_sec=float(os.environ.get("NOTIFY_TIMEOUT_SEC", "5.0")),
            notify_retries=int(os.environ.get("NOTIFY_RETRIES", "0")),
            notify_format=os.environ.get("NOTIFY_FORMAT", "generic").lower(),
            notify_hmac_secret=os.environ.get("NOTIFY_HMAC_SECRET", ""),
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
            batch_inbox_dir=(
                Path(os.environ["TRANSCRIBE_BATCH"]) if os.environ.get("TRANSCRIBE_BATCH") else None
            ),
            batch_submitted_dir=Path(
                os.environ.get("TRANSCRIBE_BATCH_SUBMITTED", base_dir / "batch_submitted")
            ),
            batch_store_path=Path(
                os.environ.get("TRANSCRIBE_BATCH_STORE", base_dir / "batch_store")
            ),
            batch_api_key=(
                os.environ.get("GROQ_BATCH_API_KEY") or os.environ.get("WHISPER_API_KEY", "")
            ),
            batch_max_mb=int(os.environ.get("TRANSCRIBE_BATCH_MAX_MB", "25")),
            batch_completion_window=os.environ.get("TRANSCRIBE_BATCH_COMPLETION_WINDOW", "24h"),
            batch_stage_dir=Path(
                os.environ.get("TRANSCRIBE_BATCH_STAGE_DIR", base_dir / "batch_stage")
            ),
            batch_funnel_base_url=os.environ.get("TRANSCRIBE_BATCH_FUNNEL_URL", ""),
            hf_token=os.environ.get("HF_TOKEN", ""),
            diarize_num_speakers=_parse_diarize_num_speakers(
                os.environ.get("WHISPER_DIARIZE_NUM_SPEAKERS")
            ),
        )
