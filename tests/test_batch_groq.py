"""Tests for backends/batch_groq.py — ASYNC-1..12 + STAG-4 + STAG-7 (DDR-03 / S5).

All HTTP mocked; zero live network; zero real ffmpeg.

Mock seams (per module docstring):
    electric_blue.backends.batch_groq.requests.post  — /files upload + /batches create
    electric_blue.backends.batch_groq.requests.get   — poll + fetch output
    electric_blue.backends.batch_groq.audio.extract  — suppress ffmpeg subprocess
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from electric_blue.backends.batch_groq import GroqBatchBackend
from electric_blue.batch_store import JobRef
from electric_blue.config import Config

# ---------------------------------------------------------------------------
# StubStager: test double for UrlStager
# ---------------------------------------------------------------------------


class StubStager:
    """Records stage() calls; returns a deterministic URL per path.name."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.stage_calls: list[Path] = []

    def stage(self, path: Path) -> str:
        self.stage_calls.append(path)
        return f"{self.base_url}/{path.name}"

    def unstage(self, url: str) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_post_mock(
    file_id: str = "file_test123",
    batch_id: str = "batch_test456",
) -> MagicMock:
    """Side-effect mock for requests.post: /files response first, /batches second."""
    files_resp = MagicMock()
    files_resp.raise_for_status.return_value = None
    files_resp.json.return_value = {"id": file_id}

    batches_resp = MagicMock()
    batches_resp.raise_for_status.return_value = None
    batches_resp.json.return_value = {"id": batch_id}

    return MagicMock(side_effect=[files_resp, batches_resp])


def _make_extract_stub(size_bytes: int = 100) -> MagicMock:
    """MagicMock for audio.extract that writes fake bytes to dst (enables size check + stage)."""

    def _side_effect(cfg: Config, src: Path, dst: Path, *, compressed: bool) -> None:
        dst.write_bytes(b"x" * size_bytes)

    return MagicMock(side_effect=_side_effect)


def _make_get_mock(status_data: dict) -> MagicMock:
    """Return a mock for requests.get that responds with the given dict."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = status_data
    return MagicMock(return_value=resp)


def _make_get_text_mock(text: str) -> MagicMock:
    """Return a mock for requests.get that responds with the given text (fetch path)."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.text = text
    return MagicMock(return_value=resp)


