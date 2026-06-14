"""Characterization tests for the API backend (pre-refactor, Slice S1).

All 20 tests call the public backends.transcribe() entry point and are hermetic:
no live HTTP, no real WHISPER_API_KEY, no real ffmpeg.

These tests must pass GREEN against the current unrefactored code and must remain
green through the S3 registry refactor unchanged (architecture §8.5).
"""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

import pytest

from electric_blue.backends import transcribe
from electric_blue.config import Config
from electric_blue.models import Segment, TranscriptInfo

# ---------------------------------------------------------------------------
# Helpers (architecture §8.2, §8.3)
# ---------------------------------------------------------------------------


def make_response(payload: dict) -> MagicMock:
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


def fake_extract(cfg, src, dst, *, compressed):
    dst.write_bytes(b"x" * 100)  # 0.0001 MB — well under any realistic cap


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DEFAULT_PAYLOAD: dict = {
    "segments": [{"start": 0.0, "end": 2.5, "text": " Hello world. "}],
    "language": "en",
    "duration": 2.5,
}


@pytest.fixture()
def cfg() -> Config:
    """Base API config with all asserted fields set explicitly (hermeticity, INV-8)."""
    return dataclasses.replace(
        Config.from_env(),
        backend="api",
        api_key="sk-test",
        api_model="whisper-large-v3-turbo",
        api_base_url="https://api.groq.com/openai/v1",
        language=None,
        api_max_mb=24,
    )


# ---------------------------------------------------------------------------
# Tests 1–5: POST call shape
# ---------------------------------------------------------------------------


def test_api_post_url(cfg, monkeypatch, tmp_path):
    mock_post = MagicMock(return_value=make_response(_DEFAULT_PAYLOAD))
    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    transcribe(cfg, src)

    assert mock_post.call_args.args[0] == f"{cfg.api_base_url}/audio/transcriptions"


def test_api_post_form_data(cfg, monkeypatch, tmp_path):
    mock_post = MagicMock(return_value=make_response(_DEFAULT_PAYLOAD))
    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    transcribe(cfg, src)

    data = mock_post.call_args.kwargs["data"]
    assert data["model"] == cfg.api_model
    assert data["response_format"] == "verbose_json"
    assert data["timestamp_granularities[]"] == "segment"


def test_api_post_auth_header(cfg, monkeypatch, tmp_path):
    mock_post = MagicMock(return_value=make_response(_DEFAULT_PAYLOAD))
    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    transcribe(cfg, src)

    headers = mock_post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer sk-test"


def test_api_post_language_when_set(cfg, monkeypatch, tmp_path):
    cfg_fr = dataclasses.replace(cfg, language="fr")
    mock_post = MagicMock(return_value=make_response(_DEFAULT_PAYLOAD))
    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    transcribe(cfg_fr, src)

    data = mock_post.call_args.kwargs["data"]
    assert data["language"] == "fr"


def test_api_post_language_absent_when_none(cfg, monkeypatch, tmp_path):
    cfg_none = dataclasses.replace(cfg, language=None)
    mock_post = MagicMock(return_value=make_response(_DEFAULT_PAYLOAD))
    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    transcribe(cfg_none, src)

    data = mock_post.call_args.kwargs["data"]
    assert "language" not in data


# ---------------------------------------------------------------------------
# Tests 6–8: response segment parsing
# ---------------------------------------------------------------------------


def test_api_response_segments_parsed(cfg, monkeypatch, tmp_path):
    payload = {
        "segments": [
            {"start": 1.0, "end": 3.5, "text": "  Hello world.  "},
            {"start": 3.5, "end": 5.0, "text": " Goodbye."},
        ],
        "language": "en",
        "duration": 5.0,
    }
    monkeypatch.setattr("requests.post", MagicMock(return_value=make_response(payload)))
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    segments, _info = transcribe(cfg, src)

    assert len(segments) == 2
    assert isinstance(segments[0], Segment)
    assert segments[0].start == 1.0
    assert segments[0].end == 3.5
    assert segments[0].text == "Hello world."
    assert segments[1].text == "Goodbye."


def test_api_response_fallback_single_segment(cfg, monkeypatch, tmp_path):
    raw_text = "  Fallback text.  "
    duration = 4.2
    payload = {"text": raw_text, "duration": duration}
    monkeypatch.setattr("requests.post", MagicMock(return_value=make_response(payload)))
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    segments, _info = transcribe(cfg, src)

    assert len(segments) == 1
    assert segments[0].start == 0.0
    assert segments[0].end == duration
    assert segments[0].text == raw_text.strip()


def test_api_response_empty_segments_empty_text(cfg, monkeypatch, tmp_path):
    payload = {"segments": [], "language": "en", "duration": 0.0}
    monkeypatch.setattr("requests.post", MagicMock(return_value=make_response(payload)))
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    segments, info = transcribe(cfg, src)

    assert segments == []
    assert isinstance(info, TranscriptInfo)


# ---------------------------------------------------------------------------
# Tests 9–14: TranscriptInfo fields
# ---------------------------------------------------------------------------


