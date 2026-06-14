"""Tests for notify.py payload builders — S3 (PAY, STA, RED acceptance criteria).

S5 will extend this file with REL, FMT, HMAC, and watcher integration tests.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from electric_blue.config import Config
from electric_blue.models import TranscriptInfo
from electric_blue.notify import (
    build_done_payload,
    build_failed_payload,
    build_started_payload,
)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 6, 14, 10, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 6, 14, 10, 1, 30, tzinfo=timezone.utc)  # 90 s after _T0

_INFO = TranscriptInfo(
    language="en",
    language_probability=0.99,
    duration=95.3,
    backend="api:whisper-large-v3-turbo",
)

_OUTPUT_STEMS: dict[str, Path] = {
    "txt": Path("/transcripts/meeting.txt"),
    "srt": Path("/transcripts/meeting.srt"),
}

_SRC = Path("/inbox/meeting.mp4")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cfg(monkeypatch):
    """Config with webhook set and safe defaults for all new fields."""
    monkeypatch.delenv("NOTIFY_WEBHOOK", raising=False)
    return dataclasses.replace(
        Config.from_env(),
        notify_webhook="http://fake.invalid/hook",
        notify_timeout_sec=1.0,
        notify_retries=0,
        notify_format="generic",
        notify_hmac_secret="",
    )


# ---------------------------------------------------------------------------
# PAY-1 — done payload fields
# ---------------------------------------------------------------------------


def test_done_payload_fields(cfg):
    """PAY-1: build_done_payload returns all expected v1 fields with correct values/types."""
    payload = build_done_payload(cfg, _SRC, _INFO, _OUTPUT_STEMS, _T0, _T1)

    assert payload["schema_version"] == 1
    assert payload["event"] == "done"
    assert payload["file"] == "meeting.mp4"  # filename only — never full path
    assert payload["status"] == "done"
    assert payload["duration_sec"] == round(_INFO.duration, 1)
    assert payload["language"] == _INFO.language
    assert payload["backend"] == _INFO.backend  # info.backend overrides cfg.backend
    assert payload["outputs"] == {"txt": "meeting.txt", "srt": "meeting.srt"}
    assert payload["started_at"] == _T0.isoformat(timespec="seconds")
    assert payload["finished_at"] == _T1.isoformat(timespec="seconds")
    assert isinstance(payload["wall_sec"], float)


# ---------------------------------------------------------------------------
# PAY-2 — failed payload fields
# ---------------------------------------------------------------------------


def test_failed_payload_fields(cfg):
    """PAY-2: build_failed_payload has event/status/error; no duration_sec/language/outputs."""
    exc = ValueError("codec error")
    payload = build_failed_payload(cfg, _SRC, exc, _T0, _T1)

    assert payload["schema_version"] == 1
    assert payload["event"] == "failed"
    assert payload["status"] == "failed"
    assert payload["error"] == "codec error"  # str(exc) — message only, no traceback
    assert "started_at" in payload
    assert "finished_at" in payload
    assert "wall_sec" in payload
    assert "duration_sec" not in payload
    assert "language" not in payload
    assert "outputs" not in payload


# ---------------------------------------------------------------------------
# PAY-3 + PAY-4 — wall_sec is derived from timestamps
# ---------------------------------------------------------------------------


def test_wall_sec_is_derived(cfg):
    """PAY-3 + PAY-4: wall_sec == round((finished_at - started_at).total_seconds(), 1)."""
    # PAY-3: exactly 90-second gap
    t0 = datetime(2026, 6, 14, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 14, 10, 1, 30, tzinfo=timezone.utc)
    p90 = build_done_payload(cfg, _SRC, _INFO, _OUTPUT_STEMS, t0, t1)
    assert p90["wall_sec"] == 90.0

    # PAY-4: exactly 86400-second gap (24 h async batch boundary); schema unchanged
    t2 = datetime(2026, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
    p86400 = build_done_payload(cfg, _SRC, _INFO, _OUTPUT_STEMS, t0, t2)
    assert p86400["wall_sec"] == 86400.0
    assert p86400["schema_version"] == 1


# ---------------------------------------------------------------------------
# STA-1 — started payload omits finished fields
# ---------------------------------------------------------------------------


def test_started_payload_omits_finished(cfg):
    """STA-1: build_started_payload has started_at; no finished_at, no wall_sec."""
    payload = build_started_payload(cfg, Path("/inbox/file.mp3"), _T0)

    assert payload["schema_version"] == 1
    assert payload["event"] == "started"
    assert payload["file"] == "file.mp3"
    assert payload["backend"] == cfg.backend
    assert "started_at" in payload
    assert "finished_at" not in payload
    assert "wall_sec" not in payload


# ---------------------------------------------------------------------------
# RED-1 + RED-2 — no absolute paths in payload
# ---------------------------------------------------------------------------


def test_no_absolute_paths(cfg):
    """RED-1 + RED-2: file==filename only; "/home" absent from json.dumps(payload)."""
    src = Path("/home/user/inbox/meeting.mp4")
    payload = build_done_payload(cfg, src, _INFO, _OUTPUT_STEMS, _T0, _T1)

    assert payload["file"] == "meeting.mp4"
    assert "/home" not in json.dumps(payload)


# ---------------------------------------------------------------------------
# RED-3 — api_key absent from payload
# ---------------------------------------------------------------------------


def test_no_api_key_in_payload(cfg):
    """RED-3: cfg.api_key='sk-secret' must not appear anywhere in json.dumps(payload)."""
    cfg_with_key = dataclasses.replace(cfg, api_key="sk-secret")
    payload = build_done_payload(cfg_with_key, _SRC, _INFO, _OUTPUT_STEMS, _T0, _T1)

    assert "sk-secret" not in json.dumps(payload)


# ---------------------------------------------------------------------------
# PAY-5 — timestamps parse as ISO-8601 UTC
# ---------------------------------------------------------------------------


def test_timestamps_parse_as_utc(cfg):
    """PAY-5: started_at and finished_at parse with fromisoformat() and carry UTC tzinfo."""
    payload = build_done_payload(cfg, _SRC, _INFO, _OUTPUT_STEMS, _T0, _T1)

    started = datetime.fromisoformat(payload["started_at"])
    finished = datetime.fromisoformat(payload["finished_at"])

    assert started.tzinfo is not None
    assert started.utcoffset().total_seconds() == 0
    assert finished.tzinfo is not None
    assert finished.utcoffset().total_seconds() == 0
