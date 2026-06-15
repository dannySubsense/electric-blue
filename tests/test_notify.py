"""Tests for notify.py — S3 (PAY, STA, RED) and S5 (REL, FMT, HMAC, watcher integration)."""

from __future__ import annotations

import dataclasses
import json
import re
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests as _requests

from electric_blue.config import Config
from electric_blue.models import Segment, TranscriptInfo
from electric_blue.notify import (
    _format_ntfy,
    _sign,
    build_done_payload,
    build_failed_payload,
    build_started_payload,
    notify,
)
from electric_blue.watcher import handle

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


# ---------------------------------------------------------------------------
# Watcher integration fixture (STA-2, INT-1, INT-2, INT-4)
# ---------------------------------------------------------------------------

_FAKE_WATCHER_INFO = TranscriptInfo(
    language="en", language_probability=0.99, duration=2.5, backend="test:tiny"
)


@pytest.fixture()
def watcher_env(tmp_dirs, monkeypatch):
    """Cfg pointing at tmp_dirs; is_stable patched True; fake .mp4 in input dir."""
    for k, v in [
        ("TRANSCRIBE_BASE", str(tmp_dirs["base"])),
        ("TRANSCRIBE_INPUT", str(tmp_dirs["input"])),
        ("TRANSCRIBE_OUTPUT", str(tmp_dirs["output"])),
        ("TRANSCRIBE_DONE", str(tmp_dirs["done"])),
        ("TRANSCRIBE_FAILED", str(tmp_dirs["failed"])),
    ]:
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("NOTIFY_WEBHOOK", raising=False)

    w_cfg = Config.from_env()
    monkeypatch.setattr("electric_blue.watcher.is_stable", lambda path, s=None: True)

    src = tmp_dirs["input"] / "clip.mp4"
    src.write_bytes(b"fake video data")
    return w_cfg, src


# ---------------------------------------------------------------------------
# REL — Reliability (REL-1 .. REL-8)
# ---------------------------------------------------------------------------


def test_timeout_from_config(cfg, monkeypatch):
    """REL-1: requests.post called with timeout=cfg.notify_timeout_sec (not hardcoded)."""
    captured_timeouts = []

    def mock_post(url, json=None, headers=None, timeout=None):
        captured_timeouts.append(timeout)
        return unittest.mock.MagicMock(status_code=200)

    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)

    cfg_timed = dataclasses.replace(cfg, notify_timeout_sec=7.5)
    notify(cfg_timed, {})

    assert captured_timeouts == [7.5]


def test_swallows_connection_error(cfg, monkeypatch):
    """REL-2: ConnectionError → notify() returns normally; post called exactly once."""
    mock_post = unittest.mock.MagicMock(side_effect=_requests.ConnectionError("network fail"))
    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)

    notify(cfg, {})  # must not raise

    assert mock_post.call_count == 1


def test_swallows_timeout(cfg, monkeypatch):
    """REL-3: requests.Timeout → returns normally; post called exactly once."""
    mock_post = unittest.mock.MagicMock(side_effect=_requests.Timeout("timed out"))
    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)

    notify(cfg, {})

    assert mock_post.call_count == 1


def test_swallows_http_500(cfg, monkeypatch):
    """REL-4: HTTP 500 → returns normally; post called once (retries=0 → no retry)."""
    mock_post = unittest.mock.MagicMock(return_value=unittest.mock.MagicMock(status_code=500))
    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)

    notify(cfg, {})  # cfg has notify_retries=0

    assert mock_post.call_count == 1


def test_retry_on_5xx(cfg, monkeypatch):
    """REL-5 + REL-6: notify_retries=1; HTTP 500 then 200 → post called exactly twice."""
    responses = [
        unittest.mock.MagicMock(status_code=500),
        unittest.mock.MagicMock(status_code=200),
    ]
    mock_post = unittest.mock.MagicMock(side_effect=responses)
    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)

    cfg_retry = dataclasses.replace(cfg, notify_retries=1)
    notify(cfg_retry, {})

    assert mock_post.call_count == 2


