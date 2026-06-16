"""File handling, directory management, and watch/once loop."""

from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from watchdog.events import FileSystemEventHandler

from .backends import transcribe
from .backends.batch_groq import AsyncBackend, make_groq_batch_backend
from .batch_store import BatchStore, JobRecord, make_store
from .config import Config
from .notify import (
    build_done_payload,
    build_failed_payload,
    build_started_payload,
    notify,
)
from .outputs import write_outputs

log = logging.getLogger("electric_blue")


def ensure_dirs(cfg: Config) -> None:
    for d in (cfg.input_dir, cfg.output_dir, cfg.done_dir, cfg.failed_dir):
        d.mkdir(parents=True, exist_ok=True)


def ensure_batch_dirs(cfg: Config) -> None:
    """Create batch_inbox_dir, batch_submitted_dir, batch_stage_dir, batch_store_path.

    PRIMARY FUNNEL GUARD (B1, CFG-10): Raises RuntimeError if cfg.batch_funnel_base_url is
    empty when batch is enabled. Called only when cfg.batch_inbox_dir is not None. Any
    RuntimeError raised here propagates through run_watch() and aborts the process — deliberate.
    """
    if cfg.batch_funnel_base_url == "":
        raise RuntimeError(
            "TRANSCRIBE_BATCH_FUNNEL_URL is not set — "
            "batch processing requires a public staging base URL (B1/CFG-10)."
        )
    cfg.batch_inbox_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
    cfg.batch_submitted_dir.mkdir(parents=True, exist_ok=True)
    cfg.batch_stage_dir.mkdir(parents=True, exist_ok=True)
    cfg.batch_store_path.mkdir(parents=True, exist_ok=True)


def handle_batch(
    cfg: Config,
    path: Path,
    *,
    backend: AsyncBackend | None = None,
    store: BatchStore | None = None,
) -> None:
    """Batch submission path with optional DI for test injection.

    Execution order (SUBMIT-1, INV-1 per 02-ARCHITECTURE §12):
    1. suffix check — return if not a media extension (SUBMIT-7)
    2. is_stable() — return if not stable
    3. find_by_src_name() + status check — skip if live record exists (A4, SUBMIT-3)
    4. construct backend INSIDE try (B1 defense-in-depth); backend.submit()
    5. store.save(record) BEFORE shutil.move (INV-1); staged_path = DESTINATION (SUBMIT-8)
    6. shutil.move(path → batch_submitted_dir)
    PRE-save failure (steps 4–5 raise, SUBMIT-5): log error + move source → failed_dir; no record.
    POST-save failure (step 6 raises, SUBMIT-6): log error; leave source in batch_inbox_dir as
    recovery artifact; record is persisted (status=submitted); drain path retrieves transcript
    via record; live-record guard prevents re-submission.
    """
    # 1. Suffix check (SUBMIT-7)
    if path.suffix.lower() not in cfg.media_exts:
        return
    # 2. Stability check
    if not is_stable(path, cfg.stability_seconds):
        return
    # 3. Duplicate-submission guard (A4, SUBMIT-3)
    store = store or make_store(cfg)
    existing = store.find_by_src_name(path.name)
    if existing is not None and existing.status in {"submitted", "polling"}:
        log.warning(
            "Batch job already live for %s (status=%s); skipping re-submission",
            path.name,
            existing.status,
        )
        return
    # 4–6. Submit inside try block
    saved = False
    try:
        _backend = backend or make_groq_batch_backend(cfg)  # B1 defense-in-depth
        job_ref = _backend.submit(cfg, path)
        record = JobRecord(
            job_id=job_ref.job_id,
            jsonl_file_id=job_ref.jsonl_file_id,
            staged_url=job_ref.staged_url,
            src_name=path.name,
            src_stem=path.stem,
            staged_path=str(cfg.batch_submitted_dir / path.name),  # DESTINATION (SUBMIT-8)
            status="submitted",
            submitted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            completed_at=None,
            error=None,
        )
        store.save(record)  # INV-1: BEFORE shutil.move
        saved = True
        shutil.move(str(path), str(cfg.batch_submitted_dir / path.name))
    except Exception as e:
        if not saved:
            # PRE-save failure (SUBMIT-5): backend construction or submit raised; no record
            # persisted — move source to failed_dir so operator can re-drop after fixing.
            log.error("Batch submission failed for %s: %s", path.name, e)
            shutil.move(str(path), str(cfg.failed_dir / path.name))
        else:
            # POST-save failure (SUBMIT-6): store.save() succeeded but shutil.move raised;
            # record is persisted (status=submitted). Do NOT move source to failed_dir —
            # leave it in batch_inbox_dir as the recovery artifact. The drain path will
            # retrieve the transcript via the persisted record; the live-record guard
            # (step 3) prevents re-submission on the next scan.
            log.error(
                "Batch record persisted (status=submitted) but file move failed for %s: %s"
                " — source remains in inbox for drain recovery.",
                path.name,
                e,
            )


