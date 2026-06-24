"""Exceptions for the electric-blue transcription pipeline."""

from __future__ import annotations


class ConfigurationError(Exception):
    """Raised when electric-blue detects an invalid or missing configuration value.

    Raised by:
    - ``Config.from_env()`` — on invalid environment variable values (e.g. a
      non-integer or non-positive ``WHISPER_DIARIZE_NUM_SPEAKERS``).
    - ``WhisperXBackend.__init__()`` — when ``HF_TOKEN`` is absent or empty.

    This exception is not caught inside the electric-blue package; it propagates
    to ``watcher.handle()`` (and, at startup, out of ``run_watch()``), where the
    caller is responsible for surfacing it to the operator.
    """