def test_no_retry_on_4xx(cfg, monkeypatch):
    """REL-7: notify_retries=1; HTTP 400 → post called exactly once (4xx not retried)."""
    mock_post = unittest.mock.MagicMock(return_value=unittest.mock.MagicMock(status_code=400))
    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)

    cfg_retry = dataclasses.replace(cfg, notify_retries=1)
    notify(cfg_retry, {})

    assert mock_post.call_count == 1


def test_warning_level_only(cfg, monkeypatch, caplog):
    """REL-8: on any failure, all log records are at WARNING — never ERROR or higher."""
    import logging

    mock_post = unittest.mock.MagicMock(side_effect=_requests.ConnectionError("fail"))
    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)

    with caplog.at_level(logging.DEBUG, logger="electric_blue"):
        notify(cfg, {})

    assert caplog.records, "Expected at least one log record on failure"
    for record in caplog.records:
        assert (
            record.levelno <= logging.WARNING
        ), f"Expected WARNING or lower, got {record.levelname}: {record.message}"


# ---------------------------------------------------------------------------
# FMT — Provider formatters (FMT-1 .. FMT-3)
# ---------------------------------------------------------------------------


def test_posts_generic_payload(cfg, monkeypatch):
    """FMT-1: notify_format='generic' → requests.post receives the raw v1 dict unchanged."""
    raw_payload = {"schema_version": 1, "event": "done", "file": "clip.mp4"}

    captured_bodies = []

    def mock_post(url, json=None, headers=None, timeout=None):
        captured_bodies.append(json)
        return unittest.mock.MagicMock(status_code=200)

    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)

    # cfg fixture already has notify_format="generic"
    notify(cfg, raw_payload)

    assert captured_bodies == [raw_payload]


def test_format_ntfy_done(cfg):
    """FMT-2 + FMT-3: _format_ntfy(done_payload) → exact key set {title,message,priority,tags};
    json.dumps of result contains no '/' -prefixed path string."""
    done_payload = build_done_payload(cfg, _SRC, _INFO, _OUTPUT_STEMS, _T0, _T1)
    result = _format_ntfy(done_payload)

    # FMT-2: exact key set — formatter introduces no extra fields
    assert set(result.keys()) == {"title", "message", "priority", "tags"}

    # FMT-3: no absolute-path strings in the serialized ntfy body
    serialized = json.dumps(result)
    assert (
        '"/' not in serialized
    ), f"Absolute path substring found in ntfy serialization: {serialized}"


def test_format_ntfy_failed_no_optional_fields(cfg):
    """FMT-2 edge: _format_ntfy with failed payload (no outputs/duration_sec/language) → no raise."""
    failed_payload = build_failed_payload(cfg, _SRC, ValueError("codec error"), _T0, _T1)
    # failed payload has no outputs, duration_sec, or language — formatter must handle gracefully
    result = _format_ntfy(failed_payload)

    assert set(result.keys()) == {"title", "message", "priority", "tags"}


# ---------------------------------------------------------------------------
# HMAC — Optional signing (HMAC-1 .. HMAC-4, RED-4 / INV-7)
# ---------------------------------------------------------------------------


def test_hmac_absent_when_no_secret(cfg, monkeypatch):
    """HMAC-1: notify_hmac_secret='' → no X-Electric-Blue-Signature header sent."""
    captured_headers = []

    def mock_post(url, json=None, headers=None, timeout=None):
        captured_headers.append(headers or {})
        return unittest.mock.MagicMock(status_code=200)

    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)

    # cfg fixture already has notify_hmac_secret=""
    notify(cfg, {})

    assert len(captured_headers) == 1
    assert "X-Electric-Blue-Signature" not in captured_headers[0]