def _parse_jsonl_body(mock_post: MagicMock) -> dict:
    """Extract and parse the JSONL bytes from the first requests.post call."""
    files_call = mock_post.call_args_list[0]
    jsonl_bytes: bytes = files_call.kwargs["files"]["file"][1]
    return json.loads(jsonl_bytes.decode("utf-8"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cfg(tmp_path: Path) -> Config:
    """Config with all batch fields set; all dirs under tmp_path."""
    base = tmp_path
    return dataclasses.replace(
        Config.from_env(),
        base_dir=base,
        input_dir=base / "inbox",
        output_dir=base / "transcripts",
        done_dir=base / "done",
        failed_dir=base / "failed",
        batch_api_key="gk-test",
        batch_funnel_base_url="https://h.ts.net/stage",
        batch_stage_dir=base / "stage",
        batch_max_mb=25,
        api_model="whisper-large-v3-turbo",
        language=None,
    )


@pytest.fixture()
def stub_stager(cfg: Config) -> StubStager:
    return StubStager(base_url=cfg.batch_funnel_base_url)


@pytest.fixture()
def src_file(tmp_path: Path) -> Path:
    p = tmp_path / "meeting.mp4"
    p.write_bytes(b"fake-video-bytes")
    return p


@pytest.fixture()
def job_ref() -> JobRef:
    return JobRef(
        job_id="batch_abc",
        jsonl_file_id="file_xyz",
        staged_url="https://h.ts.net/stage/meeting.mp3",
    )


# ---------------------------------------------------------------------------
# ASYNC-1: Protocol satisfaction
# ---------------------------------------------------------------------------


def test_async1_protocol_satisfied() -> None:
    """ASYNC-1: GroqBatchBackend has name, capabilities, submit, poll, fetch (AsyncBackend seam)."""
    backend = GroqBatchBackend(stager=StubStager(base_url="https://example.com"))

    assert hasattr(backend, "name")
    assert hasattr(backend, "capabilities")
    assert callable(getattr(backend, "submit", None))
    assert callable(getattr(backend, "poll", None))
    assert callable(getattr(backend, "fetch", None))


# ---------------------------------------------------------------------------
# ASYNC-2: Capabilities values
# ---------------------------------------------------------------------------


def test_async2_capabilities() -> None:
    """ASYNC-2: capabilities has is_async=True, needs_network=True, needs_gpu_recommended=False, max_upload_mb=None."""
    caps = GroqBatchBackend.capabilities

    assert caps.is_async is True
    assert caps.needs_network is True
    assert caps.needs_gpu_recommended is False
    assert caps.max_upload_mb is None


# ---------------------------------------------------------------------------
# ASYNC-3 + CFG-9: submit happy path; API key absent from log output
# ---------------------------------------------------------------------------


def test_async3_submit_happy_path_and_cfg9_key_not_in_logs(
    cfg: Config,
    stub_stager: StubStager,
    src_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ASYNC-3 + CFG-9: submit encodes→stages→POSTs JSONL+batch correctly; API key not in logs."""
    mock_post = _make_post_mock(file_id="file_test123", batch_id="batch_test456")
    mock_extract = _make_extract_stub()
    monkeypatch.setattr("electric_blue.backends.batch_groq.requests.post", mock_post)
    monkeypatch.setattr("electric_blue.backends.batch_groq.audio.extract", mock_extract)

    backend = GroqBatchBackend(stager=stub_stager)

    with caplog.at_level(logging.DEBUG, logger="electric_blue"):
        job = backend.submit(cfg, src_file)

    # (a) audio.extract called with compressed=True
    assert mock_extract.call_args.kwargs["compressed"] is True

    # (b) stager.stage called exactly once
    assert len(stub_stager.stage_calls) == 1

    # Parse the JSONL from the /files POST
    request_obj = _parse_jsonl_body(mock_post)
    body: dict = request_obj["body"]

    # (c) JSONL body has "url" and no "file" key
    assert "url" in body
    assert "file" not in body

    # (d) custom_id == f"eb-{src.stem}"
    assert request_obj["custom_id"] == f"eb-{src_file.stem}"

    # (e) files POST URL ends with /files
    files_url: str = mock_post.call_args_list[0].args[0]
    assert files_url.endswith("/files")

    # (f) batches POST includes completion_window
    batches_json: dict = mock_post.call_args_list[1].kwargs["json"]
    assert batches_json["completion_window"] == cfg.batch_completion_window

    # (g) JobRef.staged_url matches the value returned by stager.stage()
    expected_staged_url = f"{cfg.batch_funnel_base_url}/{src_file.stem}.mp3"
    assert job.staged_url == expected_staged_url

    # CFG-9: API key must not appear anywhere in log output across the submit path
    assert cfg.batch_api_key not in caplog.text


# ---------------------------------------------------------------------------
# ASYNC-4: in_progress → not terminal
# ---------------------------------------------------------------------------


def test_async4_poll_in_progress(
    cfg: Config, job_ref: JobRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ASYNC-4: status "in_progress" → JobStatus(terminal=False, succeeded=False, output_file_id=None, error=None)."""
    monkeypatch.setattr(
        "electric_blue.backends.batch_groq.requests.get",
        _make_get_mock({"status": "in_progress"}),
    )

    status = GroqBatchBackend(stager=StubStager(cfg.batch_funnel_base_url)).poll(cfg, job_ref)

    assert status.terminal is False
    assert status.succeeded is False
    assert status.output_file_id is None
    assert status.error is None


# ---------------------------------------------------------------------------
# ASYNC-5: completed → terminal + succeeded
# ---------------------------------------------------------------------------


def test_async5_poll_completed(
    cfg: Config, job_ref: JobRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ASYNC-5: status "completed" + output_file_id → JobStatus(terminal=True, succeeded=True, output_file_id=...)."""
    monkeypatch.setattr(
        "electric_blue.backends.batch_groq.requests.get",
        _make_get_mock({"status": "completed", "output_file_id": "file_abc"}),
    )

    status = GroqBatchBackend(stager=StubStager(cfg.batch_funnel_base_url)).poll(cfg, job_ref)

    assert status.terminal is True
    assert status.succeeded is True
    assert status.output_file_id == "file_abc"


# ---------------------------------------------------------------------------
# ASYNC-6: failed / expired / cancelled → terminal, not succeeded
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw_status", ["failed", "expired", "cancelled"])
def test_async6_poll_terminal_failures(
    cfg: Config,
    job_ref: JobRef,
    monkeypatch: pytest.MonkeyPatch,
    raw_status: str,
) -> None:
    """ASYNC-6: failed/expired/cancelled → JobStatus(terminal=True, succeeded=False)."""
    monkeypatch.setattr(
        "electric_blue.backends.batch_groq.requests.get",
        _make_get_mock({"status": raw_status}),
    )

    status = GroqBatchBackend(stager=StubStager(cfg.batch_funnel_base_url)).poll(cfg, job_ref)

    assert status.terminal is True
    assert status.succeeded is False


# ---------------------------------------------------------------------------
# ASYNC-7: fetch with segments → Transcript segments
# ---------------------------------------------------------------------------


def test_async7_fetch_segments(cfg: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    """ASYNC-7: output JSONL with segments → Transcript.segments + info.backend == f"batch:{model}"."""
    output_jsonl = json.dumps(
        {
            "response": {
                "body": {
                    "segments": [{"start": 0.0, "end": 2.4, "text": " hello"}],
                    "language": "en",
                    "duration": 2.4,
                }
            }
        }
    )
    monkeypatch.setattr(
        "electric_blue.backends.batch_groq.requests.get",
        _make_get_text_mock(output_jsonl),
    )

    job = JobRef(
        job_id="batch_abc",
        jsonl_file_id="file_xyz",
        staged_url="https://h.ts.net/stage/meeting.mp3",
        output_file_id="file_out123",
    )
    transcript = GroqBatchBackend(stager=StubStager(cfg.batch_funnel_base_url)).fetch(cfg, job)

    assert len(transcript.segments) == 1
    seg = transcript.segments[0]
    assert seg.start == 0.0
    assert seg.end == 2.4
    assert seg.text == "hello"
    assert transcript.info.backend == f"batch:{cfg.api_model}"


# ---------------------------------------------------------------------------
# ASYNC-8: text only, no segments → one synthetic Segment
# ---------------------------------------------------------------------------


def test_async8_fetch_text_only_yields_synthetic_segment(
    cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ASYNC-8: no segments, text present → Segment(start=0.0, end=duration, text=text)."""
    output_jsonl = json.dumps(
        {
            "response": {
                "body": {
                    "text": "hello world",
                    "duration": 3.7,
                    "language": "en",
                }
            }
        }
    )
    monkeypatch.setattr(
        "electric_blue.backends.batch_groq.requests.get",
        _make_get_text_mock(output_jsonl),
    )

    job = JobRef(
        job_id="batch_abc",
        jsonl_file_id="file_xyz",
        staged_url="https://h.ts.net/stage/meeting.mp3",
        output_file_id="file_out123",
    )
    transcript = GroqBatchBackend(stager=StubStager(cfg.batch_funnel_base_url)).fetch(cfg, job)

    assert len(transcript.segments) == 1
    seg = transcript.segments[0]
    assert seg.start == 0.0
    assert seg.end == 3.7
    assert seg.text == "hello world"


# ---------------------------------------------------------------------------
# ASYNC-9: empty batch_api_key → RuntimeError before any requests.post
# ---------------------------------------------------------------------------


def test_async9_empty_api_key_raises_before_network(
    cfg: Config,
    stub_stager: StubStager,
    src_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ASYNC-9: batch_api_key="" → RuntimeError from submit(); requests.post never called."""
    cfg_no_key = dataclasses.replace(cfg, batch_api_key="")
    mock_post = MagicMock()
    monkeypatch.setattr("electric_blue.backends.batch_groq.requests.post", mock_post)
    monkeypatch.setattr("electric_blue.backends.batch_groq.audio.extract", _make_extract_stub())

    with pytest.raises(RuntimeError):
        GroqBatchBackend(stager=stub_stager).submit(cfg_no_key, src_file)

    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# ASYNC-10a: language="fr" → JSONL body contains "language" key
# ASYNC-10b: language=None → no "language" key in JSONL body
# ---------------------------------------------------------------------------


def test_async10a_language_present_in_body_when_set(
    cfg: Config,
    stub_stager: StubStager,
    src_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ASYNC-10a: cfg.language="fr" → JSONL body["language"] == "fr"."""
    cfg_fr = dataclasses.replace(cfg, language="fr")
    mock_post = _make_post_mock()
    monkeypatch.setattr("electric_blue.backends.batch_groq.requests.post", mock_post)
    monkeypatch.setattr("electric_blue.backends.batch_groq.audio.extract", _make_extract_stub())

    GroqBatchBackend(stager=stub_stager).submit(cfg_fr, src_file)

    body = _parse_jsonl_body(mock_post)["body"]
    assert body.get("language") == "fr"


def test_async10b_no_language_key_when_none(
    cfg: Config,
    stub_stager: StubStager,
    src_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ASYNC-10b: cfg.language=None → no "language" key in JSONL body."""
    # cfg fixture sets language=None
    mock_post = _make_post_mock()
    monkeypatch.setattr("electric_blue.backends.batch_groq.requests.post", mock_post)
    monkeypatch.setattr("electric_blue.backends.batch_groq.audio.extract", _make_extract_stub())

    GroqBatchBackend(stager=stub_stager).submit(cfg, src_file)

    body = _parse_jsonl_body(mock_post)["body"]
    assert "language" not in body


# ---------------------------------------------------------------------------
# ASYNC-11: oversize encoded MP3 → RuntimeError before requests.post
# ---------------------------------------------------------------------------


def test_async11_oversize_mp3_raises_before_network(
    cfg: Config,
    stub_stager: StubStager,
    src_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ASYNC-11: encoded MP3 size > batch_max_mb → RuntimeError; requests.post not called."""
    # batch_max_mb=0 so any non-empty file (1 byte / 1e6 = 1e-6 MB > 0) triggers the check
    cfg_tiny_cap = dataclasses.replace(cfg, batch_max_mb=0)
    mock_post = MagicMock()
    monkeypatch.setattr("electric_blue.backends.batch_groq.requests.post", mock_post)
    # Stub writes 1 byte — enough to exceed a 0 MB cap
    monkeypatch.setattr(
        "electric_blue.backends.batch_groq.audio.extract", _make_extract_stub(size_bytes=1)
    )

    with pytest.raises(RuntimeError, match="batch cap"):
        GroqBatchBackend(stager=stub_stager).submit(cfg_tiny_cap, src_file)

    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# ASYNC-12: validating / unknown status → not terminal (conservative policy)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw_status", ["validating", "unknown_future_status"])
def test_async12_unknown_status_not_terminal(
    cfg: Config,
    job_ref: JobRef,
    monkeypatch: pytest.MonkeyPatch,
    raw_status: str,
) -> None:
    """ASYNC-12: unrecognized status → JobStatus(terminal=False, succeeded=False, ...)."""
    monkeypatch.setattr(
        "electric_blue.backends.batch_groq.requests.get",
        _make_get_mock({"status": raw_status}),
    )

    status = GroqBatchBackend(stager=StubStager(cfg.batch_funnel_base_url)).poll(cfg, job_ref)

    assert status.terminal is False
    assert status.succeeded is False
    assert status.output_file_id is None
    assert status.error is None


# ---------------------------------------------------------------------------
# STAG-4: stager.stage() called once; URL appears verbatim in JSONL body
# ---------------------------------------------------------------------------


def test_stag4_stage_called_once_url_verbatim_in_body(
    cfg: Config,
    stub_stager: StubStager,
    src_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STAG-4: stager.stage() called exactly once; its return value is verbatim as body["url"]."""
    mock_post = _make_post_mock()
    monkeypatch.setattr("electric_blue.backends.batch_groq.requests.post", mock_post)
    monkeypatch.setattr("electric_blue.backends.batch_groq.audio.extract", _make_extract_stub())

    GroqBatchBackend(stager=stub_stager).submit(cfg, src_file)

    assert len(stub_stager.stage_calls) == 1
    # Reconstruct expected URL from the recorded path (not by calling stage() again)
    staged_mp3 = stub_stager.stage_calls[0]
    expected_url = f"{cfg.batch_funnel_base_url}/{staged_mp3.name}"

    body = _parse_jsonl_body(mock_post)["body"]
    assert body["url"] == expected_url


# ---------------------------------------------------------------------------
# STAG-7: src stem drives mp3 name and staged URL
# ---------------------------------------------------------------------------


def test_stag7_mp3_name_and_url_match_src_stem(
    cfg: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """STAG-7: src=.../meeting.mp4 → stage() path .name=="meeting.mp3"; URL has that stem."""
    # Use a path that need not exist on disk (audio.extract is mocked)
    src = Path("/batch_inbox/meeting.mp4")
    stub = StubStager(base_url=cfg.batch_funnel_base_url)
    mock_post = _make_post_mock()
    monkeypatch.setattr("electric_blue.backends.batch_groq.requests.post", mock_post)
    monkeypatch.setattr("electric_blue.backends.batch_groq.audio.extract", _make_extract_stub())

    GroqBatchBackend(stager=stub).submit(cfg, src)

    # (a) path passed to stage() has .name == "meeting.mp3"
    assert len(stub.stage_calls) == 1
    assert stub.stage_calls[0].name == "meeting.mp3"

    # (b) URL in JSONL body == f"{batch_funnel_base_url}/meeting.mp3"
    expected_url = f"{cfg.batch_funnel_base_url}/meeting.mp3"
    body = _parse_jsonl_body(mock_post)["body"]
    assert body["url"] == expected_url
