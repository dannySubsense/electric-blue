"""Characterization tests: pin the surviving notify() contracts.

CHAR-1 and CHAR-2 survive into the S5 rewrite, updated to the new 2-arg
notify(cfg, payload) calling convention and the module-level mock seam.

CHAR-3 (test_char_old_payload_shape) — DELETED S5: superseded by test_posts_generic_payload.
CHAR-4 (test_char_timeout_15)         — DELETED S5: superseded by test_timeout_from_config.
"""

from __future__ import annotations

import dataclasses
import unittest.mock

import pytest

from electric_blue.config import Config
from electric_blue.notify import notify


@pytest.fixture()
def base_cfg(monkeypatch):
    """Config with no webhook set; clears NOTIFY_WEBHOOK so from_env() defaults to ''."""
    monkeypatch.delenv("NOTIFY_WEBHOOK", raising=False)
    return Config.from_env()


@pytest.fixture()
def webhook_cfg(base_cfg):
    """Config with webhook replaced to a safe dummy URL."""
    return dataclasses.replace(base_cfg, notify_webhook="http://fake.invalid/hook")


def test_char_no_op_when_webhook_unset(base_cfg, monkeypatch):
    """CHAR-1 [survives]: notify_webhook="" — requests.post is NEVER called.

    Updated to 2-arg notify(cfg, payload) form after the S5 rewrite.
    Mock seam updated to electric_blue.notify.requests.post (module-level import).
    """
    mock_post = unittest.mock.MagicMock()
    monkeypatch.setattr("electric_blue.notify.requests.post", mock_post)

    cfg = dataclasses.replace(base_cfg, notify_webhook="")
    notify(cfg, {})

    mock_post.assert_not_called()


def test_char_never_raises(webhook_cfg, monkeypatch):
    """CHAR-2 [survives]: requests.post raises Exception — notify() returns normally.

    Updated to 2-arg notify(cfg, payload) form after the S5 rewrite.
    Mock seam updated to electric_blue.notify.requests.post (module-level import).
    """
    monkeypatch.setattr(
        "electric_blue.notify.requests.post",
        unittest.mock.MagicMock(side_effect=Exception("boom")),
    )

    notify(webhook_cfg, {})  # must not propagate — return normally
