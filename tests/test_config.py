"""Hermetic tests for Config.from_env()."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from electric_blue.config import Config


def test_defaults(monkeypatch, tmp_path):
    """With no env vars set, defaults should match original transcribe_watch.py values."""
    # Clear all TRANSCRIBE_* and WHISPER_* vars so we get clean defaults
    for key in list(os.environ):
        if key.startswith(("TRANSCRIBE_", "WHISPER_", "NOTIFY_", "FFMPEG_")):
            monkeypatch.delenv(key, raising=False)
    # chdir so the cwd-relative base_dir default resolves predictably
    monkeypatch.chdir(tmp_path)

    cfg = Config.from_env()

    expected_base = tmp_path / "data"
    assert cfg.base_dir == expected_base
    assert cfg.input_dir == expected_base / "inbox"
    assert cfg.output_dir == expected_base / "transcripts"
    assert cfg.done_dir == expected_base / "done"
    assert cfg.failed_dir == expected_base / "failed"
    assert cfg.backend == "local"
    assert cfg.language is None
    assert cfg.model_size == "base"
    assert cfg.device == "auto"
    assert cfg.compute_type == "auto"
    assert cfg.api_base_url == "https://api.groq.com/openai/v1"
    assert cfg.api_model == "whisper-large-v3-turbo"
    assert cfg.api_key == ""
    assert cfg.notify_webhook == ""
    assert cfg.ffmpeg_bin == "ffmpeg"
    assert cfg.api_max_mb == 24
    assert cfg.api_bitrate == "64k"
    assert cfg.stability_seconds == 2.0
    assert cfg.poll_interval == 1.0
    # CFG-1: new webhook config fields
    assert cfg.notify_timeout_sec == 5.0
    assert cfg.notify_retries == 0
    assert cfg.notify_format == "generic"
    assert cfg.notify_hmac_secret == ""


def test_env_overrides(monkeypatch, tmp_path):
    """Env vars should override all defaults."""
    monkeypatch.setenv("TRANSCRIBE_BASE", str(tmp_path / "base"))
    monkeypatch.setenv("TRANSCRIBE_INPUT", str(tmp_path / "in"))
    monkeypatch.setenv("TRANSCRIBE_OUTPUT", str(tmp_path / "out"))
    monkeypatch.setenv("TRANSCRIBE_DONE", str(tmp_path / "done"))
    monkeypatch.setenv("TRANSCRIBE_FAILED", str(tmp_path / "fail"))
    monkeypatch.setenv("WHISPER_BACKEND", "api")
    monkeypatch.setenv("WHISPER_LANG", "fr")
    monkeypatch.setenv("WHISPER_MODEL", "tiny")
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("WHISPER_COMPUTE", "int8")
    monkeypatch.setenv("WHISPER_API_BASE", "https://example.com/v1")
    monkeypatch.setenv("WHISPER_API_MODEL", "whisper-1")
    monkeypatch.setenv("WHISPER_API_KEY", "sk-test")
    monkeypatch.setenv("NOTIFY_WEBHOOK", "https://hook.example.com")
    monkeypatch.setenv("FFMPEG_BIN", "/usr/local/bin/ffmpeg")

    cfg = Config.from_env()

    assert cfg.base_dir == tmp_path / "base"
    assert cfg.input_dir == tmp_path / "in"
    assert cfg.output_dir == tmp_path / "out"
    assert cfg.done_dir == tmp_path / "done"
    assert cfg.failed_dir == tmp_path / "fail"
    assert cfg.backend == "api"
    assert cfg.language == "fr"
    assert cfg.model_size == "tiny"
    assert cfg.device == "cpu"
    assert cfg.compute_type == "int8"
    assert cfg.api_base_url == "https://example.com/v1"
    assert cfg.api_model == "whisper-1"
    assert cfg.api_key == "sk-test"
    assert cfg.notify_webhook == "https://hook.example.com"
    assert cfg.ffmpeg_bin == "/usr/local/bin/ffmpeg"


def test_backend_lowercased(monkeypatch):
    monkeypatch.setenv("WHISPER_BACKEND", "API")
    cfg = Config.from_env()
    assert cfg.backend == "api"


def test_whisper_lang_empty_string_becomes_none(monkeypatch):
    monkeypatch.setenv("WHISPER_LANG", "")
    cfg = Config.from_env()
    assert cfg.language is None


def test_output_formats_frozen(monkeypatch):
    cfg = Config.from_env()
    assert cfg.output_formats == frozenset({"txt", "srt", "vtt", "json"})


def test_media_exts_include_common(monkeypatch):
    cfg = Config.from_env()
    assert ".mp4" in cfg.media_exts
    assert ".wav" in cfg.media_exts
    assert ".mp3" in cfg.media_exts


def test_config_is_frozen(monkeypatch):
    cfg = Config.from_env()
    with pytest.raises((AttributeError, TypeError)):
        cfg.backend = "api"  # type: ignore[misc]


def test_notify_timeout_sec_env_override(monkeypatch):
    """CFG-2: NOTIFY_TIMEOUT_SEC is parsed as float."""
    monkeypatch.setenv("NOTIFY_TIMEOUT_SEC", "2.5")
    cfg = Config.from_env()
    assert cfg.notify_timeout_sec == 2.5
    assert isinstance(cfg.notify_timeout_sec, float)


def test_notify_retries_env_override(monkeypatch):
    """CFG-3: NOTIFY_RETRIES is parsed as int."""
    monkeypatch.setenv("NOTIFY_RETRIES", "3")
    cfg = Config.from_env()
    assert cfg.notify_retries == 3
    assert isinstance(cfg.notify_retries, int)


def test_notify_format_lowercased(monkeypatch):
    """CFG-4: NOTIFY_FORMAT value is lowercased regardless of input case."""
    monkeypatch.setenv("NOTIFY_FORMAT", "NTFY")
    cfg = Config.from_env()
    assert cfg.notify_format == "ntfy"


def test_notify_hmac_secret_env_override(monkeypatch):
    """CFG-5: NOTIFY_HMAC_SECRET is stored as-is (no transformation)."""
    monkeypatch.setenv("NOTIFY_HMAC_SECRET", "abc123")
    cfg = Config.from_env()
    assert cfg.notify_hmac_secret == "abc123"


def test_notify_new_fields_frozen(monkeypatch):
    """CFG-7: the new Config fields are also immutable after construction."""
    cfg = Config.from_env()
    with pytest.raises((AttributeError, TypeError)):
        cfg.notify_timeout_sec = 99.0  # type: ignore[misc]


# ── S2 batch-config tests (CFG-1..9) ──────────────────────────────────────


def test_batch_defaults(monkeypatch, tmp_path):
    """CFG-1: no batch env vars → all 8 batch fields take their documented defaults.

    base_dir is derived the same way config.py does: Path.cwd() / "data" when
    TRANSCRIBE_BASE is unset.  chdir to tmp_path makes that predictable.
    """
    for key in list(os.environ):
        if key.startswith(("TRANSCRIBE_", "WHISPER_", "NOTIFY_", "FFMPEG_", "GROQ_BATCH_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)

    cfg = Config.from_env()
    base = tmp_path / "data"

    assert cfg.batch_inbox_dir is None
    assert cfg.batch_submitted_dir == base / "batch_submitted"
    assert cfg.batch_store_path == base / "batch_store"
    assert cfg.batch_api_key == ""
    assert cfg.batch_max_mb == 25
    assert cfg.batch_completion_window == "24h"
    assert cfg.batch_stage_dir == base / "batch_stage"
    assert cfg.batch_funnel_base_url == ""


def test_batch_inbox_dir_from_env(monkeypatch):
    """CFG-2: TRANSCRIBE_BATCH sets batch_inbox_dir to the given path."""
    monkeypatch.setenv("TRANSCRIBE_BATCH", "/tmp/bi")
    cfg = Config.from_env()
    assert cfg.batch_inbox_dir == Path("/tmp/bi")


def test_batch_api_key_prefers_groq_batch_key(monkeypatch):
    """CFG-3: GROQ_BATCH_API_KEY takes precedence over WHISPER_API_KEY (D10)."""
    monkeypatch.setenv("GROQ_BATCH_API_KEY", "gk-abc")
    monkeypatch.setenv("WHISPER_API_KEY", "sk-xyz")
    cfg = Config.from_env()
    assert cfg.batch_api_key == "gk-abc"


def test_batch_api_key_falls_back_to_whisper_api_key(monkeypatch):
    """CFG-4: when GROQ_BATCH_API_KEY is absent, batch_api_key uses WHISPER_API_KEY (D10 fallback)."""
    monkeypatch.delenv("GROQ_BATCH_API_KEY", raising=False)
    monkeypatch.setenv("WHISPER_API_KEY", "sk-xyz")
    cfg = Config.from_env()
    assert cfg.batch_api_key == "sk-xyz"


def test_batch_max_mb_parsed_as_int(monkeypatch):
    """CFG-5: TRANSCRIBE_BATCH_MAX_MB is coerced to int."""
    monkeypatch.setenv("TRANSCRIBE_BATCH_MAX_MB", "50")
    cfg = Config.from_env()
    assert cfg.batch_max_mb == 50
    assert isinstance(cfg.batch_max_mb, int) is True


def test_batch_completion_window_env(monkeypatch):
    """CFG-6: TRANSCRIBE_BATCH_COMPLETION_WINDOW overrides the "24h" default."""
    monkeypatch.setenv("TRANSCRIBE_BATCH_COMPLETION_WINDOW", "7d")
    cfg = Config.from_env()
    assert cfg.batch_completion_window == "7d"


def test_batch_fields_frozen(monkeypatch):
    """CFG-8: assigning to any batch field after construction raises (frozen dataclass)."""
    cfg = Config.from_env()
    with pytest.raises((AttributeError, TypeError)):
        cfg.batch_inbox_dir = None  # type: ignore[misc]


def test_batch_api_key_not_logged(monkeypatch, caplog):
    """CFG-9: cfg.batch_api_key value never appears in any log output (INV-7).

    Asserted across Config.from_env() — the construction path that reads the key.
    Cross-path verification through backend HTTP headers is the responsibility of S5/S6.
    """
    monkeypatch.setenv("GROQ_BATCH_API_KEY", "gk-secret")
    with caplog.at_level(logging.DEBUG):
        Config.from_env()
    assert "gk-secret" not in caplog.text
