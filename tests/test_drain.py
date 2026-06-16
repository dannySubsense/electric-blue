"""Tests for drain.py — DRAIN-1..8, DRAIN-10, HOOK-1..3, FAIL-1..4, STAG-5, CFG-9 (DDR-03 / S6).

All tests are hermetic: tmp_path only; MockAsyncBackend + StubStager injected via DI;
store seeded via real make_store(cfg) (SidecarBatchStore is disk-based; two instances
on the same path share state via the filesystem). DRAIN-6 monkeypatches make_store to
wrap the real store's update method.

Mock seams:
    electric_blue.drain.notify        — HOOK-1/2/3
    electric_blue.drain.write_outputs — most tests (monkeypatched to no-op or recorder)
    electric_blue.drain.make_store    — DRAIN-6, DRAIN-10 (wrapped/stubbed)
    shutil.move                       — DRAIN-3 (wrapped to track ordering)
"""

from __future__ import annotations

import dataclasses
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from electric_blue.backends.base import Capabilities, Transcript
from electric_blue.batch_store import JobRecord, JobStatus, make_store
from electric_blue.config import Config
from electric_blue.drain import drain_batch
from electric_blue.models import Segment, TranscriptInfo

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class MockAsyncBackend:
    """Scripted backend: poll() serves queued JobStatus values; fetch() returns Transcript."""

    name = "mock-batch"
    capabilities = Capabilities(
        supports_diarization=False,
        max_upload_mb=None,
        needs_network=True,
        needs_gpu_recommended=False,
        is_async=True,
    )

    def __init__(
        self,
        poll_statuses: list[JobStatus],
        fetch_result: Transcript | None = None,
        calls: list | None = None,
    ) -> None:
        self._poll_iter = iter(poll_statuses)
        self._fetch_result = fetch_result
        self._calls: list = calls if calls is not None else []

    def poll(self, cfg: Config, job_ref) -> JobStatus:
        self._calls.append(("poll", job_ref.job_id))
        return next(self._poll_iter)

    def fetch(self, cfg: Config, job_ref) -> Transcript:
        self._calls.append(("fetch", job_ref.job_id))
        if self._fetch_result is None:
            raise AssertionError("fetch() called unexpectedly on non-success path")
        return self._fetch_result


class StubStager:
    """Records stage()/unstage(); optionally raises on unstage (FAIL-4)."""

    def __init__(self, raise_on_unstage: bool = False, calls: list | None = None) -> None:
        self.stage_calls: list[Path] = []
        self.unstage_calls: list[str] = []
        self._raise = raise_on_unstage
        self._calls: list = calls if calls is not None else []

    def stage(self, path: Path) -> str:
        self.stage_calls.append(path)
        return f"https://example.com/{path.name}"

    def unstage(self, url: str) -> None:
        self.unstage_calls.append(url)
        self._calls.append("unstage")
        if self._raise:
            raise RuntimeError("unstage intentionally failed")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_STAGED_URL = "https://example.com/staged/meeting.mp4"


def _make_transcript() -> Transcript:
    return Transcript(
        segments=[Segment(start=0.0, end=3.0, text="hello world")],
        info=TranscriptInfo(
            language="en",
            language_probability=0.99,
            duration=3.0,
            backend="batch:whisper-large-v3-turbo",
        ),
    )


def _make_cfg(tmp_path: Path, batch_inbox_dir_none: bool = False) -> Config:
    bi = tmp_path / "bi"
    if not batch_inbox_dir_none:
        bi.mkdir(parents=True, exist_ok=True)
    (tmp_path / "out").mkdir(parents=True, exist_ok=True)
    (tmp_path / "done").mkdir(parents=True, exist_ok=True)
    (tmp_path / "failed").mkdir(parents=True, exist_ok=True)

    return dataclasses.replace(
        Config.from_env(),
        batch_inbox_dir=None if batch_inbox_dir_none else bi,
        output_dir=tmp_path / "out",
        done_dir=tmp_path / "done",
        failed_dir=tmp_path / "failed",
        batch_store_path=tmp_path / "store",
        batch_completion_window="24h",
        notify_webhook="",
        batch_api_key="gk-test-secret",
    )