class _BatchHandler(FileSystemEventHandler):
    """FileSystemEventHandler that routes file events to handle_batch().

    Mirrors the sync H handler pattern inside run_watch(); non-directory events only.
    """

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg

    def on_created(self, e) -> None:  # type: ignore[override]
        if not e.is_directory:
            handle_batch(self.cfg, Path(e.src_path))

    def on_moved(self, e) -> None:  # type: ignore[override]
        if not e.is_directory:
            handle_batch(self.cfg, Path(e.dest_path))


def is_stable(path: Path, stability_seconds: float = 2.0) -> bool:
    try:
        s1 = path.stat().st_size
        time.sleep(stability_seconds)
        return path.exists() and path.stat().st_size == s1 and s1 > 0
    except FileNotFoundError:
        return False


def process(cfg: Config, src: Path, started_at: datetime) -> None:
    log.info("Processing (%s): %s", cfg.backend, src.name)
    notify(cfg, build_started_payload(cfg, src, started_at))
    segments, info = transcribe(cfg, src)
    output_stems = write_outputs(cfg, cfg.output_dir, src.stem, segments, info)
    finished_at = datetime.now(timezone.utc)
    log.info(
        "Done: %s  [%s, %.0fs audio, %.0fs wall] -> %s",
        src.name,
        info.language,
        info.duration,
        (finished_at - started_at).total_seconds(),
        cfg.output_dir,
    )
    notify(cfg, build_done_payload(cfg, src, info, output_stems, started_at, finished_at))


def handle(cfg: Config, path: Path) -> None:
    if path.suffix.lower() not in cfg.media_exts or not is_stable(path, cfg.stability_seconds):
        return
    started_at = datetime.now(timezone.utc)
    try:
        process(cfg, path, started_at)
        shutil.move(str(path), str(cfg.done_dir / path.name))
    except Exception as e:
        log.error("Failed on %s: %s", path.name, e)
        notify(cfg, build_failed_payload(cfg, path, e, started_at, datetime.now(timezone.utc)))
        shutil.move(str(path), str(cfg.failed_dir / path.name))


def run_once(cfg: Config) -> None:
    files = sorted(p for p in cfg.input_dir.iterdir() if p.is_file())
    if not files:
        log.info("Nothing in %s", cfg.input_dir)
    for p in files:
        handle(cfg, p)


def run_watch(cfg: Config) -> None:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    class H(FileSystemEventHandler):
        def on_created(self, e):
            if not e.is_directory:
                handle(cfg, Path(e.src_path))

        def on_moved(self, e):
            if not e.is_directory:
                handle(cfg, Path(e.dest_path))

    run_once(cfg)
    obs = Observer()
    obs.schedule(H(), str(cfg.input_dir), recursive=False)
    if cfg.batch_inbox_dir:
        ensure_batch_dirs(cfg)  # primary B1 guard — raises RuntimeError if funnel URL unset
        obs.schedule(_BatchHandler(cfg), str(cfg.batch_inbox_dir), recursive=False)
    obs.start()
    log.info("Watching %s  backend=%s  (Ctrl-C to stop)", cfg.input_dir, cfg.backend)
    try:
        while True:
            time.sleep(cfg.poll_interval)
    except KeyboardInterrupt:
        obs.stop()
    obs.join()
