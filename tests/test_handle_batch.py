"""Tests for handle_batch, ensure_batch_dirs, and CLI dispatch (S7 — groq-batch sprint).

AC coverage: SUBMIT-1..8, STAG-6, DRAIN-9, CFG-10, CLI-1
"""

from __future__ import annotations

import dataclasses
import shutil
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

import electric_blue.watcher
from electric_blue.batch_store import JobRecord, JobRef
from electric_blue.config import Config
from electric_blue.watcher import _BatchHandler, ensure_batch_dirs, handle_batch, run_watch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cfg(
    tmp_path: Path,
    *,
    batch_enabled: bool = True,
    funnel_url: str = "https://funnel.example.com",
) -> Config:
    """Return a Config with all dirs under tmp_path; creates all required directories."""
    batch_inbox = tmp_path / "batch_inbox" if batch_enabled else None
    cfg = dataclasses.replace(
        Config.from_env(),
        base_dir=tmp_path,
        input_dir=tmp_path / "inbox",
        output_dir=tmp_path / "transcripts",
        done_dir=tmp_path / "done",
        failed_dir=tmp_path / "failed",
        batch_inbox_dir=batch_inbox,
        batch_submitted_dir=tmp_path / "batch_submitted",
        batch_store_path=tmp_path / "batch_store",
        batch_stage_dir=tmp_path / "batch_stage",
        batch_funnel_base_url=funnel_url,
    )
    for d in (cfg.input_dir, cfg.output_dir, cfg.done_dir, cfg.failed_dir):
        d.mkdir(parents=True, exist_ok=True)
    if batch_inbox is not None:
        batch_inbox.mkdir(parents=True, exist_ok=True)
    cfg.batch_submitted_dir.mkdir(parents=True, exist_ok=True)
    cfg.batch_store_path.mkdir(parents=True, exist_ok=True)
    cfg.batch_stage_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def _job_ref(job_id: str = "batch_abc123") -> JobRef:
    return JobRef(
        job_id=job_id,
        jsonl_file_id="file_jsonl_001",
        staged_url="https://funnel.example.com/staged/test.mp4",
    )


def _record(src_name: str, status: str, job_id: str = "batch_abc123") -> JobRecord:
    return JobRecord(
        job_id=job_id,
        jsonl_file_id="file_jsonl_001",
        staged_url="https://funnel.example.com/staged/test.mp4",
        src_name=src_name,
        src_stem=Path(src_name).stem,
        staged_path=f"/some/batch_submitted/{src_name}",
        status=status,
        submitted_at="2026-06-16T00:00:00+00:00",
        completed_at=None,
        error=None,
    )


# ---------------------------------------------------------------------------
# SUBMIT-1: Execution order — stability → live-record guard → submit → save → move
# ---------------------------------------------------------------------------


def test_submit_1_execution_order(tmp_path, monkeypatch):
    """SUBMIT-1: handle_batch executes steps in correct order:
    is_stable → find_by_src_name → backend.submit → store.save → shutil.move."""
    cfg = _make_cfg(tmp_path)
    recorder: list[str] = []

    monkeypatch.setattr(
        "electric_blue.watcher.is_stable",
        lambda path, s=None: recorder.append("is_stable") or True,
    )

    mock_store = Mock()
    mock_store.find_by_src_name.side_effect = (
        lambda name: recorder.append("find_by_src_name") or None
    )
    mock_store.save.side_effect = lambda rec: recorder.append("store.save")

    mock_backend = Mock()
    mock_backend.submit.side_effect = (
        lambda cfg, path: recorder.append("backend.submit") or _job_ref()
    )

    monkeypatch.setattr(shutil, "move", lambda src, dst: recorder.append("shutil.move"))

    src = cfg.batch_inbox_dir / "clip.mp4"
    src.write_bytes(b"fake media data")

    handle_batch(cfg, src, backend=mock_backend, store=mock_store)

    assert recorder == [
        "is_stable",
        "find_by_src_name",
        "backend.submit",
        "store.save",
        "shutil.move",
    ]


# ---------------------------------------------------------------------------
# SUBMIT-2: run_watch with batch_inbox_dir=None → one observer; no batch handler
# ---------------------------------------------------------------------------