def test_hmac_header_present(cfg, monkeypatch):
    """HMAC-2 + HMAC-3: secret set → header matches sha256=[0-9a-f]{64}; equals _sign() output."""
    captured = []

    def mock_post(url, json=None, headers=None, timeout=None):
        captured.append({"json": json, "headers": headers or {}})
        return unittest.mock.MagicMock(status_code=200)

    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)

    secret = "s"
    payload = {"event": "done", "file": "test.mp4"}
    cfg_signed = dataclasses.replace(cfg, notify_hmac_secret=secret, notify_format="generic")

    notify(cfg_signed, payload)

    assert len(captured) == 1
    sig = captured[0]["headers"].get("X-Electric-Blue-Signature", "")

    # HMAC-2: header matches expected pattern
    assert re.fullmatch(r"sha256=[0-9a-f]{64}", sig), f"Unexpected signature format: {sig!r}"

    # HMAC-3: value equals _sign() over canonical JSON of the payload
    body_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    expected = _sign(body_bytes, secret)
    assert sig == expected


def test_hmac_over_formatted_body(cfg, monkeypatch):
    """HMAC-4: HMAC is computed over the post-_format_payload body, not the raw v1 dict."""
    secret = "hmac-key"
    cfg_ntfy = dataclasses.replace(cfg, notify_format="ntfy", notify_hmac_secret=secret)

    # Started payload — _format_ntfy reshapes it significantly (different keys entirely)
    raw_payload = build_started_payload(cfg_ntfy, _SRC, _T0)

    captured = []

    def mock_post(url, json=None, headers=None, timeout=None):
        captured.append({"json": json, "headers": headers or {}})
        return unittest.mock.MagicMock(status_code=200)

    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)
    notify(cfg_ntfy, raw_payload)

    assert len(captured) == 1
    sig = captured[0]["headers"]["X-Electric-Blue-Signature"]

    # Signature must match HMAC over the ntfy-formatted body
    ntfy_body = _format_ntfy(raw_payload)
    expected_sig = _sign(
        json.dumps(ntfy_body, sort_keys=True, separators=(",", ":")).encode(),
        secret,
    )
    assert sig == expected_sig

    # And must NOT match HMAC over the raw v1 body (ntfy format changes the shape)
    raw_sig = _sign(
        json.dumps(raw_payload, sort_keys=True, separators=(",", ":")).encode(),
        secret,
    )
    assert ntfy_body != raw_payload, "ntfy format must change the payload shape"
    assert sig != raw_sig


def test_no_hmac_secret_leak(cfg, monkeypatch, caplog):
    """RED-4 / INV-7: notify_hmac_secret='topsecret' → secret absent from POST body and logs."""
    import logging

    secret = "topsecret"
    cfg_signed = dataclasses.replace(cfg, notify_hmac_secret=secret)

    captured_bodies = []

    def mock_post(url, json=None, headers=None, timeout=None):
        captured_bodies.append(json)
        return unittest.mock.MagicMock(status_code=200)

    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)

    with caplog.at_level(logging.DEBUG, logger="electric_blue"):
        notify(cfg_signed, {"event": "done"})

    assert len(captured_bodies) == 1
    assert secret not in json.dumps(
        captured_bodies[0]
    ), "HMAC secret must not appear in the serialized POST body"
    assert secret not in caplog.text, "HMAC secret must not appear in any log record"


# ---------------------------------------------------------------------------
# Watcher integration (STA-2, INT-1, INT-2, INT-4)
# ---------------------------------------------------------------------------


