"""Registry tests for get_backend() factory (post-refactor, Slice S3).

Verifies AC-04-F: unknown cfg.backend raises RuntimeError (not KeyError) with a
message that names the bad key and lists the available backends.
"""

from __future__ import annotations

import dataclasses

import pytest

from electric_blue.backends import get_backend
from electric_blue.config import Config


def test_get_backend_unknown_raises():
    """Unknown backend raises RuntimeError naming the bad key and listing available ones."""
    cfg = dataclasses.replace(Config.from_env(), backend="bogus_backend_xyz")

    with pytest.raises(RuntimeError) as exc_info:
        get_backend(cfg)

    msg = str(exc_info.value)
    assert "bogus_backend_xyz" in msg
    assert "local" in msg or "api" in msg
