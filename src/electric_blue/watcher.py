"""File handling, directory management, and watch/once loop."""

from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from .backends import transcribe
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
    obs.start()
    log.info("Watching %s  backend=%s  (Ctrl-C to stop)", cfg.input_dir, cfg.backend)
    try:
        while True:
            time.sleep(cfg.poll_interval)
    except KeyboardInterrupt:
        obs.stop()
    obs.join()
