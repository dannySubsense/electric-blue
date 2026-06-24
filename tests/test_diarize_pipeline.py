"""Diarize-pipeline test module for DDR-05 (whisperx-diarization).

Tests grow slice by slice across S1–S7. Each section is labelled with its slice.
S1: foundation — ConfigurationError importability.
S2: characterization tests — baseline behavior of Segment.to_dict() and write_outputs().
"""

from __future__ import annotations

import logging
import os

import pytest

from electric_blue.config import Config
from electric_blue.exceptions import ConfigurationError
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


# ── S3 — Segment.speaker field ────────────────────────────────────────────────


def test_segment_to_dict_omits_speaker_when_none():
    """S3: to_dict() has no 'speaker' key when speaker is absent or explicitly None."""
    result_positional = Segment(0.0, 1.0, "x").to_dict()
    assert "speaker" not in result_positional

    result_kwarg = Segment(0.0, 1.0, "x", speaker=None).to_dict()
    assert "speaker" not in result_kwarg


def test_segment_to_dict_includes_speaker_when_set():
    """S3: to_dict() includes 'speaker' key with correct value when speaker is set."""
    result = Segment(0.0, 1.0, "x", speaker="SPEAKER_00").to_dict()
    assert result["speaker"] == "SPEAKER_00"


# ── S4 — Diarize fields in config.py ─────────────────────────────────────────


