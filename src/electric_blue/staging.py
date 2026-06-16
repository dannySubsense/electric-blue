"""URL staging Protocol and FunnelStager implementation.

UrlStager is a structural Protocol; FunnelStager is the Tailscale Funnel implementation.
A future MintedUrlStager (R2/B2 pre-signed URL) is a drop-in: add the class, update
make_stager() — no changes to GroqBatchBackend, handle_batch, or drain_batch required.

No imports from batch_groq.py, drain.py, or watcher.py.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .config import Config


@runtime_checkable
class UrlStager(Protocol):
    """Structural protocol for staging a local file to a public HTTPS URL.

    Implementors require no explicit inheritance — structural match suffices.
    FunnelStager is the first concrete implementation.

    The abstraction exists so that a MintedUrlStager (R2/B2 pre-signed URL) is a future
    drop-in: add a new class and change make_stager() with no modification to
    GroqBatchBackend, handle_batch(), or drain_batch().
    """

    def stage(self, path: Path) -> str:
        """Copy path to the serve location; return the public HTTPS URL.

        The returned URL contains only the filename component, never an absolute
        filesystem path (INV-7).  Callers (submit()) always pass a path named
        f"{src.stem}.mp3", ensuring URL uniqueness per source file (B3).
        """
        ...

    def unstage(self, url: str) -> None:
        """Remove the staged file corresponding to url.

        Idempotent — a second call on the same url does not raise.
        """
        ...


class FunnelStager:
    """Tailscale Funnel implementation of UrlStager.

    stage_dir: filesystem directory served by Tailscale Funnel (cfg.batch_stage_dir)
    base_url:  public HTTPS base URL, no trailing slash (cfg.batch_funnel_base_url)
               e.g. "https://myhost.ts.net/stage"

    stage(path) copies path.name into stage_dir and returns
    f"{base_url}/{path.name}" — the filename only, never an absolute fs path (INV-7).

    unstage(url) derives the filename via url.rsplit('/', 1)[-1] and deletes
    stage_dir / filename if it exists; silently returns if the file is already gone.
    """

    def __init__(self, stage_dir: Path, base_url: str) -> None:
        self.stage_dir = stage_dir
        self.base_url = base_url
        self.stage_dir.mkdir(parents=True, exist_ok=True)

    def stage(self, path: Path) -> str:
        """Copy path into stage_dir and return its public HTTPS URL.

        Returns f"{base_url}/{path.name}" — filename only, no absolute fs path (INV-7).
        Raises RuntimeError if the copy fails.
        """
        dest = self.stage_dir / path.name
        try:
            shutil.copy2(path, dest)
        except OSError as exc:
            raise RuntimeError(f"FunnelStager.stage: copy failed for {path}: {exc}") from exc
        return f"{self.base_url.rstrip('/')}/{path.name}"

    def unstage(self, url: str) -> None:
        """Delete the staged file derived from url.  Silently returns if already absent."""
        filename = url.rsplit("/", 1)[-1]
        target = self.stage_dir / filename
        try:
            target.unlink()
        except FileNotFoundError:
            pass


def make_stager(cfg: Config) -> UrlStager:
    """Factory: construct FunnelStager from cfg.

    Raises RuntimeError immediately if cfg.batch_funnel_base_url is empty (INV-2, A3).
    This is the primary guard relied upon by the backend, drain, and watcher.
    """
    if cfg.batch_funnel_base_url == "":
        raise RuntimeError(
            "TRANSCRIBE_BATCH_FUNNEL_URL is not set — batch staging requires a public base URL"
        )
    return FunnelStager(cfg.batch_stage_dir, cfg.batch_funnel_base_url)
