"""Batch job state store — data schemas, Protocol, and SidecarBatchStore D1 implementation.

No imports from batch_groq.py, drain.py, or watcher.py (no dependency cycles per roadmap
dependency graph).  Zero new runtime dependencies: stdlib dataclasses, json, os, pathlib,
tempfile only.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .config import Config


@dataclass
class JobRef:
    """Returned by submit(); passed to poll() and fetch()."""

    job_id: str  # Groq batch object ID (e.g. "batch_abc123")
    jsonl_file_id: str  # Groq file ID of the uploaded JSONL
    staged_url: str  # Public HTTPS URL returned by stager.stage() — A1 (replaces audio_file_id)
    output_file_id: str | None = None
    # output_file_id is None at submit() time; set by drain before calling fetch()
    # after poll() returns JobStatus(succeeded=True, output_file_id="file_xyz")


@dataclass
class JobStatus:
    """Returned by poll()."""

    raw: str  # Provider status string, unmodified (e.g. "in_progress", "completed")
    terminal: bool  # True if no further polling is needed
    succeeded: bool  # True if completed successfully (raw == "completed")
    output_file_id: str | None  # Present only when terminal=True and succeeded=True
    error: str | None  # Present for terminal failures


@dataclass
class JobRecord:
    """Persisted to the sidecar JSON store at submission; updated through drain.

    All fields are JSON-serializable without custom encoders (str, str | None).
    staged_url replaces audio_file_id from DDR §4 body (A1 — confirmed correction).
    """

    job_id: str  # Groq batch ID — used as sidecar filename
    jsonl_file_id: str  # Groq file ID of the uploaded JSONL (for potential cleanup)
    staged_url: str  # Public HTTPS URL (A1) — passed to stager.unstage() at terminal
    src_name: str  # Original filename (e.g. "meeting.mp4") — for done/failed move
    src_stem: str  # Stem used for write_outputs (e.g. "meeting")
    staged_path: str  # Absolute path of source file in batch_submitted_dir (DESTINATION)
    status: str  # "submitted" | "polling" | "completed" | "failed" | "expired" | "cancelled"
    submitted_at: str  # ISO 8601 UTC, timespec="seconds"
    completed_at: str | None  # ISO 8601 UTC, set when status → "completed"
    error: str | None  # Error description for terminal-failure statuses


@runtime_checkable
class BatchStore(Protocol):
    """Structural protocol for the batch job state store."""

    def save(self, record: JobRecord) -> None: ...

    def get(self, job_id: str) -> JobRecord | None: ...

    def find_by_src_name(self, src_name: str) -> JobRecord | None:
        """Return any record with src_name == src_name, regardless of status.

        Caller is responsible for checking record.status (see A4).
        """
        ...

    def list_pending(self) -> list[JobRecord]:
        """Return records where status in {"submitted", "polling"} only."""
        ...

    def update(self, job_id: str, **kwargs) -> None:
        """Update named fields on the record identified by job_id. Raises KeyError if not found."""
        ...


_PENDING_STATUSES: frozenset[str] = frozenset({"submitted", "polling"})


class SidecarBatchStore:
    """D1 implementation: one <job_id>.json per record in store_path directory.

    File format: JSON object, all JobRecord fields. Written atomically via a sibling temp
    file and Path.replace() — no in-memory state required between sessions (cold-start safe).
    """

    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path
        store_path.mkdir(parents=True, exist_ok=True)

    def _sidecar(self, job_id: str) -> Path:
        return self._store_path / f"{job_id}.json"

    def _write_atomic(self, record: JobRecord) -> None:
        """Write record atomically: json.dumps → sibling temp → Path.replace(final)."""
        final = self._sidecar(record.job_id)
        content = json.dumps(dataclasses.asdict(record))
        # mkstemp creates the temp file in the same directory so Path.replace() is
        # guaranteed to be on the same filesystem (atomic rename on POSIX).
        fd, tmp_name = tempfile.mkstemp(dir=self._store_path, suffix=".tmp")
        os.close(fd)  # close raw fd; write_text opens independently
        tmp = Path(tmp_name)
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(final)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def save(self, record: JobRecord) -> None:
        """Persist record. Overwrites any existing sidecar for the same job_id."""
        self._write_atomic(record)

    def get(self, job_id: str) -> JobRecord | None:
        """Return the record for job_id, or None if not found."""
        path = self._sidecar(job_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return JobRecord(**data)

    def find_by_src_name(self, src_name: str) -> JobRecord | None:
        """Return any record with matching src_name, or None.

        Caller is responsible for checking record.status (A4).  Returns the first
        matching sidecar found; iteration order is filesystem-dependent.
        """
        for p in self._store_path.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("src_name") == src_name:
                    return JobRecord(**data)
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return None

    def list_pending(self) -> list[JobRecord]:
        """Return records where status in {"submitted", "polling"}.

        Reads all *.json sidecars from disk on every call (cold-start safe).
        Silently skips unreadable or malformed sidecars.
        """
        pending: list[JobRecord] = []
        for p in self._store_path.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("status") in _PENDING_STATUSES:
                    pending.append(JobRecord(**data))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return pending

    def update(self, job_id: str, **kwargs) -> None:
        """Update named fields on the record identified by job_id.

        Raises KeyError if job_id not found.
        Uses dataclasses.replace() to produce the patched record, then writes atomically.
        Only <job_id>.json is touched — all other sidecars are unread and unwritten (STORE-7).
        """
        record = self.get(job_id)
        if record is None:
            raise KeyError(f"No batch record found for job_id={job_id!r}")
        updated = dataclasses.replace(record, **kwargs)
        self._write_atomic(updated)


def make_store(cfg: Config) -> BatchStore:
    """Factory: return SidecarBatchStore(cfg.batch_store_path). Creates directory if needed."""
    return SidecarBatchStore(cfg.batch_store_path)
