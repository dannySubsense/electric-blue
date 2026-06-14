"""Tests for is_stable, ensure_dirs, and handle routing."""

from __future__ import annotations

import os

from electric_blue.config import Config
from electric_blue.watcher import ensure_dirs, handle, is_stable


def make_cfg(tmp_dirs: dict) -> Config:
    """Build a Config pointing at the fixture tmp dirs."""
    env_backup = {}
    overrides = {
        "TRANSCRIBE_BASE": str(tmp_dirs["base"]),
        "TRANSCRIBE_INPUT": str(tmp_dirs["input"]),
        "TRANSCRIBE_OUTPUT": str(tmp_dirs["output"]),
        "TRANSCRIBE_DONE": str(tmp_dirs["done"]),
        "TRANSCRIBE_FAILED": str(tmp_dirs["failed"]),
    }
    for k, v in overrides.items():
        env_backup[k] = os.environ.get(k)
        os.environ[k] = v
    cfg = Config.from_env()
    for k, v in env_backup.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return cfg


# ---------------------------------------------------------------------------
# ensure_dirs
# ---------------------------------------------------------------------------


def test_ensure_dirs_creates_all(tmp_path):
    dirs = {
        "base": tmp_path,
        "input": tmp_path / "inbox",
        "output": tmp_path / "transcripts",
        "done": tmp_path / "done",
        "failed": tmp_path / "failed",
    }
    cfg = make_cfg(dirs)
    # Remove them so we can verify creation
    for d in [dirs["input"], dirs["output"], dirs["done"], dirs["failed"]]:
        d.rmdir() if d.exists() else None
    ensure_dirs(cfg)
    for d in [dirs["input"], dirs["output"], dirs["done"], dirs["failed"]]:
        assert d.is_dir()


# ---------------------------------------------------------------------------
# is_stable
# ---------------------------------------------------------------------------


def test_is_stable_stable_file(tmp_path):
    f = tmp_path / "a.wav"
    f.write_bytes(b"x" * 1024)
    # Use near-zero stability window so the test is fast
    assert is_stable(f, stability_seconds=0.05) is True


def test_is_stable_missing_file(tmp_path):
    assert is_stable(tmp_path / "nonexistent.wav", stability_seconds=0.05) is False


def test_is_stable_empty_file(tmp_path):
    f = tmp_path / "empty.wav"
    f.write_bytes(b"")
    assert is_stable(f, stability_seconds=0.05) is False


# ---------------------------------------------------------------------------
# handle routing (with monkeypatched transcribe)
# ---------------------------------------------------------------------------


def test_handle_success_moves_to_done(tmp_dirs, fake_transcribe, monkeypatch):
    cfg = make_cfg(tmp_dirs)
    # Override stability so test is fast
    monkeypatch.setattr("electric_blue.watcher.is_stable", lambda path, s=None: True)

    src = tmp_dirs["input"] / "clip.mp4"
    src.write_bytes(b"fake video data")

    handle(cfg, src)

    assert not src.exists()
    assert (tmp_dirs["done"] / "clip.mp4").exists()
    # Check all four output files were written
    for ext in ("txt", "srt", "vtt", "json"):
        assert (tmp_dirs["output"] / f"clip.{ext}").exists()


def test_handle_failure_moves_to_failed(tmp_dirs, monkeypatch):
    cfg = make_cfg(tmp_dirs)
    monkeypatch.setattr("electric_blue.watcher.is_stable", lambda path, s=None: True)

    def _bad_transcribe(cfg, src):
        raise RuntimeError("backend exploded")

    monkeypatch.setattr("electric_blue.watcher.transcribe", _bad_transcribe)

    src = tmp_dirs["input"] / "clip.mp4"
    src.write_bytes(b"fake video data")

    handle(cfg, src)

    assert not src.exists()
    assert (tmp_dirs["failed"] / "clip.mp4").exists()


def test_handle_ignores_non_media(tmp_dirs, fake_transcribe, monkeypatch):
    cfg = make_cfg(tmp_dirs)
    monkeypatch.setattr("electric_blue.watcher.is_stable", lambda path, s=None: True)

    src = tmp_dirs["input"] / "notes.txt"
    src.write_text("not a media file")

    handle(cfg, src)

    # File should remain untouched
    assert src.exists()
    assert not list(tmp_dirs["done"].iterdir())


def test_handle_ignores_unstable_file(tmp_dirs, fake_transcribe, monkeypatch):
    cfg = make_cfg(tmp_dirs)
    monkeypatch.setattr("electric_blue.watcher.is_stable", lambda path, s=None: False)

    src = tmp_dirs["input"] / "clip.mp4"
    src.write_bytes(b"partial data")

    handle(cfg, src)

    assert src.exists()
    assert not list(tmp_dirs["done"].iterdir())
