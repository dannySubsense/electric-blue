"""Characterization tests for groq-batch S1 — pin pre-change behavior.

Five tests (CHAR-1..5) cover the observable behaviors touched by the
groq-batch sprint.  All must remain green at every slice boundary (S2–S7).
No production file is modified by this module.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock

import electric_blue.watcher
from electric_blue.backends.api import ApiBackend
from electric_blue.backends.local import LocalBackend
from electric_blue.config import Config
from electric_blue.watcher import handle, run_watch

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_cfg(tmp_path: Path) -> Config:
    """Return a Config with all dir fields under tmp_path; creates the directories."""
    cfg = dataclasses.replace(
        Config.from_env(),
        base_dir=tmp_path,
        input_dir=tmp_path / "inbox",
        output_dir=tmp_path / "transcripts",
        done_dir=tmp_path / "done",
        failed_dir=tmp_path / "failed",
    )
    for d in (cfg.input_dir, cfg.output_dir, cfg.done_dir, cfg.failed_dir):
        d.mkdir(parents=True, exist_ok=True)
    return cfg


# ---------------------------------------------------------------------------
# CHAR-1
# ---------------------------------------------------------------------------


def test_char_handle_success(tmp_path, monkeypatch):
    """CHAR-1: handle(cfg, path) with process() succeeding → file moved to done_dir.

    Survives S2–S7: handle() success path is unchanged by this sprint.
    """
    cfg = _make_cfg(tmp_path)
    monkeypatch.setattr("electric_blue.watcher.is_stable", lambda path, s=None: True)
    monkeypatch.setattr("electric_blue.watcher.process", lambda cfg, src, started_at: None)

    src = cfg.input_dir / "clip.mp4"
    src.write_bytes(b"fake")

    handle(cfg, src)

    assert (cfg.done_dir / "clip.mp4").exists()
    assert list(cfg.failed_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# CHAR-2
# ---------------------------------------------------------------------------


def test_char_handle_failure(tmp_path, monkeypatch):
    """CHAR-2: handle(cfg, path) with process() raising → file moved to failed_dir.

    Survives S2–S7: handle() failure path is unchanged by this sprint.
    """
    cfg = _make_cfg(tmp_path)
    monkeypatch.setattr("electric_blue.watcher.is_stable", lambda path, s=None: True)
    monkeypatch.setattr(
        "electric_blue.watcher.process",
        Mock(side_effect=RuntimeError("backend boom")),
    )

    src = cfg.input_dir / "clip.mp4"
    src.write_bytes(b"fake")

    handle(cfg, src)

    assert (cfg.failed_dir / "clip.mp4").exists()
    assert list(cfg.done_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# CHAR-3
# ---------------------------------------------------------------------------


def test_char_single_observer_when_no_batch(tmp_path, monkeypatch):
    """CHAR-3: run_watch(cfg) with no batch_inbox_dir schedules exactly one observer.

    Two patches prevent the test from hanging:
    (1) watchdog.observers.Observer replaced by FakeObserver (MagicMock) — no real thread.
        run_watch does 'from watchdog.observers import Observer' at function entry, so
        patching watchdog.observers.Observer is the correct interception point.
    (2) electric_blue.watcher.time.sleep raises KeyboardInterrupt on first call, driving
        run_watch into its except branch (obs.stop()) and returning normally.

    Survives S2–S7: after S2 adds batch_inbox_dir=None default and S7 adds the
    conditional batch observer branch, None still yields schedule count == 1.
    """
    cfg = _make_cfg(tmp_path)

    FakeObserver = MagicMock()
    monkeypatch.setattr("watchdog.observers.Observer", FakeObserver)
    monkeypatch.setattr(
        electric_blue.watcher.time,
        "sleep",
        Mock(side_effect=KeyboardInterrupt),
    )

    run_watch(cfg)

    instance = FakeObserver.return_value
    assert instance.schedule.call_count == 1
    assert instance.start.called
    assert instance.stop.called


# ---------------------------------------------------------------------------
# CHAR-4
# ---------------------------------------------------------------------------


def test_char_capabilities_existing_fields():
    """CHAR-4: LocalBackend and ApiBackend expose expected Capabilities field values.

    Survives S2: does not assert the absence of is_async; the test remains green
    after S2 adds is_async: bool = False to Capabilities.
    """
    local_cap = LocalBackend.capabilities
    api_cap = ApiBackend.capabilities

    # LocalBackend expected values
    assert local_cap.supports_diarization is False
    assert local_cap.max_upload_mb is None
    assert local_cap.needs_network is False
    assert local_cap.needs_gpu_recommended is True

    # ApiBackend expected values
    assert api_cap.supports_diarization is False
    assert api_cap.max_upload_mb == 24
    assert api_cap.needs_network is True
    assert api_cap.needs_gpu_recommended is False


# ---------------------------------------------------------------------------
# CHAR-5
# ---------------------------------------------------------------------------


def test_char_cli_dispatch(monkeypatch):
    """CHAR-5: cli.main() dispatch — default→run_watch, --once→run_once, --file→process.

    Pins the pre-S7 dispatch behavior (INV-3 pin for cli.py).  Three sub-cases
    verified sequentially.  Mock targets are attributes on electric_blue.watcher
    because main() binds them via a lazy 'from .watcher import ...' at call time.

    Partially survives S7: default and --once dispatch are unchanged after S7 adds
    --drain-batch and fixes --file.  CHAR-5 does not assert that --drain-batch is
    absent, so S7's addition of that branch does not break this test.
    """
    import electric_blue.cli

    mock_run_watch = Mock()
    mock_run_once = Mock()
    mock_process = Mock()
    mock_ensure_dirs = Mock()

    monkeypatch.setattr("electric_blue.watcher.run_watch", mock_run_watch)
    monkeypatch.setattr("electric_blue.watcher.run_once", mock_run_once)
    monkeypatch.setattr("electric_blue.watcher.process", mock_process)
    monkeypatch.setattr("electric_blue.watcher.ensure_dirs", mock_ensure_dirs)

    # default: no flags → run_watch(cfg) called
    monkeypatch.setattr(sys, "argv", ["electric-blue"])
    electric_blue.cli.main()
    assert mock_run_watch.called
    assert not mock_run_once.called
    assert not mock_process.called
    mock_run_watch.reset_mock()

    # --once → run_once(cfg) called
    monkeypatch.setattr(sys, "argv", ["electric-blue", "--once"])
    electric_blue.cli.main()
    assert mock_run_once.called
    assert not mock_run_watch.called
    assert not mock_process.called
    mock_run_once.reset_mock()

    # --file → process called; path appears in positional args (count not asserted)
    monkeypatch.setattr(sys, "argv", ["electric-blue", "--file", "/tmp/x.mp4"])
    electric_blue.cli.main()
    assert mock_process.called
    assert not mock_run_watch.called
    assert not mock_run_once.called
    assert Path("/tmp/x.mp4") in mock_process.call_args.args