def _seed_record(
    cfg: Config,
    tmp_path: Path,
    *,
    job_id: str = "batch_abc",
    src_name: str = "meeting.mp4",
    src_stem: str = "meeting",
    status: str = "polling",
    submitted_at: str = "2026-06-16T12:00:00+00:00",
    staged_dir_name: str = "staged",
    create_staged_file: bool = True,
) -> JobRecord:
    """Create a real staged file and persist a JobRecord via make_store(cfg).save()."""
    staged_dir = tmp_path / staged_dir_name
    staged_dir.mkdir(parents=True, exist_ok=True)
    staged_file = staged_dir / src_name
    if create_staged_file:
        staged_file.write_bytes(b"fake-audio")

    record = JobRecord(
        job_id=job_id,
        jsonl_file_id="file_jsonl_001",
        staged_url=_STAGED_URL,
        src_name=src_name,
        src_stem=src_stem,
        staged_path=str(staged_file),
        status=status,
        submitted_at=submitted_at,
        completed_at=None,
        error=None,
    )
    make_store(cfg).save(record)
    return record


# ---------------------------------------------------------------------------
# cfg fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def cfg(tmp_path: Path) -> Config:
    return _make_cfg(tmp_path)


# ---------------------------------------------------------------------------
# DRAIN-1: 2 pending records → poll called exactly twice
# ---------------------------------------------------------------------------