def test_submit_2_run_watch_no_batch_inbox(tmp_path, monkeypatch):
    """SUBMIT-2: run_watch with batch_inbox_dir=None schedules exactly one observer;
    ensure_batch_dirs not called; _BatchHandler not passed to .schedule."""
    cfg = _make_cfg(tmp_path, batch_enabled=False)

    FakeObserver = MagicMock()
    monkeypatch.setattr("watchdog.observers.Observer", FakeObserver)
    monkeypatch.setattr(
        electric_blue.watcher.time,
        "sleep",
        Mock(side_effect=KeyboardInterrupt),
    )

    ensure_batch_dirs_calls: list[bool] = []
    monkeypatch.setattr(
        "electric_blue.watcher.ensure_batch_dirs",
        lambda cfg: ensure_batch_dirs_calls.append(True),
    )

    run_watch(cfg)

    instance = FakeObserver.return_value
    assert instance.schedule.call_count == 1
    assert len(ensure_batch_dirs_calls) == 0

    for c in instance.schedule.call_args_list:
        assert not isinstance(c.args[0], _BatchHandler)


# ---------------------------------------------------------------------------
# SUBMIT-3: Existing live record → submit skipped
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("live_status", ["submitted", "polling"])
def test_submit_3_live_record_skips_submission(tmp_path, monkeypatch, live_status):
    """SUBMIT-3: Existing record with live status (submitted/polling) → submit not called."""
    cfg = _make_cfg(tmp_path)
    monkeypatch.setattr("electric_blue.watcher.is_stable", lambda path, s=None: True)

    mock_store = Mock()
    mock_store.find_by_src_name.return_value = _record("clip.mp4", status=live_status)
    mock_backend = Mock()

    src = cfg.batch_inbox_dir / "clip.mp4"
    src.write_bytes(b"fake media data")

    handle_batch(cfg, src, backend=mock_backend, store=mock_store)

    mock_backend.submit.assert_not_called()


# ---------------------------------------------------------------------------
# SUBMIT-4: Terminal record → submit IS called; new job_id in saved record
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("terminal_status", ["failed", "expired"])
def test_submit_4_terminal_record_allows_resubmission(tmp_path, monkeypatch, terminal_status):
    """SUBMIT-4: Existing terminal record (failed/expired) → submit called; new job_id recorded."""
    cfg = _make_cfg(tmp_path)
    monkeypatch.setattr("electric_blue.watcher.is_stable", lambda path, s=None: True)
    monkeypatch.setattr(shutil, "move", Mock())

    saved: list[JobRecord] = []
    mock_store = Mock()
    mock_store.find_by_src_name.return_value = _record(
        "clip.mp4", status=terminal_status, job_id="batch_old"
    )
    mock_store.save.side_effect = lambda rec: saved.append(rec)

    mock_backend = Mock()
    mock_backend.submit.return_value = _job_ref(job_id="batch_new")

    src = cfg.batch_inbox_dir / "clip.mp4"
    src.write_bytes(b"fake media data")

    handle_batch(cfg, src, backend=mock_backend, store=mock_store)

    mock_backend.submit.assert_called_once()
    assert len(saved) == 1
    assert saved[0].job_id == "batch_new"


# ---------------------------------------------------------------------------
# SUBMIT-5: backend.submit raises → no store record; file→failed_dir; done_dir untouched
# ---------------------------------------------------------------------------


