"""Tests for batch_store.py — STORE-1..8 acceptance criteria (DDR-03 / S3).

All tests are hermetic: tmp_path only, no network, no subprocess.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

from electric_blue.batch_store import (
    BatchStore,
    JobRecord,
    SidecarBatchStore,
    make_store,
)
from electric_blue.config import Config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXPECTED_FIELDS = frozenset(
    {
        "job_id",
        "jsonl_file_id",
        "staged_url",
        "src_name",
        "src_stem",
        "staged_path",
        "status",
        "submitted_at",
        "completed_at",
        "error",
    }
)


def _make_record(job_id: str = "batch_abc123", status: str = "submitted") -> JobRecord:
    """Build a fully-populated JobRecord with all 10 required fields."""
    return JobRecord(
        job_id=job_id,
        jsonl_file_id="file_jsonl_001",
        staged_url="https://example.com/staged/meeting.mp4",
        src_name="meeting.mp4",
        src_stem="meeting",
        staged_path="/data/batch_submitted/meeting.mp4",
        status=status,
        submitted_at="2026-06-16T12:00:00",
        completed_at=None,
        error=None,
    )


def _make_cfg(tmp_path: Path) -> Config:
    """Return a Config with batch_store_path under tmp_path."""
    return dataclasses.replace(
        Config.from_env(),
        batch_store_path=tmp_path / "store",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# STORE-1
# ---------------------------------------------------------------------------


def test_store1_protocol_structural(tmp_path):
    """STORE-1: BatchStore Protocol is structural; SidecarBatchStore and make_store satisfy it."""
    store_path = tmp_path / "store"
    store = SidecarBatchStore(store_path)
    assert isinstance(store, BatchStore)

    cfg = _make_cfg(tmp_path)
    factory_store = make_store(cfg)
    assert isinstance(factory_store, BatchStore)


# ---------------------------------------------------------------------------
# STORE-2
# ---------------------------------------------------------------------------


def test_store2_save_creates_sidecar(tmp_path):
    """STORE-2: save(record) → <job_id>.json exists; JSON object contains all JobRecord fields."""
    store = SidecarBatchStore(tmp_path / "store")
    record = _make_record()

    store.save(record)

    sidecar = tmp_path / "store" / f"{record.job_id}.json"
    assert sidecar.exists()

    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert set(data.keys()) == _EXPECTED_FIELDS


# ---------------------------------------------------------------------------
# STORE-3
# ---------------------------------------------------------------------------


def test_store3_list_pending_filters_status(tmp_path):
    """STORE-3: list_pending() returns only submitted/polling; excludes completed/failed/expired/cancelled."""
    store = SidecarBatchStore(tmp_path / "store")

    store.save(_make_record(job_id="batch_sub", status="submitted"))
    store.save(_make_record(job_id="batch_pol", status="polling"))
    store.save(_make_record(job_id="batch_com", status="completed"))
    store.save(_make_record(job_id="batch_fai", status="failed"))
    store.save(_make_record(job_id="batch_exp", status="expired"))
    store.save(_make_record(job_id="batch_can", status="cancelled"))

    pending = store.list_pending()
    returned_ids = {r.job_id for r in pending}

    assert returned_ids == {"batch_sub", "batch_pol"}


# ---------------------------------------------------------------------------
# STORE-4
# ---------------------------------------------------------------------------


def test_store4_update_patches_fields(tmp_path):
    """STORE-4: save then update(status, completed_at) → get() returns patched record; other fields unchanged."""
    store = SidecarBatchStore(tmp_path / "store")
    record = _make_record()
    store.save(record)

    store.update(record.job_id, status="completed", completed_at="2026-06-16T13:00:00")

    retrieved = store.get(record.job_id)
    assert retrieved is not None
    assert retrieved.status == "completed"
    assert retrieved.completed_at == "2026-06-16T13:00:00"
    # All other fields must remain unchanged
    assert retrieved.job_id == record.job_id
    assert retrieved.jsonl_file_id == record.jsonl_file_id
    assert retrieved.staged_url == record.staged_url
    assert retrieved.src_name == record.src_name
    assert retrieved.src_stem == record.src_stem
    assert retrieved.staged_path == record.staged_path
    assert retrieved.submitted_at == record.submitted_at
    assert retrieved.error == record.error


# ---------------------------------------------------------------------------
# STORE-5
# ---------------------------------------------------------------------------


def test_store5_find_by_src_name(tmp_path):
    """STORE-5: find_by_src_name returns matching record; no match returns None."""
    store = SidecarBatchStore(tmp_path / "store")
    record = _make_record()
    store.save(record)

    found = store.find_by_src_name("meeting.mp4")
    assert found is not None
    assert found.src_name == "meeting.mp4"

    not_found = store.find_by_src_name("nonexistent.mp4")
    assert not_found is None


# ---------------------------------------------------------------------------
# STORE-6
# ---------------------------------------------------------------------------


def test_store6_cold_start(tmp_path):
    """STORE-6: record saved via first make_store; new make_store on same path returns it via list_pending()."""
    cfg = _make_cfg(tmp_path)
    record = _make_record(status="polling")

    first_store = make_store(cfg)
    first_store.save(record)

    # Simulate cold-start: new instance, same path, no shared in-memory state
    second_store = make_store(cfg)
    pending = second_store.list_pending()

    assert len(pending) == 1
    assert pending[0].job_id == record.job_id


# ---------------------------------------------------------------------------
# STORE-7
# ---------------------------------------------------------------------------


def test_store7_update_touches_only_target(tmp_path):
    """STORE-7: update(job_id='A') → only A.json changed; B.json bytes unchanged (hash compare)."""
    store = SidecarBatchStore(tmp_path / "store")

    store.save(_make_record(job_id="batch_A"))
    store.save(_make_record(job_id="batch_B"))

    path_b = tmp_path / "store" / "batch_B.json"
    hash_before = _sha256(path_b)

    store.update("batch_A", status="completed", completed_at="2026-06-16T14:00:00")

    assert _sha256(path_b) == hash_before


# ---------------------------------------------------------------------------
# STORE-8
# ---------------------------------------------------------------------------


def test_store8_jobrecord_fields_and_serializable():
    """STORE-8: JobRecord has all 10 named fields; asdict is JSON-serializable without custom encoder; staged_url exists."""
    record = _make_record()
    as_dict = dataclasses.asdict(record)

    assert set(as_dict.keys()) == _EXPECTED_FIELDS
    assert "staged_url" in as_dict
    assert "audio_file_id" not in as_dict

    # JSON-serializable without a custom encoder
    serialized = json.dumps(as_dict)
    assert isinstance(serialized, str)
