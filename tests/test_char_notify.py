"""Characterization tests: pin the current notify(cfg, text, meta) stub behaviour.

All four tests must be green against the pre-change stub (S1). CHAR-1 and CHAR-2 are
marked 'survives' — the contracts they verify are preserved by the S5 rewrite (under the
updated 2-arg calling convention). CHAR-3 and CHAR-4 are marked 'superseded' — they
document behaviour that is intentionally replaced in S5 and will be deleted in the same
commit as the notify.py rewrite.
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

    No-op when webhook unset is a surviving contract; this test is preserved (under the
    updated 2-arg calling convention) after the S5 rewrite.
    """
    mock_post = unittest.mock.MagicMock()
    monkeypatch.setattr("requests.post", mock_post)

    cfg = dataclasses.replace(base_cfg, notify_webhook="")
    notify(cfg, "hello", {})

    mock_post.assert_not_called()


def test_char_never_raises(webhook_cfg, monkeypatch):
    """CHAR-2 [survives]: requests.post raises Exception — notify() returns normally.

    Never-raises is a surviving contract; this test is preserved (under the updated 2-arg
    calling convention) after the S5 rewrite.
    """
    monkeypatch.setattr("requests.post", unittest.mock.MagicMock(side_effect=Exception("boom")))

    notify(webhook_cfg, "hello", {})  # must not propagate — return normally


def test_char_old_payload_shape(webhook_cfg, monkeypatch):
    """CHAR-3 [superseded]: webhook set + meta={"file": "x.mp4"} — requests.post called
    with json={"text": "hello", "file": "x.mp4"}.

    Pins pre-rewrite payload shape; superseded by test_posts_generic_payload in S5.
    """
    mock_post = unittest.mock.MagicMock()
    monkeypatch.setattr("requests.post", mock_post)

    notify(webhook_cfg, "hello", {"file": "x.mp4"})

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"text": "hello", "file": "x.mp4"}


def test_char_timeout_15(webhook_cfg, monkeypatch):
    """CHAR-4 [superseded]: webhook set — requests.post called with timeout=15.

    Pins pre-rewrite timeout; superseded by test_timeout_from_config in S5.
    """
    mock_post = unittest.mock.MagicMock()
    monkeypatch.setattr("requests.post", mock_post)

    notify(webhook_cfg, "hello", {})

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["timeout"] == 15
