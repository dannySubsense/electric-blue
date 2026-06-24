"""Diarize-pipeline test module for DDR-05 (whisperx-diarization).

Tests grow slice by slice across S1–S7. Each section is labelled with its slice.
S1: foundation — ConfigurationError importability.
S2: characterization tests — baseline behavior of Segment.to_dict() and write_outputs().
"""

from __future__ import annotations

import os

import pytest

from electric_blue.config import Config
from electric_blue.models import Segment, TranscriptInfo
from electric_blue.outputs import write_outputs

# ── S1 — exceptions.py ────────────────────────────────────────────────────────


def test_configuration_error_importable():
    """S1: ConfigurationError is importable and is a subclass of Exception."""
    from electric_blue.exceptions import ConfigurationError

    assert issubclass(ConfigurationError, Exception) is True


# ── S2 — Characterization tests (baseline behavior lock) ─────────────────────


@pytest.fixture()
def char_cfg(tmp_path):
    """Config with all four output formats enabled; output_dir at tmp_path/out."""
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    env_backup = {}
    overrides = {
        "TRANSCRIBE_BASE": str(tmp_path),
        "TRANSCRIBE_OUTPUT": str(out_dir),
    }
    for k, v in overrides.items():
        env_backup[k] = os.environ.get(k)
        os.environ[k] = v
    cfg = Config.from_env()
    yield cfg, out_dir
    for k, v in env_backup.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture()
def char_segments():
    """Two no-speaker Segment instances using the current three-arg constructor."""
    return [
        Segment(0.0, 2.5, "hello world"),
        Segment(2.5, 5.0, "goodbye world"),
    ]


@pytest.fixture()
def char_info():
    """Minimal TranscriptInfo for characterization tests."""
    return TranscriptInfo(
        language="en", language_probability=0.99, duration=5.0, backend="local:tiny"
    )


def test_char_segment_to_dict_no_speaker_field():
    """S2: Segment.to_dict() returns exactly the three-field dict with no 'speaker' key."""
    result = Segment(0.0, 1.0, "hello").to_dict()
    assert result == {"start": 0.0, "end": 1.0, "text": "hello"}
    assert "speaker" not in result


def test_char_srt_no_speaker_prefix(char_cfg, char_segments, char_info):
    """S2: SRT output for no-speaker segments contains no '[SPEAKER_' substring."""
    cfg, out_dir = char_cfg
    write_outputs(cfg, out_dir, "char_clip", char_segments, char_info)
    srt_content = (out_dir / "char_clip.srt").read_text(encoding="utf-8")
    assert "[SPEAKER_" not in srt_content


def test_char_vtt_no_speaker_prefix(char_cfg, char_segments, char_info):
    """S2: VTT output for no-speaker segments contains no '[SPEAKER_' substring."""
    cfg, out_dir = char_cfg
    write_outputs(cfg, out_dir, "char_clip", char_segments, char_info)
    vtt_content = (out_dir / "char_clip.vtt").read_text(encoding="utf-8")
    assert "[SPEAKER_" not in vtt_content


def test_char_txt_no_speaker_prefix(char_cfg, char_segments, char_info):
    """S2: TXT output for no-speaker segments contains no '[SPEAKER_' substring."""
    cfg, out_dir = char_cfg
    write_outputs(cfg, out_dir, "char_clip", char_segments, char_info)
    txt_content = (out_dir / "char_clip.txt").read_text(encoding="utf-8")
    assert "[SPEAKER_" not in txt_content