def test_drain1_poll_called_for_each_pending(
    cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DRAIN-1: list_pending() returns 2 records → poll() called exactly twice."""
    monkeypatch.setattr("electric_blue.drain.write_outputs", MagicMock(return_value={}))

    # Two pending records with separate staged dirs to avoid filename collision
    staged_a = tmp_path / "staged_a"
    staged_a.mkdir()
    (staged_a / "meeting.mp4").write_bytes(b"a")
    staged_b = tmp_path / "staged_b"
    staged_b.mkdir()
    (staged_b / "talk.mp4").write_bytes(b"b")

    store = make_store(cfg)
    store.save(
        JobRecord(
            job_id="batch_a",
            jsonl_file_id="f1",
            staged_url=_STAGED_URL,
            src_name="meeting.mp4",
            src_stem="meeting",
            staged_path=str(staged_a / "meeting.mp4"),
            status="polling",
            submitted_at="2026-06-16T12:00:00+00:00",
            completed_at=None,
            error=None,
        )
    )
    store.save(
        JobRecord(
            job_id="batch_b",
            jsonl_file_id="f2",
            staged_url=_STAGED_URL,
            src_name="talk.mp4",
            src_stem="talk",
            staged_path=str(staged_b / "talk.mp4"),
            status="polling",
            submitted_at="2026-06-16T12:00:00+00:00",
            completed_at=None,
            error=None,
        )
    )

    not_terminal = JobStatus(
        raw="in_progress", terminal=False, succeeded=False, output_file_id=None, error=None
    )
    backend = MockAsyncBackend(poll_statuses=[not_terminal, not_terminal])

    drain_batch(cfg, backend=backend, stager=StubStager())

    poll_calls = [c for c in backend._calls if c[0] == "poll"]
    assert len(poll_calls) == 2


# ---------------------------------------------------------------------------
# DRAIN-2: terminal=False → store.update(status="polling"); record stays pending
# ---------------------------------------------------------------------------


def test_drain2_non_terminal_updates_to_polling(
    cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DRAIN-2: poll returns terminal=False → store.update(status="polling"); record stays in list_pending()."""
    record = _seed_record(cfg, tmp_path, status="submitted")

    not_terminal = JobStatus(
        raw="in_progress", terminal=False, succeeded=False, output_file_id=None, error=None
    )
    drain_batch(cfg, backend=MockAsyncBackend([not_terminal]), stager=StubStager())

    updated = make_store(cfg).get(record.job_id)
    assert updated is not None
    assert updated.status == "polling"
    pending_ids = {r.job_id for r in make_store(cfg).list_pending()}
    assert record.job_id in pending_ids


# ---------------------------------------------------------------------------
# DRAIN-3: success path ordering (INV-1)
# ---------------------------------------------------------------------------


def test_drain3_success_path_ordering(
    cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DRAIN-3: success → fetch, write_outputs, move, update(completed), unstage, hook in order."""
    transcript = _make_transcript()
    success_status = JobStatus(
        raw="completed", terminal=True, succeeded=True, output_file_id="file_out", error=None
    )

    order: list[str] = []

    # Build real store with tracking wrapper
    real_store = make_store(cfg)
    record = _seed_record(cfg, tmp_path)  # seeds via separate make_store instance (same disk)
    original_update = real_store.update

    def _track_update(job_id: str, **kwargs) -> None:
        if kwargs.get("status") == "completed":
            order.append("update_completed")
        else:
            order.append(f"update_{kwargs.get('status', '?')}")
        original_update(job_id, **kwargs)

    real_store.update = _track_update  # type: ignore[method-assign]
    monkeypatch.setattr("electric_blue.drain.make_store", lambda _cfg: real_store)

    class _TrackingBackend(MockAsyncBackend):
        def fetch(self, cfg, job_ref):
            order.append("fetch")
            return transcript

    backend = _TrackingBackend(poll_statuses=[success_status], fetch_result=transcript, calls=[])

    # Track write_outputs
    def _track_write(cfg, out_dir, stem, segments, info):
        order.append("write_outputs")
        return {}

    monkeypatch.setattr("electric_blue.drain.write_outputs", _track_write)

    # Track shutil.move
    real_move = shutil.move

    def _track_move(src, dst):
        order.append("move")
        return real_move(src, dst)

    monkeypatch.setattr(shutil, "move", _track_move)

    # Track notify
    def _track_notify(c, payload):
        order.append("notify")

    monkeypatch.setattr("electric_blue.drain.notify", _track_notify)

    # Track unstage via shared order list
    stager = StubStager(calls=order)

    drain_batch(cfg, backend=backend, stager=stager)

    # Assert ordering: fetch < write_outputs < move < update_completed < unstage < notify
    assert "fetch" in order
    assert "write_outputs" in order
    assert "move" in order
    assert "update_completed" in order
    assert "unstage" in order
    assert "notify" in order

    assert order.index("fetch") < order.index("write_outputs")
    assert order.index("write_outputs") < order.index("move")
    assert order.index("move") < order.index("update_completed")
    assert order.index("update_completed") < order.index("unstage")
    assert order.index("unstage") < order.index("notify")

    # Filesystem: staged gone, done_dir has file
    assert (cfg.done_dir / record.src_name).exists()
    assert not Path(record.staged_path).exists()

    # Store: completed
    final = real_store.get(record.job_id)
    assert final is not None
    assert final.status == "completed"
    assert final.completed_at is not None


# ---------------------------------------------------------------------------
# DRAIN-4: terminal not succeeded → fetch NOT called; staged→failed; update; done_dir untouched
# ---------------------------------------------------------------------------


def test_drain4_failure_path(cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DRAIN-4: terminal non-success → fetch not called; staged→failed_dir; store updated; done_dir untouched."""
    record = _seed_record(cfg, tmp_path)
    monkeypatch.setattr("electric_blue.drain.write_outputs", MagicMock(return_value={}))
    monkeypatch.setattr("electric_blue.drain.notify", MagicMock())

    failed_status = JobStatus(
        raw="failed", terminal=True, succeeded=False, output_file_id=None, error="provider failed"
    )
    backend = MockAsyncBackend(poll_statuses=[failed_status], fetch_result=None)
    stager = StubStager()

    drain_batch(cfg, backend=backend, stager=stager)

    # fetch NOT called
    assert not any(c[0] == "fetch" for c in backend._calls)

    # staged moved to failed_dir; done_dir untouched
    assert (cfg.failed_dir / record.src_name).exists()
    assert not Path(record.staged_path).exists()
    assert not (cfg.done_dir / record.src_name).exists()

    # store updated
    updated = make_store(cfg).get(record.job_id)
    assert updated is not None
    assert updated.status == "failed"
    assert updated.error is not None


# ---------------------------------------------------------------------------
# DRAIN-5: idempotent — second run re-fetches; staged.exists guard prevents double-move
# ---------------------------------------------------------------------------


def test_drain5_idempotent_second_run(
    cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DRAIN-5: second drain on same success record → write_outputs overwrites; no double-move."""
    record = _seed_record(cfg, tmp_path)
    transcript = _make_transcript()
    success_status = JobStatus(
        raw="completed", terminal=True, succeeded=True, output_file_id="file_out", error=None
    )
    monkeypatch.setattr("electric_blue.drain.notify", MagicMock())

    # First run
    backend1 = MockAsyncBackend(poll_statuses=[success_status], fetch_result=transcript)
    drain_batch(cfg, backend=backend1, stager=StubStager())

    assert (cfg.done_dir / record.src_name).exists()
    assert make_store(cfg).get(record.job_id).status == "completed"

    # Reset record to polling to re-enter list_pending (simulates partial state)
    make_store(cfg).update(record.job_id, status="polling", completed_at=None)
    assert not Path(record.staged_path).exists()  # file already moved

    # Second run: staged.exists() is False → no second move; write_outputs overwrites
    backend2 = MockAsyncBackend(poll_statuses=[success_status], fetch_result=transcript)
    stager2 = StubStager()
    drain_batch(cfg, backend=backend2, stager=stager2)

    # fetch called again (re-fetch)
    assert any(c[0] == "fetch" for c in backend2._calls)

    # Final state: completed; done_dir file still there (not double-moved)
    assert (cfg.done_dir / record.src_name).exists()
    final = make_store(cfg).get(record.job_id)
    assert final is not None
    assert final.status == "completed"


# ---------------------------------------------------------------------------
# DRAIN-6: crash between move and update → no data loss; second run recovers
# ---------------------------------------------------------------------------


def test_drain6_crash_between_move_and_update_no_data_loss(
    cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DRAIN-6: store.update raises after move → record stays polling → second drain re-fetches safely."""
    transcript = _make_transcript()
    success_status = JobStatus(
        raw="completed", terminal=True, succeeded=True, output_file_id="file_out", error=None
    )

    # Build real store, seed record
    real_store = make_store(cfg)
    record = _seed_record(cfg, tmp_path)  # seeds via disk

    original_update = real_store.update
    raise_count = {"n": 0}

    def _flaky_update(job_id: str, **kwargs) -> None:
        if kwargs.get("status") == "completed" and raise_count["n"] == 0:
            raise_count["n"] += 1
            raise RuntimeError("simulated crash between move and update")
        original_update(job_id, **kwargs)

    real_store.update = _flaky_update  # type: ignore[method-assign]
    monkeypatch.setattr("electric_blue.drain.make_store", lambda _cfg: real_store)
    monkeypatch.setattr("electric_blue.drain.write_outputs", MagicMock(return_value={}))
    monkeypatch.setattr("electric_blue.drain.notify", MagicMock())

    # First drain: update raises → logged as per-job error; staged already moved
    backend1 = MockAsyncBackend(poll_statuses=[success_status], fetch_result=transcript)
    drain_batch(cfg, backend=backend1, stager=StubStager())

    assert (cfg.done_dir / record.src_name).exists()
    assert not Path(record.staged_path).exists()
    # Record still polling (update raised before writing)
    assert real_store.get(record.job_id).status == "polling"

    # Restore update so second run succeeds
    real_store.update = original_update  # type: ignore[method-assign]

    # Second drain: re-polls → re-fetches → staged.exists() False → no second move → update OK
    backend2 = MockAsyncBackend(poll_statuses=[success_status], fetch_result=transcript)
    drain_batch(cfg, backend=backend2, stager=StubStager())

    assert any(c[0] == "fetch" for c in backend2._calls)
    final = real_store.get(record.job_id)
    assert final is not None
    assert final.status == "completed"


# ---------------------------------------------------------------------------
# DRAIN-7: poll raises for job A → error logged; status unchanged; job B processed
# ---------------------------------------------------------------------------


def test_drain7_per_job_exception_isolation(
    cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """DRAIN-7: poll raises for job A → error logged; status unchanged; job B processed."""
    monkeypatch.setattr("electric_blue.drain.write_outputs", MagicMock(return_value={}))
    monkeypatch.setattr("electric_blue.drain.notify", MagicMock())

    staged_a = tmp_path / "staged_a"
    staged_a.mkdir()
    (staged_a / "meeting.mp4").write_bytes(b"a")

    staged_b = tmp_path / "staged_b"
    staged_b.mkdir()
    (staged_b / "talk.mp4").write_bytes(b"b")

    store = make_store(cfg)
    store.save(
        JobRecord(
            job_id="batch_a",
            jsonl_file_id="f1",
            staged_url=_STAGED_URL,
            src_name="meeting.mp4",
            src_stem="meeting",
            staged_path=str(staged_a / "meeting.mp4"),
            status="polling",
            submitted_at="2026-06-16T12:00:00+00:00",
            completed_at=None,
            error=None,
        )
    )
    store.save(
        JobRecord(
            job_id="batch_b",
            jsonl_file_id="f2",
            staged_url=_STAGED_URL,
            src_name="talk.mp4",
            src_stem="talk",
            staged_path=str(staged_b / "talk.mp4"),
            status="polling",
            submitted_at="2026-06-16T12:00:00+00:00",
            completed_at=None,
            error=None,
        )
    )

    success_status = JobStatus(
        raw="completed", terminal=True, succeeded=True, output_file_id="file_out", error=None
    )
    transcript = _make_transcript()

    class _IsolationBackend:
        name = "isolation"
        capabilities = MockAsyncBackend.capabilities

        def __init__(self) -> None:
            self._calls: list = []

        def poll(self, cfg, job_ref):
            self._calls.append(("poll", job_ref.job_id))
            if job_ref.job_id == "batch_a":
                raise RuntimeError("network error for batch_a")
            return success_status

        def fetch(self, cfg, job_ref):
            self._calls.append(("fetch", job_ref.job_id))
            return transcript

    backend = _IsolationBackend()

    with caplog.at_level(logging.ERROR, logger="electric_blue"):
        drain_batch(cfg, backend=backend, stager=StubStager())

    # Error logged for batch_a
    assert "batch_a" in caplog.text

    # batch_a status unchanged (still polling)
    record_a = make_store(cfg).get("batch_a")
    assert record_a is not None
    assert record_a.status == "polling"

    # batch_b processed successfully
    record_b = make_store(cfg).get("batch_b")
    assert record_b is not None
    assert record_b.status == "completed"


# ---------------------------------------------------------------------------
# DRAIN-8: expiry warning at 80% of window; both "24h" and "7d" thresholds verified
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "window_str, threshold_hours",
    [("24h", 19.2), ("7d", 134.4)],
)
def test_drain8_expiry_warning_scales_with_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    window_str: str,
    threshold_hours: float,
) -> None:
    """DRAIN-8: submitted_at older than 80% of window → WARNING with job_id; threshold scales."""
    cfg = dataclasses.replace(_make_cfg(tmp_path), batch_completion_window=window_str)

    # submitted_at is 1 hour past the threshold → must warn
    age_hours = threshold_hours + 1.0
    submitted_at = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat(
        timespec="seconds"
    )

    record = _seed_record(cfg, tmp_path, submitted_at=submitted_at)

    not_terminal = JobStatus(
        raw="in_progress", terminal=False, succeeded=False, output_file_id=None, error=None
    )

    with caplog.at_level(logging.WARNING, logger="electric_blue"):
        drain_batch(
            cfg,
            backend=MockAsyncBackend(poll_statuses=[not_terminal]),
            stager=StubStager(),
        )

    assert record.job_id in caplog.text
    # Message contains expiry/threshold indicators
    lowered = caplog.text.lower()
    assert "expir" in lowered or "threshold" in lowered or "approaching" in lowered


# ---------------------------------------------------------------------------
# DRAIN-10: batch_inbox_dir None → returns immediately; no store access
# ---------------------------------------------------------------------------


def test_drain10_none_batch_inbox_returns_immediately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DRAIN-10: cfg.batch_inbox_dir is None → drain_batch returns immediately; make_store not called."""
    cfg = _make_cfg(tmp_path, batch_inbox_dir_none=True)
    assert cfg.batch_inbox_dir is None

    mock_make_store = MagicMock()
    monkeypatch.setattr("electric_blue.drain.make_store", mock_make_store)

    backend = MockAsyncBackend(poll_statuses=[])
    drain_batch(cfg, backend=backend, stager=StubStager())

    mock_make_store.assert_not_called()
    assert backend._calls == []


# ---------------------------------------------------------------------------
# HOOK-1: success → notify called with schema_version=1, file, job_id, backend, status, event
# ---------------------------------------------------------------------------


def test_hook1_notify_called_with_correct_payload(
    cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HOOK-1: success → notify(cfg, payload) with required batch_done fields; requests.post not called (empty webhook)."""
    record = _seed_record(cfg, tmp_path)
    transcript = _make_transcript()
    captured: list[dict] = []

    monkeypatch.setattr("electric_blue.drain.notify", lambda c, p: captured.append(p))
    monkeypatch.setattr("electric_blue.drain.write_outputs", MagicMock(return_value={}))

    mock_post = MagicMock()
    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)

    success_status = JobStatus(
        raw="completed", terminal=True, succeeded=True, output_file_id="file_out", error=None
    )
    drain_batch(
        cfg,
        backend=MockAsyncBackend(poll_statuses=[success_status], fetch_result=transcript),
        stager=StubStager(),
    )

    assert len(captured) == 1
    payload = captured[0]
    assert payload["schema_version"] == 1
    assert payload["event"] == "batch_done"
    assert payload["file"] == record.src_name
    assert payload["job_id"] == record.job_id
    assert payload["backend"] == transcript.info.backend
    assert "status" in payload

    # notify_webhook="" → requests.post never called
    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# HOOK-2: notify raises → caught + logged WARNING; drain still completes update
# ---------------------------------------------------------------------------


def test_hook2_notify_raises_caught_drain_continues(
    cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """HOOK-2: notify raises inside _fire_completion_hook → caught; WARNING logged; drain continues."""
    record = _seed_record(cfg, tmp_path)
    transcript = _make_transcript()

    def _raising_notify(c, payload):
        raise RuntimeError("webhook unreachable")

    monkeypatch.setattr("electric_blue.drain.notify", _raising_notify)
    monkeypatch.setattr("electric_blue.drain.write_outputs", MagicMock(return_value={}))

    success_status = JobStatus(
        raw="completed", terminal=True, succeeded=True, output_file_id="file_out", error=None
    )

    with caplog.at_level(logging.WARNING, logger="electric_blue"):
        drain_batch(
            cfg,
            backend=MockAsyncBackend(poll_statuses=[success_status], fetch_result=transcript),
            stager=StubStager(),
        )

    # WARNING logged; no exception raised
    assert "hook" in caplog.text.lower() or "completion" in caplog.text.lower()

    # Drain completed the store update despite the hook failure
    updated = make_store(cfg).get(record.job_id)
    assert updated is not None
    assert updated.status == "completed"


# ---------------------------------------------------------------------------
# HOOK-3: notify_webhook="" → requests.post never called through hook path
# ---------------------------------------------------------------------------


def test_hook3_empty_webhook_requests_post_never_called(
    cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HOOK-3: notify_webhook="" → requests.post never invoked through the hook path."""
    assert cfg.notify_webhook == ""

    _seed_record(cfg, tmp_path)
    transcript = _make_transcript()

    mock_post = MagicMock()
    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)
    monkeypatch.setattr("electric_blue.drain.write_outputs", MagicMock(return_value={}))

    success_status = JobStatus(
        raw="completed", terminal=True, succeeded=True, output_file_id="file_out", error=None
    )
    drain_batch(
        cfg,
        backend=MockAsyncBackend(poll_statuses=[success_status], fetch_result=transcript),
        stager=StubStager(),
    )

    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# FAIL-1: raw="failed" → staged→failed_dir; update(status=failed, error non-None); unstage called
# ---------------------------------------------------------------------------


def test_fail1_raw_failed(cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FAIL-1: poll returns raw="failed" → staged→failed_dir; update(failed,error!=None); unstage called."""
    record = _seed_record(cfg, tmp_path)
    monkeypatch.setattr("electric_blue.drain.write_outputs", MagicMock(return_value={}))
    monkeypatch.setattr("electric_blue.drain.notify", MagicMock())

    failed_status = JobStatus(
        raw="failed", terminal=True, succeeded=False, output_file_id=None, error="provider error"
    )
    stager = StubStager()
    drain_batch(cfg, backend=MockAsyncBackend(poll_statuses=[failed_status]), stager=stager)

    assert (cfg.failed_dir / record.src_name).exists()
    assert not Path(record.staged_path).exists()

    updated = make_store(cfg).get(record.job_id)
    assert updated is not None
    assert updated.status == "failed"
    assert updated.error is not None

    assert record.staged_url in stager.unstage_calls


# ---------------------------------------------------------------------------
# FAIL-2: raw="expired" → staged→failed_dir; update(status=expired, error non-None); unstage called
# ---------------------------------------------------------------------------


def test_fail2_raw_expired(cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FAIL-2: poll returns raw="expired" → staged→failed_dir; update(expired,error!=None); unstage called."""
    record = _seed_record(cfg, tmp_path)
    monkeypatch.setattr("electric_blue.drain.write_outputs", MagicMock(return_value={}))
    monkeypatch.setattr("electric_blue.drain.notify", MagicMock())

    expired_status = JobStatus(
        raw="expired", terminal=True, succeeded=False, output_file_id=None, error=None
    )
    stager = StubStager()
    drain_batch(cfg, backend=MockAsyncBackend(poll_statuses=[expired_status]), stager=stager)

    assert (cfg.failed_dir / record.src_name).exists()

    updated = make_store(cfg).get(record.job_id)
    assert updated is not None
    assert updated.status == "expired"
    assert updated.error is not None

    assert record.staged_url in stager.unstage_calls


# ---------------------------------------------------------------------------
# FAIL-3: staged missing on failure path → WARNING; no FileNotFoundError; drain continues
# ---------------------------------------------------------------------------


def test_fail3_staged_missing_warning_no_error(
    cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """FAIL-3: staged file absent when moving to failed_dir → WARNING; no FileNotFoundError; drain continues."""
    record = _seed_record(cfg, tmp_path, create_staged_file=False)
    monkeypatch.setattr("electric_blue.drain.write_outputs", MagicMock(return_value={}))
    monkeypatch.setattr("electric_blue.drain.notify", MagicMock())

    failed_status = JobStatus(
        raw="failed", terminal=True, succeeded=False, output_file_id=None, error="err"
    )

    with caplog.at_level(logging.WARNING, logger="electric_blue"):
        drain_batch(
            cfg,
            backend=MockAsyncBackend(poll_statuses=[failed_status]),
            stager=StubStager(),
        )

    lowered = caplog.text.lower()
    assert "missing" in lowered or "staged" in lowered

    # Store still updated despite missing staged file
    updated = make_store(cfg).get(record.job_id)
    assert updated is not None
    assert updated.status == "failed"


# ---------------------------------------------------------------------------
# FAIL-4: unstage raises on both success and failure paths → caught; WARNING; drain continues
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("succeeded", [True, False], ids=["success_path", "failure_path"])
def test_fail4_unstage_raises_caught_drain_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    succeeded: bool,
) -> None:
    """FAIL-4: stager.unstage raises on both paths → caught; WARNING; drain continues."""
    cfg = _make_cfg(tmp_path)
    transcript = _make_transcript()
    record = _seed_record(cfg, tmp_path)

    if succeeded:
        status = JobStatus(
            raw="completed", terminal=True, succeeded=True, output_file_id="file_out", error=None
        )
        backend = MockAsyncBackend(poll_statuses=[status], fetch_result=transcript)
    else:
        status = JobStatus(
            raw="failed", terminal=True, succeeded=False, output_file_id=None, error="err"
        )
        backend = MockAsyncBackend(poll_statuses=[status], fetch_result=None)

    monkeypatch.setattr("electric_blue.drain.write_outputs", MagicMock(return_value={}))
    monkeypatch.setattr("electric_blue.drain.notify", MagicMock())

    with caplog.at_level(logging.WARNING, logger="electric_blue"):
        drain_batch(cfg, backend=backend, stager=StubStager(raise_on_unstage=True))

    assert "unstage" in caplog.text.lower()

    # Store update succeeded despite unstage failure
    updated = make_store(cfg).get(record.job_id)
    assert updated is not None
    expected_status = "completed" if succeeded else "failed"
    assert updated.status == expected_status


# ---------------------------------------------------------------------------
# STAG-5: terminal state → unstage(record.staged_url) called exactly once per job
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, succeeded, use_transcript",
    [
        ("completed", True, True),
        ("failed", False, False),
        ("expired", False, False),
    ],
    ids=["completed", "failed", "expired"],
)
def test_stag5_unstage_called_once_per_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    succeeded: bool,
    use_transcript: bool,
) -> None:
    """STAG-5: terminal completed/failed/expired → unstage(record.staged_url) called exactly once."""
    cfg = _make_cfg(tmp_path)
    record = _seed_record(cfg, tmp_path)
    transcript = _make_transcript() if use_transcript else None

    status = JobStatus(
        raw=raw,
        terminal=True,
        succeeded=succeeded,
        output_file_id="file_out" if succeeded else None,
        error=None,
    )
    backend = MockAsyncBackend(poll_statuses=[status], fetch_result=transcript)

    monkeypatch.setattr("electric_blue.drain.write_outputs", MagicMock(return_value={}))
    monkeypatch.setattr("electric_blue.drain.notify", MagicMock())

    stager = StubStager()
    drain_batch(cfg, backend=backend, stager=stager)

    assert stager.unstage_calls.count(record.staged_url) == 1


# ---------------------------------------------------------------------------
# CFG-9 cross-path: batch_api_key never appears in drain log output
# ---------------------------------------------------------------------------


def test_cfg9_api_key_not_in_drain_logs(
    cfg: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """CFG-9 cross-path: cfg.batch_api_key never appears in log output during drain execution."""
    _seed_record(cfg, tmp_path)
    monkeypatch.setattr("electric_blue.drain.write_outputs", MagicMock(return_value={}))
    monkeypatch.setattr("electric_blue.drain.notify", MagicMock())

    failed_status = JobStatus(
        raw="failed", terminal=True, succeeded=False, output_file_id=None, error="err"
    )

    with caplog.at_level(logging.DEBUG, logger="electric_blue"):
        drain_batch(
            cfg,
            backend=MockAsyncBackend(poll_statuses=[failed_status]),
            stager=StubStager(),
        )

    assert cfg.batch_api_key not in caplog.text
