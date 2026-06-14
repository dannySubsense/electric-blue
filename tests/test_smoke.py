"""
Smoke test — real ffmpeg clip + real local tiny model → four output files.

Marked @pytest.mark.smoke; excluded from make gate, included in make smoke.
Skips cleanly if faster_whisper or ffmpeg are unavailable.
"""

from __future__ import annotations

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


@pytest.mark.smoke
def test_real_transcription(tmp_path, monkeypatch):
    pytest.importorskip(
        "faster_whisper", reason="faster_whisper not installed — skipping smoke test"
    )

    ffmpeg_bin = _locate_ffmpeg()
    if ffmpeg_bin is None:
        pytest.skip("ffmpeg not found on PATH or via imageio-ffmpeg — skipping smoke test")

    # Set FFMPEG_BIN so the package uses the located binary
    monkeypatch.setenv("FFMPEG_BIN", ffmpeg_bin)
    monkeypatch.setenv("WHISPER_BACKEND", "local")
    monkeypatch.setenv("WHISPER_MODEL", "tiny")
    monkeypatch.setenv("TRANSCRIBE_BASE", str(tmp_path))

    # Generate a ~3s sine-wave clip
    clip = tmp_path / "sine.wav"
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(clip),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert clip.exists() and clip.stat().st_size > 0

    from electric_blue.backends import transcribe
    from electric_blue.config import Config
    from electric_blue.outputs import write_outputs

    cfg = Config.from_env()
    out_dir = tmp_path / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)

    segments, info = transcribe(cfg, clip)

    write_outputs(cfg, out_dir, "sine", segments, info)

    for ext in ("txt", "srt", "vtt", "json"):
        p = out_dir / f"sine.{ext}"
        assert p.exists(), f"Missing output file: sine.{ext}"

    assert info.duration > 0, f"Expected duration > 0, got {info.duration}"
    assert info.backend.startswith("local:"), f"Unexpected backend: {info.backend}"
    assert info.language is not None