def test_submit_5_submit_raises_moves_to_failed(tmp_path, monkeypatch):
    """SUBMIT-5: backend.submit raises → store.save not called; file moved to failed_dir;
    done_dir untouched (INV-1)."""
    cfg = _make_cfg(tmp_path)
    monkeypatch.setattr("electric_blue.watcher.is_stable", lambda path, s=None: True)

    mock_store = Mock()
    mock_store.find_by_src_name.return_value = None
    mock_backend = Mock()
    mock_backend.submit.side_effect = RuntimeError("Groq API error")

    src = cfg.batch_inbox_dir / "clip.mp4"
    src.write_bytes(b"fake media data")

    handle_batch(cfg, src, backend=mock_backend, store=mock_store)

    mock_store.save.assert_not_called()
    assert (cfg.failed_dir / "clip.mp4").exists()
    assert not (cfg.batch_submitted_dir / "clip.mp4").exists()
    assert list(cfg.done_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# SUBMIT-6: store.save ok; shutil.move raises → record persists; live-record guard works
# ---------------------------------------------------------------------------


def test_submit_6_move_raises_record_persists_guard_works(tmp_path, monkeypatch):
    """SUBMIT-6: shutil.move raises after store.save → record exists with staged_path==DESTINATION;
    second handle_batch call detects live record and skips re-submission."""
    cfg = _make_cfg(tmp_path)
    monkeypatch.setattr("electric_blue.watcher.is_stable", lambda path, s=None: True)

    saved: list[JobRecord] = []
    mock_store = Mock()
    mock_store.find_by_src_name.return_value = None
    mock_store.save.side_effect = lambda rec: saved.append(rec)

    mock_backend = Mock()
    mock_backend.submit.return_value = _job_ref()

    move_calls: list[tuple[str, str]] = []

    def _mock_move(src: str, dst: str) -> None:
        move_calls.append((src, dst))
        if len(move_calls) == 1:
            raise OSError("disk full")

    monkeypatch.setattr(shutil, "move", _mock_move)

    src = cfg.batch_inbox_dir / "clip.mp4"
    src.write_bytes(b"fake media data")

    handle_batch(cfg, src, backend=mock_backend, store=mock_store)

    # Record saved with DESTINATION staged_path before move was attempted
    assert len(saved) == 1
    assert saved[0].status == "submitted"
    assert saved[0].staged_path == str(cfg.batch_submitted_dir / "clip.mp4")

    # Second call: live-record guard detects submitted record → skip re-submission
    mock_store.find_by_src_name.return_value = saved[0]

    handle_batch(cfg, src, backend=mock_backend, store=mock_store)

    assert mock_backend.submit.call_count == 1  # not called a second time


# ---------------------------------------------------------------------------
# SUBMIT-7: Non-media suffix → returns immediately; no submit/save/move
# ---------------------------------------------------------------------------


def test_submit_7_non_media_suffix_skipped(tmp_path, monkeypatch):
    """SUBMIT-7: File with non-media suffix → handle_batch returns immediately;
    submit, save, and move are never called."""
    cfg = _make_cfg(tmp_path)
    mock_store = Mock()
    mock_backend = Mock()
    mock_move = Mock()
    monkeypatch.setattr(shutil, "move", mock_move)

    src = cfg.batch_inbox_dir / "notes.txt"
    src.write_text("not a media file")

    handle_batch(cfg, src, backend=mock_backend, store=mock_store)

    mock_backend.submit.assert_not_called()
    mock_store.save.assert_not_called()
    mock_move.assert_not_called()


# ---------------------------------------------------------------------------
# SUBMIT-8: staged_path == DESTINATION (batch_submitted_dir / path.name)
# ---------------------------------------------------------------------------


def test_submit_8_staged_path_is_destination(tmp_path, monkeypatch):
    """SUBMIT-8: store.save receives record where staged_path == DESTINATION path
    (cfg.batch_submitted_dir / path.name), set unconditionally before shutil.move."""
    cfg = _make_cfg(tmp_path)
    monkeypatch.setattr("electric_blue.watcher.is_stable", lambda path, s=None: True)
    monkeypatch.setattr(shutil, "move", Mock())

    saved: list[JobRecord] = []
    mock_store = Mock()
    mock_store.find_by_src_name.return_value = None
    mock_store.save.side_effect = lambda rec: saved.append(rec)

    mock_backend = Mock()
    mock_backend.submit.return_value = _job_ref()

    src = cfg.batch_inbox_dir / "meeting.mp4"
    src.write_bytes(b"fake media data")

    handle_batch(cfg, src, backend=mock_backend, store=mock_store)

    assert len(saved) == 1
    assert saved[0].staged_path == str(cfg.batch_submitted_dir / "meeting.mp4")


# ---------------------------------------------------------------------------
# STAG-6: backend.submit raises (simulating stager failure) → no record; file→failed_dir
# ---------------------------------------------------------------------------


def test_stag_6_stager_raises_propagates_to_failed(tmp_path, monkeypatch):
    """STAG-6: backend.submit raises (stager.stage() failure propagated through submit) →
    no JobRecord written; source file moved to failed_dir; error logged."""
    cfg = _make_cfg(tmp_path)
    monkeypatch.setattr("electric_blue.watcher.is_stable", lambda path, s=None: True)

    mock_store = Mock()
    mock_store.find_by_src_name.return_value = None
    mock_backend = Mock()
    mock_backend.submit.side_effect = RuntimeError("stager.stage() failed: connection refused")

    src = cfg.batch_inbox_dir / "video.mp4"
    src.write_bytes(b"fake media data")

    handle_batch(cfg, src, backend=mock_backend, store=mock_store)

    mock_store.save.assert_not_called()
    assert (cfg.failed_dir / "video.mp4").exists()


# ---------------------------------------------------------------------------
# CFG-10: ensure_batch_dirs — empty funnel URL raises; non-empty creates dirs
# ---------------------------------------------------------------------------


def test_cfg_10_empty_funnel_url_raises(tmp_path):
    """CFG-10 (negative): ensure_batch_dirs raises RuntimeError when batch_funnel_base_url
    is empty — primary B1 startup guard."""
    cfg = _make_cfg(tmp_path, funnel_url="")

    with pytest.raises(RuntimeError, match="TRANSCRIBE_BATCH_FUNNEL_URL"):
        ensure_batch_dirs(cfg)


def test_cfg_10_non_empty_funnel_url_creates_dirs(tmp_path):
    """CFG-10 (positive): ensure_batch_dirs with non-empty funnel URL creates all
    batch directories (inbox, submitted, stage, store)."""
    batch_root = tmp_path / "fresh_batch"  # none of these subdirs exist yet
    cfg = dataclasses.replace(
        Config.from_env(),
        batch_inbox_dir=batch_root / "inbox",
        batch_submitted_dir=batch_root / "submitted",
        batch_store_path=batch_root / "store",
        batch_stage_dir=batch_root / "stage",
        batch_funnel_base_url="https://funnel.example.com",
    )

    ensure_batch_dirs(cfg)

    assert (batch_root / "inbox").is_dir()
    assert (batch_root / "submitted").is_dir()
    assert (batch_root / "store").is_dir()
    assert (batch_root / "stage").is_dir()


# ---------------------------------------------------------------------------
# DRAIN-9: --drain-batch CLI dispatch patches electric_blue.drain module attribute
# ---------------------------------------------------------------------------


def test_drain_9_cli_drain_batch_dispatch(monkeypatch):
    """DRAIN-9: --drain-batch CLI dispatch uses lazy 'from .drain import drain_batch';
    patching electric_blue.drain.drain_batch (the module attr) intercepts the call."""
    import electric_blue.cli
    import electric_blue.drain  # ensure module loaded before patching

    mock_drain = Mock()
    monkeypatch.setattr("electric_blue.drain.drain_batch", mock_drain)
    monkeypatch.setattr(sys, "argv", ["electric-blue", "--drain-batch"])
    monkeypatch.setattr("electric_blue.watcher.ensure_dirs", Mock())

    electric_blue.cli.main()

    mock_drain.assert_called_once()
    call_args = mock_drain.call_args.args
    assert len(call_args) == 1
    assert isinstance(call_args[0], Config)


# ---------------------------------------------------------------------------
# CLI-1: --file flag passes exactly 3 args (cfg, Path, datetime) — no TypeError
# ---------------------------------------------------------------------------


def test_cli_1_file_flag_passes_datetime(monkeypatch):
    """CLI-1: --file fix passes (cfg, Path, datetime) to process; no TypeError raised.
    Pre-fix call was process(cfg, Path) — missing started_at caused TypeError."""
    import electric_blue.cli

    mock_process = Mock()
    monkeypatch.setattr("electric_blue.watcher.process", mock_process)
    monkeypatch.setattr("electric_blue.watcher.ensure_dirs", Mock())
    monkeypatch.setattr(sys, "argv", ["electric-blue", "--file", "/tmp/meeting.mp4"])

    electric_blue.cli.main()

    mock_process.assert_called_once()
    args = mock_process.call_args.args
    assert len(args) == 3
    assert isinstance(args[0], Config)
    assert args[1] == Path("/tmp/meeting.mp4")
    assert isinstance(args[2], datetime)
