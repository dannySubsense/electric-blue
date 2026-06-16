"""Command-line interface for electric-blue."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Drop-folder transcription pipeline — local or API backend."
    )
    ap.add_argument("--once", action="store_true", help="Process INPUT_DIR then exit.")
    ap.add_argument("--file", type=str, help="Transcribe a single file.")
    ap.add_argument(
        "--drain-batch",
        action="store_true",
        help="Poll pending Groq Batch jobs and retrieve completed ones. Safe to call from cron.",
    )
    args = ap.parse_args()

    from .config import Config
    from .watcher import ensure_dirs, process, run_once, run_watch

    cfg = Config.from_env()
    ensure_dirs(cfg)

    if args.drain_batch:
        from .drain import drain_batch

        drain_batch(cfg)
        return

    if args.file:
        from datetime import datetime, timezone

        process(cfg, Path(args.file), datetime.now(timezone.utc))
    elif args.once:
        run_once(cfg)
    else:
        run_watch(cfg)