def test_watcher_started_fires_before_transcribe(watcher_env, monkeypatch):
    """STA-2: notify(started) is called before transcribe() is invoked."""
    w_cfg, src = watcher_env

    call_order = []

    def mock_notify(c, p):
        call_order.append(("notify", p.get("event")))

    def mock_transcribe(c, s):
        call_order.append(("transcribe",))
        return [Segment(0.0, 2.5, "Hello.")], _FAKE_WATCHER_INFO

    monkeypatch.setattr("electric_blue.watcher.notify", mock_notify)
    monkeypatch.setattr("electric_blue.watcher.transcribe", mock_transcribe)
    monkeypatch.setattr(
        "electric_blue.watcher.write_outputs",
        lambda *a, **kw: {"txt": Path("/fake/clip.txt")},
    )

    handle(w_cfg, src)

    started_idx = next(i for i, c in enumerate(call_order) if c == ("notify", "started"))
    transcribe_idx = next(i for i, c in enumerate(call_order) if c[0] == "transcribe")
    assert started_idx < transcribe_idx


def test_watcher_done_on_success(watcher_env, monkeypatch):
    """INT-1: successful transcription → notify called with event='done' and output filenames."""
    w_cfg, src = watcher_env

    notify_calls = []

    def mock_notify(c, p):
        notify_calls.append(dict(p))

    def mock_transcribe(c, s):
        return [Segment(0.0, 2.5, "Hello.")], _FAKE_WATCHER_INFO

    monkeypatch.setattr("electric_blue.watcher.notify", mock_notify)
    monkeypatch.setattr("electric_blue.watcher.transcribe", mock_transcribe)
    monkeypatch.setattr(
        "electric_blue.watcher.write_outputs",
        lambda *a, **kw: {
            "txt": Path("/fake/output/clip.txt"),
            "srt": Path("/fake/output/clip.srt"),
        },
    )

    handle(w_cfg, src)

    done_calls = [p for p in notify_calls if p.get("event") == "done"]
    assert done_calls, "Expected at least one done notification"
    done_payload = done_calls[0]
    assert done_payload["event"] == "done"
    assert "outputs" in done_payload
    # D1: outputs carry filename-only strings — no absolute paths
    for val in done_payload["outputs"].values():
        assert "/" not in val, f"Absolute path found in output filename: {val!r}"


def test_watcher_failed_on_exception(watcher_env, monkeypatch):
    """INT-2: transcribe raises → notify called with event='failed' payload before file move."""
    w_cfg, src = watcher_env

    notify_calls = []

    def mock_notify(c, p):
        notify_calls.append(dict(p))

    def bad_transcribe(c, s):
        raise RuntimeError("backend exploded")

    monkeypatch.setattr("electric_blue.watcher.notify", mock_notify)
    monkeypatch.setattr("electric_blue.watcher.transcribe", bad_transcribe)

    handle(w_cfg, src)

    failed_calls = [p for p in notify_calls if p.get("event") == "failed"]
    assert failed_calls, "Expected at least one failed notification"
    failed_payload = failed_calls[0]
    assert failed_payload["status"] == "failed"
    assert "error" in failed_payload
    assert "backend exploded" in failed_payload["error"]


def test_started_at_shared(watcher_env, monkeypatch):
    """INT-4: started_at is identical in both started and done payloads.

    A single datetime.now(timezone.utc) is stamped in handle() and passed into
    process() — confirming the scoping fix (FLAG-2) prevents double-stamping.
    """
    w_cfg, src = watcher_env

    notify_calls = []

    def mock_notify(c, p):
        notify_calls.append(dict(p))

    def mock_transcribe(c, s):
        return [Segment(0.0, 2.5, "Hello.")], _FAKE_WATCHER_INFO

    monkeypatch.setattr("electric_blue.watcher.notify", mock_notify)
    monkeypatch.setattr("electric_blue.watcher.transcribe", mock_transcribe)
    monkeypatch.setattr(
        "electric_blue.watcher.write_outputs",
        lambda *a, **kw: {"txt": Path("/fake/clip.txt")},
    )

    handle(w_cfg, src)

    started_payload = next(p for p in notify_calls if p.get("event") == "started")
    done_payload = next(p for p in notify_calls if p.get("event") == "done")

    assert started_payload["started_at"] == done_payload["started_at"]
