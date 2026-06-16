"""Tests for staging.py — STAG-1..3 acceptance criteria (DDR-03 / S4).

All tests are hermetic: tmp_path only, no network, no subprocess.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from electric_blue.config import Config
from electric_blue.staging import FunnelStager, UrlStager, make_stager

# ---------------------------------------------------------------------------
# STAG-1
# ---------------------------------------------------------------------------


def test_stag1_protocol_structural(tmp_path: Path) -> None:
    """STAG-1: UrlStager is a Protocol; FunnelStager satisfies it structurally via isinstance."""
    stager = FunnelStager(stage_dir=tmp_path / "stage", base_url="https://host.ts.net/stage")
    assert isinstance(stager, UrlStager)


# ---------------------------------------------------------------------------
# STAG-2
# ---------------------------------------------------------------------------


def test_stag2_stage_copies_file_and_returns_url(tmp_path: Path) -> None:
    """STAG-2: stage(path) copies the file to stage_dir and returns a URL with only the filename.

    (a) stage_dir / path.name exists after stage().
    (b) Returned URL == "https://host.ts.net/stage/meeting.mp3"; no absolute filesystem
        path component is present in the URL (INV-7).
    """
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    src_file = src_dir / "meeting.mp3"
    src_file.write_bytes(b"audio-data")

    stage_dir = tmp_path / "stage"
    stager = FunnelStager(stage_dir=stage_dir, base_url="https://host.ts.net/stage")

    url = stager.stage(src_file)

    # (a) file copied to stage_dir
    assert (stage_dir / "meeting.mp3").exists()

    # (b) URL is the expected public URL with filename only
    assert url == "https://host.ts.net/stage/meeting.mp3"

    # (b) the source directory path must NOT appear in the URL
    assert str(src_dir) not in url


# ---------------------------------------------------------------------------
# STAG-3
# ---------------------------------------------------------------------------


def test_stag3_unstage_deletes_file_and_is_idempotent(tmp_path: Path) -> None:
    """STAG-3: unstage(url) deletes the staged file; a second call does not raise (idempotent)."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    src_file = src_dir / "meeting.mp3"
    src_file.write_bytes(b"audio-data")

    stage_dir = tmp_path / "stage"
    stager = FunnelStager(stage_dir=stage_dir, base_url="https://host.ts.net/stage")

    url = stager.stage(src_file)
    staged_path = stage_dir / "meeting.mp3"
    assert staged_path.exists()

    stager.unstage(url)
    assert not staged_path.exists()

    # Second call must not raise
    stager.unstage(url)


# ---------------------------------------------------------------------------
# make_stager guard (CFG-10 / INV-2 startup guard; primary test in S7)
# ---------------------------------------------------------------------------


def test_make_stager_raises_on_empty_base_url(tmp_path: Path) -> None:
    """make_stager raises RuntimeError when cfg.batch_funnel_base_url is empty."""
    cfg = dataclasses.replace(
        Config.from_env(),
        batch_funnel_base_url="",
        batch_stage_dir=tmp_path / "stage",
    )
    with pytest.raises(RuntimeError, match="TRANSCRIBE_BATCH_FUNNEL_URL"):
        make_stager(cfg)