def test_api_info_language_from_response(cfg, monkeypatch, tmp_path):
    payload = {"segments": [], "language": "de", "duration": 0.0}
    monkeypatch.setattr("requests.post", MagicMock(return_value=make_response(payload)))
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    _segs, info = transcribe(cfg, src)

    assert info.language == "de"


def test_api_info_language_fallback_cfg(cfg, monkeypatch, tmp_path):
    cfg_en = dataclasses.replace(cfg, language="en")
    payload = {"segments": [], "duration": 0.0}  # no "language" key
    monkeypatch.setattr("requests.post", MagicMock(return_value=make_response(payload)))
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    _segs, info = transcribe(cfg_en, src)

    assert info.language == "en"


def test_api_info_language_fallback_unknown(cfg, monkeypatch, tmp_path):
    cfg_none = dataclasses.replace(cfg, language=None)
    payload = {"segments": [], "duration": 0.0}  # no "language" key
    monkeypatch.setattr("requests.post", MagicMock(return_value=make_response(payload)))
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    _segs, info = transcribe(cfg_none, src)

    assert info.language == "unknown"


def test_api_info_duration(cfg, monkeypatch, tmp_path):
    payload = {"segments": [], "language": "en", "duration": 42.5}
    monkeypatch.setattr("requests.post", MagicMock(return_value=make_response(payload)))
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    _segs, info = transcribe(cfg, src)

    assert info.duration == 42.5


def test_api_info_duration_missing(cfg, monkeypatch, tmp_path):
    payload = {"segments": [], "language": "en"}  # no "duration" key
    monkeypatch.setattr("requests.post", MagicMock(return_value=make_response(payload)))
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    _segs, info = transcribe(cfg, src)

    assert info.duration == 0.0


def test_api_info_backend_string(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr("requests.post", MagicMock(return_value=make_response(_DEFAULT_PAYLOAD)))
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    _segs, info = transcribe(cfg, src)

    assert info.backend == f"api:{cfg.api_model}"


# ---------------------------------------------------------------------------
# Tests 15–18: error paths and size-limit semantics
# ---------------------------------------------------------------------------


def test_api_size_limit_raises(cfg, monkeypatch, tmp_path):
    """RuntimeError raised when encoded size exceeds cap; message names the batch folder."""
    cfg_capped = dataclasses.replace(cfg, api_max_mb=0)
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    with pytest.raises(RuntimeError) as exc_info:
        transcribe(cfg_capped, src)

    assert "Route this one to the local/batch folder" in str(exc_info.value)


def test_api_missing_key_raises(cfg, monkeypatch, tmp_path):
    """RuntimeError raised immediately when api_key is empty; no extract call needed."""
    cfg_nokey = dataclasses.replace(cfg, api_key="")
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    with pytest.raises(RuntimeError) as exc_info:
        transcribe(cfg_nokey, src)

    assert "WHISPER_API_KEY is not set" in str(exc_info.value)


def test_api_info_language_probability_none(cfg, monkeypatch, tmp_path):
    """Pins FLAG-C: the API path never returns a confidence score; must be None, not 0.0."""
    monkeypatch.setattr("requests.post", MagicMock(return_value=make_response(_DEFAULT_PAYLOAD)))
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    _segs, info = transcribe(cfg, src)

    assert info.language_probability is None


def test_api_size_limit_si_boundary(cfg, monkeypatch, tmp_path):
    """Pins FLAG-B: size check uses SI megabytes (/ 1e6), not MiB (/ 1024**2).

    1,048,576 bytes / 1e6 = 1.048576 > 1.0  → RuntimeError (SI).
    1,048,576 bytes / 1024**2 = 1.0 > 1.0   → False, no error (MiB).
    If /1e6 is changed to /1024**2 this test fails — the sentinel value is exact 1 MiB.
    """
    cfg_1mb = dataclasses.replace(cfg, api_max_mb=1)

    def fat_extract(c, s, dst, *, compressed):
        dst.write_bytes(b"x" * 1_048_576)

    monkeypatch.setattr("electric_blue.backends.api.extract", fat_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    with pytest.raises(RuntimeError):
        transcribe(cfg_1mb, src)


# ---------------------------------------------------------------------------
# Tests 19–20: POST call assertions (files tuple and raise_for_status)
# ---------------------------------------------------------------------------


def test_api_post_files_and_timeout(cfg, monkeypatch, tmp_path):
    """Pins verbatim POST shape: filename 'a.mp3', MIME 'audio/mpeg', timeout 600."""
    mock_post = MagicMock(return_value=make_response(_DEFAULT_PAYLOAD))
    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    transcribe(cfg, src)

    files = mock_post.call_args.kwargs["files"]
    assert files["file"][0] == "a.mp3"
    assert files["file"][2] == "audio/mpeg"
    assert mock_post.call_args.kwargs["timeout"] == 600


def test_api_raise_for_status_called(cfg, monkeypatch, tmp_path):
    """HTTP errors surface: raise_for_status() is called exactly once per request."""
    mock_post = MagicMock(return_value=make_response(_DEFAULT_PAYLOAD))
    monkeypatch.setattr("requests.post", mock_post)
    monkeypatch.setattr("electric_blue.backends.api.extract", fake_extract)
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    transcribe(cfg, src)

    mock_post.return_value.raise_for_status.assert_called_once()
