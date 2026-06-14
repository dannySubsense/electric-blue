"""Hermetic tests for fmt_ts and all four output writers."""

from __future__ import annotations

import json

import pytest

from electric_blue.models import Segment, TranscriptInfo
from electric_blue.outputs import fmt_ts, write_outputs

# ---------------------------------------------------------------------------
# fmt_ts
# ---------------------------------------------------------------------------


def test_fmt_ts_zero():
    assert fmt_ts(0.0, ",") == "00:00:00,000"


def test_fmt_ts_comma_sep():
    # 1h 2m 3.456s → 01:02:03,456
    seconds = 3600 + 2 * 60 + 3.456
    assert fmt_ts(seconds, ",") == "01:02:03,456"


def test_fmt_ts_dot_sep():
    assert fmt_ts(61.5, ".") == "00:01:01,500".replace(",", ".")


def test_fmt_ts_rounding():
    # 1.9995 s → 1999.5ms rounds to 2000ms = 00:00:02,000
    assert fmt_ts(1.9995, ",") == "00:00:02,000"


# ---------------------------------------------------------------------------
# write_outputs
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_data():
    segments = [
        Segment(start=0.0, end=1.5, text="Hello world."),
        Segment(start=1.5, end=3.0, text="Goodbye."),
    ]
    info = TranscriptInfo(
        language="en", language_probability=0.99, duration=3.0, backend="local:tiny"
    )
    return segments, info


@pytest.fixture()
def cfg_with_output(tmp_path):
    """Config pointing output_dir at tmp_path."""
    import os

    from electric_blue.config import Config

    env_backup = {}
    overrides = {
        "TRANSCRIBE_BASE": str(tmp_path),
        "TRANSCRIBE_OUTPUT": str(tmp_path / "out"),
    }
    for k, v in overrides.items():
        env_backup[k] = os.environ.get(k)
        os.environ[k] = v
    cfg = Config.from_env()
    yield cfg, tmp_path / "out"
    for k, v in env_backup.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_txt_content(cfg_with_output, sample_data):
    cfg, out_dir = cfg_with_output
    out_dir.mkdir(parents=True, exist_ok=True)
    segments, info = sample_data
    write_outputs(cfg, out_dir, "clip", segments, info)
    txt = (out_dir / "clip.txt").read_text()
    assert "Hello world." in txt
    assert "Goodbye." in txt
    assert txt.endswith("\n")


def test_srt_structure(cfg_with_output, sample_data):
    cfg, out_dir = cfg_with_output
    out_dir.mkdir(parents=True, exist_ok=True)
    segments, info = sample_data
    write_outputs(cfg, out_dir, "clip", segments, info)
    srt = (out_dir / "clip.srt").read_text()
    lines = srt.split("\n")
    assert lines[0] == "1"
    assert "-->" in lines[1]
    assert "Hello world." in lines[2]


def test_vtt_header(cfg_with_output, sample_data):
    cfg, out_dir = cfg_with_output
    out_dir.mkdir(parents=True, exist_ok=True)
    segments, info = sample_data
    write_outputs(cfg, out_dir, "clip", segments, info)
    vtt = (out_dir / "clip.vtt").read_text()
    assert vtt.startswith("WEBVTT")
    assert "-->" in vtt


def test_json_shape(cfg_with_output, sample_data):
    cfg, out_dir = cfg_with_output
    out_dir.mkdir(parents=True, exist_ok=True)
    segments, info = sample_data
    write_outputs(cfg, out_dir, "clip", segments, info)
    data = json.loads((out_dir / "clip.json").read_text())
    assert data["language"] == "en"
    assert data["duration"] == 3.0
    assert data["backend"] == "local:tiny"
    assert "text" in data
    assert isinstance(data["segments"], list)
    assert data["segments"][0]["start"] == 0.0
    assert data["segments"][0]["text"] == "Hello world."


def test_all_four_files_created(cfg_with_output, sample_data):
    cfg, out_dir = cfg_with_output
    out_dir.mkdir(parents=True, exist_ok=True)
    segments, info = sample_data
    write_outputs(cfg, out_dir, "clip", segments, info)
    for ext in ("txt", "srt", "vtt", "json"):
        assert (out_dir / f"clip.{ext}").exists(), f"Missing clip.{ext}"


def test_json_schema_version(cfg_with_output, sample_data):
    cfg, out_dir = cfg_with_output
    out_dir.mkdir(parents=True, exist_ok=True)
    segments, info = sample_data
    write_outputs(cfg, out_dir, "clip", segments, info)
    data = json.loads((out_dir / "clip.json").read_text())
    assert data["schema_version"] == 1
    assert isinstance(data["schema_version"], int)