def test_config_hf_token_default_empty(monkeypatch):
    """S4: HF_TOKEN unset → cfg.hf_token == ""."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    cfg = Config.from_env()
    assert cfg.hf_token == ""


def test_config_diarize_num_speakers_default_none(monkeypatch):
    """S4: WHISPER_DIARIZE_NUM_SPEAKERS unset → cfg.diarize_num_speakers is None."""
    monkeypatch.delenv("WHISPER_DIARIZE_NUM_SPEAKERS", raising=False)
    cfg = Config.from_env()
    assert cfg.diarize_num_speakers is None


def test_config_num_speakers_valid(monkeypatch):
    """S4: WHISPER_DIARIZE_NUM_SPEAKERS=2 → cfg.diarize_num_speakers == 2, isinstance int."""
    monkeypatch.setenv("WHISPER_DIARIZE_NUM_SPEAKERS", "2")
    cfg = Config.from_env()
    assert cfg.diarize_num_speakers == 2
    assert isinstance(cfg.diarize_num_speakers, int)


def test_config_invalid_num_speakers_zero(monkeypatch):
    """S4: WHISPER_DIARIZE_NUM_SPEAKERS=0 → ConfigurationError from Config.from_env()."""
    monkeypatch.setenv("WHISPER_DIARIZE_NUM_SPEAKERS", "0")
    with pytest.raises(ConfigurationError):
        Config.from_env()


def test_config_invalid_num_speakers_negative(monkeypatch):
    """S4: WHISPER_DIARIZE_NUM_SPEAKERS=-1 → ConfigurationError."""
    monkeypatch.setenv("WHISPER_DIARIZE_NUM_SPEAKERS", "-1")
    with pytest.raises(ConfigurationError):
        Config.from_env()


def test_config_invalid_num_speakers_string(monkeypatch):
    """S4: WHISPER_DIARIZE_NUM_SPEAKERS=two → ConfigurationError."""
    monkeypatch.setenv("WHISPER_DIARIZE_NUM_SPEAKERS", "two")
    with pytest.raises(ConfigurationError):
        Config.from_env()


def test_config_hf_token_not_logged(monkeypatch, caplog):
    """S4: HF_TOKEN value never appears in any log output during Config.from_env() (INV-7)."""
    monkeypatch.setenv("HF_TOKEN", "hf-secret-xyz")
    with caplog.at_level(logging.DEBUG):
        Config.from_env()
    assert "hf-secret-xyz" not in caplog.text


# ── S5 — Speaker prefix rendering in outputs.py ──────────────────────────────


@pytest.fixture()
def diarize_segments_00():
    """Two segments with speaker='SPEAKER_00'."""
    return [
        Segment(0.0, 2.5, "hello world", speaker="SPEAKER_00"),
        Segment(2.5, 5.0, "goodbye world", speaker="SPEAKER_00"),
    ]


@pytest.fixture()
def diarize_segments_01():
    """Two segments with speaker='SPEAKER_01'."""
    return [
        Segment(0.0, 2.5, "hello world", speaker="SPEAKER_01"),
        Segment(2.5, 5.0, "goodbye world", speaker="SPEAKER_01"),
    ]


def test_srt_speaker_prefix(char_cfg, char_info, diarize_segments_00):
    """S5: SRT cue text for speaker='SPEAKER_00' starts with '[SPEAKER_00]'."""
    cfg, out_dir = char_cfg
    write_outputs(cfg, out_dir, "s5_srt", diarize_segments_00, char_info)
    srt_content = (out_dir / "s5_srt.srt").read_text(encoding="utf-8")
    cue_lines = [
        line
        for line in srt_content.splitlines()
        if line and not line.isdigit() and "-->" not in line
    ]
    assert cue_lines, "No cue lines found in SRT output"
    assert all(line.startswith("[SPEAKER_00]") for line in cue_lines)


def test_vtt_speaker_prefix(char_cfg, char_info, diarize_segments_01):
    """S5: VTT cue text for speaker='SPEAKER_01' starts with '[SPEAKER_01]'."""
    cfg, out_dir = char_cfg
    write_outputs(cfg, out_dir, "s5_vtt", diarize_segments_01, char_info)
    vtt_content = (out_dir / "s5_vtt.vtt").read_text(encoding="utf-8")
    cue_lines = [
        line for line in vtt_content.splitlines() if line and line != "WEBVTT" and "-->" not in line
    ]
    assert cue_lines, "No cue lines found in VTT output"
    assert all(line.startswith("[SPEAKER_01]") for line in cue_lines)


def test_txt_no_speaker_prefix(char_cfg, char_info, diarize_segments_00):
    """S5: TXT output for diarized segments contains no '[SPEAKER_' substring."""
    cfg, out_dir = char_cfg
    write_outputs(cfg, out_dir, "s5_txt", diarize_segments_00, char_info)
    txt_content = (out_dir / "s5_txt.txt").read_text(encoding="utf-8")
    assert "[SPEAKER_" not in txt_content


def test_json_speaker_field_present(char_cfg, char_info, diarize_segments_00):
    """S5: JSON segment dict has 'speaker' key when diarized; value matches label."""
    import json

    cfg, out_dir = char_cfg
    write_outputs(cfg, out_dir, "s5_json", diarize_segments_00, char_info)
    data = json.loads((out_dir / "s5_json.json").read_text(encoding="utf-8"))
    for seg in data["segments"]:
        assert "speaker" in seg
        assert seg["speaker"] == "SPEAKER_00"


def test_json_schema_version_still_1(char_cfg, char_info, diarize_segments_00):
    """S5: data['schema_version'] == 1 for diarized output (INV-10)."""
    import json

    cfg, out_dir = char_cfg
    write_outputs(cfg, out_dir, "s5_schema", diarize_segments_00, char_info)
    data = json.loads((out_dir / "s5_schema.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1


def test_no_speaker_output_identical(char_cfg, char_info, tmp_path):
    """S5: all-None speaker list produces byte-for-byte identical output to 3-arg form.

    Two segment lists — one built with 3-arg positional form, one with speaker=None kwarg
    — are written to separate dirs. All four output files must match byte-for-byte,
    proving that speaker=None changes nothing relative to the pre-S3 call form.
    """
    cfg, _ = char_cfg
    dir1 = tmp_path / "positional"
    dir2 = tmp_path / "none_kwarg"
    dir1.mkdir()
    dir2.mkdir()

    segs_positional = [
        Segment(0.0, 2.5, "hello world"),
        Segment(2.5, 5.0, "goodbye world"),
    ]
    segs_none_kwarg = [
        Segment(0.0, 2.5, "hello world", speaker=None),
        Segment(2.5, 5.0, "goodbye world", speaker=None),
    ]

    write_outputs(cfg, dir1, "clip", segs_positional, char_info)
    write_outputs(cfg, dir2, "clip", segs_none_kwarg, char_info)

    for ext in ("srt", "vtt", "txt", "json"):
        content1 = (dir1 / f"clip.{ext}").read_bytes()
        content2 = (dir2 / f"clip.{ext}").read_bytes()
        assert (
            content1 == content2
        ), f"{ext} output differs between positional and speaker=None forms"
