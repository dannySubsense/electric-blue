"""Best-effort webhook notification — never raises into the pipeline."""

from __future__ import annotations

import logging

from .config import Config

log = logging.getLogger("electric_blue")


def notify(cfg: Config, text: str, meta: dict | None = None) -> None:
    """POST a JSON ping to cfg.notify_webhook if set. Silently ignores all errors."""
    if not cfg.notify_webhook:
        return
    try:
        import requests

        payload = {"text": text}
        if meta:
            payload.update(meta)
        requests.post(cfg.notify_webhook, json=payload, timeout=15)
    except Exception as e:
        log.warning("notify failed: %s", e)
