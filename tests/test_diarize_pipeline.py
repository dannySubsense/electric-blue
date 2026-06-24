"""Diarize-pipeline test module for DDR-05 (whisperx-diarization).

Tests grow slice by slice across S1–S7. Each section is labelled with its slice.
S1: foundation — ConfigurationError importability.
"""

from __future__ import annotations

# ── S1 — exceptions.py ────────────────────────────────────────────────────────


def test_configuration_error_importable():
    """S1: ConfigurationError is importable and is a subclass of Exception."""
    from electric_blue.exceptions import ConfigurationError

    assert issubclass(ConfigurationError, Exception) is True
