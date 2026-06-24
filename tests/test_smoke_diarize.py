"""
Diarize smoke test — real whisperX + pyannote pipeline → four output files.

Marked @pytest.mark.diarize_smoke; excluded from make gate, run only manually or
via pytest -m diarize_smoke with HF_TOKEN set and [diarize] installed.
Importable without whisperx installed and without HF_TOKEN set — skip guards live
inside the test body, not at module level.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest


def _locate_ffmpeg():
    import shutil

    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe:
            return exe
    except Exception:
        pass
    return None


@pytest.mark.diarize_smoke
def test_diarize_smoke_end_to_end(tmp_path, monkeypatch):
    # Skip guards — must be first in the test body so the file always collects cleanly.
    pytest.importorskip("whisperx")
    if not os.environ.get("HF_TOKEN"):
        pytest.skip("HF_TOKEN not set")

    ffmpeg_bin = _locate_ffmpeg()
    if ffmpeg_bin is None:
        pytest.skip("ffmpeg not found on PATH or via imageio-ffmpeg")

    # Set environment so Config.from_env() builds a diarize/cpu/int8 config.
    monkeypatch.setenv("WHISPER_BACKEND", "diarize")
    monkeypatch.setenv("WHISPER_MODEL", "tiny")
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("WHISPER_COMPUTE", "int8")
    monkeypatch.setenv("TRANSCRIBE_BASE", str(tmp_path))
    monkeypatch.setenv("FFMPEG_BIN", ffmpeg_bin)
    # HF_TOKEN is already in the environment (guard above confirmed it).

    # Generate a 5-second sine WAV with a ~1s silence gap centred at 2.5 s.
    # A single lavfi source with a volume=0 window is the most portable approach.
    wav = tmp_path / "diarize_test.wav"
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=5:sample_rate=16000",
            "-af",
            "volume=enable='between(t,2,3)':volume=0",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert wav.exists() and wav.stat().st_size > 0

    # Import electric_blue pieces inside the test body, after all skip guards.
    from electric_blue.backends.diarize import WhisperXBackend
    from electric_blue.config import Config
    from electric_blue.outputs import write_outputs

    cfg = Config.from_env()
    backend = WhisperXBackend(cfg)

    # Assertion 1: pipeline completes without exception.
    result = backend.transcribe(cfg, wav)

    # Assertion 2: result is a Transcript with .segments and .info.
    assert hasattr(result, "segments"), "Transcript missing .segments"
    assert hasattr(result, "info"), "Transcript missing .info"

    # Assertion 3: backend tag starts with "diarize:".
    assert result.info.backend.startswith(
        "diarize:"
    ), f"Expected info.backend to start with 'diarize:', got {result.info.backend!r}"

    # Assertion 4: backend tag is "diarize:<model>" — exactly two colon-separated parts.
    assert (
        len(result.info.backend.split(":")) == 2
    ), f"Expected 'diarize:<model>' format, got {result.info.backend!r}"

    # Assertion 5: write_outputs writes all four files (txt/srt/vtt/json).
    out_dir = tmp_path / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_outputs(cfg, out_dir, "diarize_test", result.segments, result.info)
    for ext in ("txt", "srt", "vtt", "json"):
        p = out_dir / f"diarize_test.{ext}"
        assert p.exists(), f"Missing output file: diarize_test.{ext}"

    # Assertion 6: JSON output has schema_version == 1.
    json_path = out_dir / "diarize_test.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert (
        data["schema_version"] == 1
    ), f"Expected schema_version 1, got {data.get('schema_version')!r}"
