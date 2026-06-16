"""drain_batch — idempotent polling drain for Groq Batch jobs.

Retrieves and finalises all pending batch jobs: poll → fetch → write → move → notify.

WARNING: Simultaneous --drain-batch invocations are unsupported (FLAG-2). Per-job sidecar
isolation limits damage if two processes run concurrently, but concurrent writes to the same
sidecar can corrupt it. Operators should ensure the drain cron interval exceeds typical drain
runtime. No file locking is implemented this sprint.
"""

from __future__ import annotations

import dataclasses
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .backends.batch_groq import AsyncBackend, make_groq_batch_backend
from .batch_store import JobRecord, JobRef, make_store
from .config import Config
from .models import TranscriptInfo
from .notify import notify
from .outputs import write_outputs
from .staging import UrlStager, make_stager

log = logging.getLogger("electric_blue")

_LIVE_STATUSES: frozenset[str] = frozenset({"submitted", "polling"})


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string with seconds precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_window_hours(window: str) -> float:
    """Parse completion window string to hours. Returns 24.0 if unparseable."""
    w = window.strip()
    try:
        if w.endswith("h"):
            return float(w[:-1])
        if w.endswith("d"):
            return float(w[:-1]) * 24.0
    except (ValueError, IndexError):
        pass
    log.warning("Unparseable batch_completion_window %r; defaulting to 24h", window)
    return 24.0


def _maybe_warn_expiry(record: JobRecord, cfg: Config) -> None:
    """Warn if the job is approaching its completion window expiry (DRAIN-8).

    Parses cfg.batch_completion_window ("24h"→24.0, "7d"→168.0; fallback 24.0).
    Emits WARNING if submitted_at is older than 80% of the parsed window and the
    record status is live (submitted/polling).
    """
    if record.status not in _LIVE_STATUSES:
        return
    window_hours = _parse_window_hours(cfg.batch_completion_window)
    threshold_hours = window_hours * 0.8
    try:
        submitted = datetime.fromisoformat(record.submitted_at)
        if submitted.tzinfo is None:
            submitted = submitted.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - submitted).total_seconds() / 3600.0
        if age_hours >= threshold_hours:
            log.warning(
                "Batch job %s approaching expiry: age %.1fh >= threshold %.1fh (80%% of %s)",
                record.job_id,
                age_hours,
                threshold_hours,
                cfg.batch_completion_window,
            )
    except (ValueError, TypeError) as exc:
        log.warning("Could not parse submitted_at for job %s: %s", record.job_id, exc)


def _fire_completion_hook(cfg: Config, record: JobRecord, info: TranscriptInfo) -> None:
    """Best-effort completion notification. Swallows all exceptions (HOOK-2).

    Builds the batch_done payload (schema_version=1) and calls notify(cfg, payload).
    Any exception from payload construction or notify() is caught and logged at WARNING —
    a notification failure must never propagate into the drain pipeline.
    """
    try:
        payload: dict = {
            "schema_version": 1,
            "event": "batch_done",
            "file": record.src_name,
            "job_id": record.job_id,
            "backend": info.backend,
            "status": "batch_done",
            "duration_min": round(info.duration / 60, 1),
        }
        notify(cfg, payload)
    except Exception as exc:  # noqa: BLE001
        log.warning("_fire_completion_hook failed for job %s: %s", record.job_id, exc)


def drain_batch(
    cfg: Config,
    *,
    backend: AsyncBackend | None = None,
    stager: UrlStager | None = None,
) -> None:
    """Poll all pending batch jobs. Idempotent. Optional backend/stager for test injection.

    Returns immediately if cfg.batch_inbox_dir is None (DRAIN-10).
    Per-job exceptions are caught and logged; processing continues for remaining jobs (DRAIN-7).
    Stager and backend are constructed inside the per-job try block (defense-in-depth for B1):
    if make_stager raises RuntimeError (empty funnel URL), the exception is caught per-job,
    logged, and that job is skipped without aborting the entire drain.
    """
    if cfg.batch_inbox_dir is None:  # DRAIN-10: defensive guard
        return

    store = make_store(cfg)

    for record in store.list_pending():
        try:
            # B1 defense-in-depth: construct per-job inside try so any RuntimeError
            # (e.g. empty funnel URL) is caught by the per-job handler and logged,
            # rather than aborting the entire drain. Primary guard is ensure_batch_dirs().
            _stager = stager if stager is not None else make_stager(cfg)
            _backend = backend if backend is not None else make_groq_batch_backend(cfg)

            # DRAIN-8: warn on approaching expiry
            _maybe_warn_expiry(record, cfg)

            job_ref = JobRef(
                job_id=record.job_id,
                jsonl_file_id=record.jsonl_file_id,
                staged_url=record.staged_url,
            )
            status = _backend.poll(cfg, job_ref)

            if not status.terminal:
                store.update(record.job_id, status="polling")  # DRAIN-2
                continue

            if status.succeeded:
                # Set output_file_id so fetch() can download results
                job_ref_for_fetch = dataclasses.replace(
                    job_ref, output_file_id=status.output_file_id
                )
                transcript = _backend.fetch(cfg, job_ref_for_fetch)

                write_outputs(
                    cfg,
                    cfg.output_dir,
                    record.src_stem,
                    transcript.segments,
                    transcript.info,
                )

                staged = Path(record.staged_path)
                if staged.exists():  # DRAIN-5 idempotent guard
                    shutil.move(str(staged), str(cfg.done_dir / record.src_name))

                store.update(
                    record.job_id,
                    status="completed",
                    completed_at=_now_iso(),
                )  # INV-1: AFTER shutil.move

                try:  # STAG-5, FAIL-4
                    _stager.unstage(record.staged_url)
                except Exception as exc:
                    log.warning("unstage failed for %s: %s", record.staged_url, exc)

                _fire_completion_hook(cfg, record, transcript.info)  # HOOK-2

            else:
                # Terminal failure: failed / expired / cancelled
                staged = Path(record.staged_path)
                if staged.exists():  # FAIL-3
                    shutil.move(str(staged), str(cfg.failed_dir / record.src_name))
                else:
                    log.warning(
                        "staged file missing for failed job %s: %s",
                        record.job_id,
                        record.staged_path,
                    )

                store.update(
                    record.job_id,
                    status=status.raw,
                    error=status.error or f"batch job did not succeed: {status.raw}",
                )  # INV-1: AFTER shutil.move

                try:  # FAIL-4
                    _stager.unstage(record.staged_url)
                except Exception as exc:
                    log.warning("unstage failed for %s: %s", record.staged_url, exc)

                log.error("Batch job %s terminal failure: %s", record.job_id, status.raw)

        except Exception as exc:  # DRAIN-7: per-job guard
            log.error("drain error for job %s: %s", record.job_id, exc)
            # Status unchanged — retried on next drain invocation
