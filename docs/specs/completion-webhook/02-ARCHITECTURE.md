# Architecture: completion-webhook

- **Status:** DRAFT
- **Author:** reed
- **Date:** 2026-06-14
- **Requirements:** 01-REQUIREMENTS.md
- **DDR:** DDR-04-completion-webhook.md
- **Sprint:** completion-webhook (GitHub issue #10)

---

## Summary

This document translates locked decisions D1–D6 and the 01-REQUIREMENTS into a concrete
technical design grounded in the real current code. It specifies exact function signatures,
the full notify.py rewrite, the Config additions, the write_outputs() return-value change,
the watcher.py call-site changes, and the characterization-test strategy.

One correction over the DDR's proposed code is noted in section 3 (_post_with_retry and 4xx
handling). One design decision about started_at scope is made explicit in section 5 (watcher
call sites). Both are called out where they occur.

---

## 1. Components

| Component | Responsibility | Location |
|-----------|----------------|----------|
| `notify._base_payload` | Build shared v1 envelope fields (schema_version, event, file, backend, started_at, optional finished_at/wall_sec) | `src/electric_blue/notify.py` |
| `notify.build_done_payload` | Extend base with status, duration_sec, language, backend (from info), outputs dict | `src/electric_blue/notify.py` |
| `notify.build_failed_payload` | Extend base with status, error string | `src/electric_blue/notify.py` |
| `notify.build_started_payload` | Wrap base with finished_at=None | `src/electric_blue/notify.py` |
| `notify._format_payload` | Dispatch to provider formatter by cfg.notify_format; default identity | `src/electric_blue/notify.py` |
| `notify._format_ntfy` | Translate v1 dict to ntfy JSON publish shape | `src/electric_blue/notify.py` |
| `notify._sign` | Compute sha256 HMAC over canonical JSON bytes | `src/electric_blue/notify.py` |
| `notify._post_with_retry` | POST body with bounded timeout and retry; 4xx aborts, 5xx retries; never raises | `src/electric_blue/notify.py` |
| `notify.notify` | Public entry point: guard → format → sign → post-with-retry; never raises | `src/electric_blue/notify.py` |
| `Config` (additions) | Four new frozen fields: notify_timeout_sec, notify_retries, notify_format, notify_hmac_secret | `src/electric_blue/config.py` |
| `write_outputs` | Write all enabled formats; return {fmt: Path} for each file written | `src/electric_blue/outputs.py` |
| `watcher.handle` | Stamp started_at; call process(); on success move to done; on exception build_failed_payload + move to failed | `src/electric_blue/watcher.py` |
| `watcher.process` | Receive started_at; fire started notification; transcribe; write outputs; fire done notification | `src/electric_blue/watcher.py` |

---

## 2. Data Schemas

All payloads are plain Python dicts (`dict[str, ...]`). No new dataclass is introduced — the
dict contract is enforced by tests, not by the type system.

### v1 Base Payload Fields (shared by all events)

```python
{
    "schema_version": 1,               # int literal, additive policy (INV-10)
    "event": str,                      # "done" | "failed" | "started"
    "file": str,                       # src.name ONLY — never str(src) (INV-7 / RED-1)
    "backend": str,                    # cfg.backend (started/failed) or info.backend (done)
    "started_at": str,                 # ISO-8601 UTC, timespec="seconds", e.g. "2026-06-14T10:00:00+00:00"
}
```

### Done Payload (extends base)

```python
{
    # ... base fields ...
    "finished_at": str,                # ISO-8601 UTC string
    "wall_sec": float,                 # round((finished_at - started_at).total_seconds(), 1)
    "status": "done",
    "duration_sec": float,             # round(info.duration, 1) — audio length, not wall time
    "language": str,                   # info.language
    "backend": str,                    # info.backend overrides cfg.backend (e.g. "api:whisper-large-v3-turbo")
    "outputs": dict[str, str],         # {fmt: filename_only} e.g. {"txt": "meeting.txt"}
}
```

### Failed Payload (extends base)

```python
{
    # ... base fields ...
    "finished_at": str,                # ISO-8601 UTC string
    "wall_sec": float,                 # derived from timestamps
    "status": "failed",
    "error": str,                      # str(exception) — message only, no traceback (RED-4 safe)
    # no duration_sec, no language, no outputs
}
```

### Started Payload (base only, no finished fields)

```python
{
    "schema_version": 1,
    "event": "started",
    "file": str,
    "backend": str,                    # cfg.backend (info not yet available)
    "started_at": str,
    # no finished_at, no wall_sec (STA-1)
}
```

### ntfy Formatted Payload

```python
{
    "title": str,                      # e.g. "Transcription done: meeting.mp4"
    "message": str,                    # event-specific description
    "priority": int,                   # 2 (started), 3 (done/generic), 4 (failed)
    "tags": list[str],                 # ntfy tag names, e.g. ["white_check_mark"]
}
```

### Config Additions (Python type annotations)

```python
notify_timeout_sec: float   # NOTIFY_TIMEOUT_SEC, default 5.0
notify_retries: int         # NOTIFY_RETRIES, default 0
notify_format: str          # NOTIFY_FORMAT, default "generic", lowercased at parse time
notify_hmac_secret: str     # NOTIFY_HMAC_SECRET, default ""
```

### write_outputs Return Type

```python
dict[str, Path]  # {fmt: absolute_path} e.g. {"txt": Path("/transcripts/meeting.txt")}
```

The done-payload `outputs` dict is derived from this by taking `.name` of each value:
`{fmt: path.name for fmt, path in output_stems.items()}`.

---

## 3. API Contracts

### notify.py — Full Module Design

```python
"""Best-effort webhook notification — never raises into the pipeline."""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import logging
from datetime import datetime
from pathlib import Path

import requests

from .config import Config
from .models import TranscriptInfo

log = logging.getLogger("electric_blue")


def _base_payload(
    event: str,
    cfg: Config,
    src: Path,
    started_at: datetime,
    finished_at: datetime | None = None,
) -> dict:
    """Build shared v1 envelope. finished_at=None emits no finished_at or wall_sec."""
    p: dict = {
        "schema_version": 1,
        "event": event,
        "file": src.name,       # filename only — never str(src)
        "backend": cfg.backend,
        "started_at": started_at.isoformat(timespec="seconds"),
    }
    if finished_at is not None:
        p["finished_at"] = finished_at.isoformat(timespec="seconds")
        p["wall_sec"] = round((finished_at - started_at).total_seconds(), 1)
    return p


def build_started_payload(cfg: Config, src: Path, started_at: datetime) -> dict:
    """v1 payload for the 'started' event. No finished_at, no wall_sec."""
    return _base_payload("started", cfg, src, started_at)


def build_done_payload(
    cfg: Config,
    src: Path,
    info: TranscriptInfo,
    output_stems: dict[str, Path],
    started_at: datetime,
    finished_at: datetime,
) -> dict:
    """v1 payload for the 'done' event. All fields including outputs dict."""
    p = _base_payload("done", cfg, src, started_at, finished_at)
    p.update({
        "status": "done",
        "duration_sec": round(info.duration, 1),
        "language": info.language,
        "backend": info.backend,   # overrides cfg.backend with the richer info.backend string
        "outputs": {fmt: path.name for fmt, path in output_stems.items()},
    })
    return p


def build_failed_payload(
    cfg: Config,
    src: Path,
    error: Exception,
    started_at: datetime,
    finished_at: datetime,
) -> dict:
    """v1 payload for the 'failed' event. Error message only; no traceback."""
    p = _base_payload("failed", cfg, src, started_at, finished_at)
    p.update({
        "status": "failed",
        "error": str(error),
    })
    return p


def _format_ntfy(raw: dict) -> dict:
    """Translate a v1 payload dict into the ntfy JSON publish shape.
    Handles missing optional fields gracefully (failed has no outputs/duration_sec/language).
    Introduces no new fields derived from absolute paths or config secrets."""
    event = raw.get("event", "")
    filename = raw.get("file", "")
    backend = raw.get("backend", "")

    if event == "done":
        duration = raw.get("duration_sec", "?")
        title = f"Transcription done: {filename}"
        message = f"{duration}s audio · {backend}"
        priority = 3
        tags = ["white_check_mark"]
    elif event == "failed":
        error = raw.get("error", "unknown error")
        title = f"Transcription failed: {filename}"
        message = error
        priority = 4
        tags = ["x"]
    elif event == "started":
        title = f"Transcription started: {filename}"
        message = f"Processing with {backend}"
        priority = 2
        tags = ["hourglass_flowing_sand"]
    else:
        title = f"electric-blue: {event}: {filename}"
        message = f"backend: {backend}"
        priority = 3
        tags = []

    return {"title": title, "message": message, "priority": priority, "tags": tags}


def _format_payload(raw: dict, fmt: str) -> dict:
    """Dispatch to provider formatter. Unknown/generic: identity (return raw unchanged)."""
    if fmt == "ntfy":
        return _format_ntfy(raw)
    return raw  # "generic" or any unrecognised value — post the structured v1 dict as-is


def _sign(body_bytes: bytes, secret: str) -> str:
    """Return 'sha256=<hex>' HMAC over body_bytes. Secret never logged or returned."""
    return "sha256=" + _hmac.new(
        secret.encode(), body_bytes, hashlib.sha256
    ).hexdigest()


def _post_with_retry(
    url: str,
    body: dict,
    cfg: Config,
    headers: dict[str, str] | None = None,
) -> None:
    """POST body as JSON to url with bounded retry. Never raises.

    Retry policy (D3 locked):
    - Network errors and HTTP 5xx: retried up to cfg.notify_retries additional times.
    - HTTP 4xx: NOT retried (client error — misconfigured endpoint). Return immediately.
    - Total attempts = 1 + cfg.notify_retries.
    - No backoff between retries in v1.
    All failures logged at WARNING (never ERROR or higher).
    """
    for attempt in range(1 + cfg.notify_retries):
        try:
            r = requests.post(
                url,
                json=body,
                headers=headers or {},
                timeout=cfg.notify_timeout_sec,
            )
            if 400 <= r.status_code < 500:
                log.warning(
                    "notify attempt %d/%d: HTTP %d (4xx client error, not retried)",
                    attempt + 1, 1 + cfg.notify_retries, r.status_code,
                )
                return  # abort — 4xx is not a transient failure
            if r.status_code >= 500:
                log.warning(
                    "notify attempt %d/%d: HTTP %d",
                    attempt + 1, 1 + cfg.notify_retries, r.status_code,
                )
                # fall through to next iteration (retry)
            else:
                return  # 2xx/3xx success
        except Exception as e:
            log.warning(
                "notify attempt %d/%d failed: %s",
                attempt + 1, 1 + cfg.notify_retries, e,
            )
    # All attempts exhausted or aborted — pipeline is unaffected


def notify(cfg: Config, payload: dict) -> None:
    """Post payload to cfg.notify_webhook. No-ops when webhook is unset. Never raises.

    Flow: guard → _format_payload → optional _sign → _post_with_retry.
    Outer try/except catches any exception from formatting or signing.
    """
    if not cfg.notify_webhook:
        return
    try:
        formatted = _format_payload(payload, cfg.notify_format)
        headers: dict[str, str] = {}
        if cfg.notify_hmac_secret:
            body_bytes = json.dumps(
                formatted, sort_keys=True, separators=(",", ":")
            ).encode()
            headers["X-Electric-Blue-Signature"] = _sign(
                body_bytes, cfg.notify_hmac_secret
            )
        _post_with_retry(cfg.notify_webhook, formatted, cfg, headers)
    except Exception as e:
        log.warning("notify setup failed: %s", e)
```

**Correction over DDR §3 proposed code:**
The DDR's proposed `_post_with_retry` calls `r.raise_for_status()` and catches all
exceptions uniformly. This is incorrect for locked D3, which specifies "Retry on network
errors and HTTP 5xx only — NOT on 4xx." With `raise_for_status()`, a 4xx response raises
`requests.exceptions.HTTPError` which is caught and retried — violating REL-7. The corrected
design checks `r.status_code` directly and returns immediately on 4xx.

**requests import at module level:**
`requests` is a core dependency (`pyproject.toml` `dependencies = ["requests>=2.28"]`). The
current stub's lazy import was cautious but unnecessary. Module-level import allows
`monkeypatch.setattr("electric_blue.notify.requests.post", ...)` in tests without the
complexity of mocking a lazy import. This is the canonical mock seam for INV-8.

**HMAC signature vs POST body bytes:**
The HMAC is computed over `json.dumps(formatted, sort_keys=True, separators=(",", ":"))`.
`requests.post(..., json=formatted)` serializes the dict without `sort_keys=True`, so the
HMAC-signed bytes and the wire bytes differ in key ordering only. HMAC-3 documents the
canonical form explicitly. A receiver that parses the JSON body and re-serializes with
`sort_keys=True` can verify the signature. This is an accepted webhook HMAC pattern.

---

## 4. Config Additions — config.py

The four new fields are inserted after `notify_webhook` in the `# Notifications` block.
No existing field is modified, removed, or has its default changed (CFG-6).

### Dataclass field additions (after notify_webhook on line 34 of current config.py)

```python
# Notifications
notify_webhook: str
notify_timeout_sec: float
notify_retries: int
notify_format: str
notify_hmac_secret: str
```

### from_env() additions (after the notify_webhook= line in cls(...))

```python
notify_webhook=os.environ.get("NOTIFY_WEBHOOK", ""),
notify_timeout_sec=float(os.environ.get("NOTIFY_TIMEOUT_SEC", "5.0")),
notify_retries=int(os.environ.get("NOTIFY_RETRIES", "0")),
notify_format=os.environ.get("NOTIFY_FORMAT", "generic").lower(),
notify_hmac_secret=os.environ.get("NOTIFY_HMAC_SECRET", ""),
```

The `.lower()` on `notify_format` satisfies CFG-4 (uppercase env var lowercased at parse time).
The `float()` and `int()` casts satisfy CFG-2 and CFG-3.

### test_config.py update required

`test_defaults()` must add assertions for all four new fields with their defaults (CFG-1).
Existing assertions in `test_defaults()` and all other tests remain unchanged (CFG-6).

New test to add (CFG-4): `test_notify_format_lowercased` — monkeypatch `NOTIFY_FORMAT="NTFY"`,
assert `cfg.notify_format == "ntfy"`.

---

## 5. write_outputs() Return Value — outputs.py

Current signature (line 20–26):
```python
def write_outputs(
    cfg: Config,
    out_dir: Path,
    stem: str,
    segments: list[Segment],
    info: TranscriptInfo,
) -> None:
```

New signature: identical except return type `-> dict[str, Path]`.

### Change strategy

Add `result: dict[str, Path] = {}` at the top of the function body. Assign each written file
to the result dict alongside the existing write call:

```python
result: dict[str, Path] = {}

if "txt" in cfg.output_formats:
    p = out_dir / f"{stem}.txt"
    p.write_text(full + "\n", encoding="utf-8")
    result["txt"] = p

if "srt" in cfg.output_formats:
    p = out_dir / f"{stem}.srt"
    p.write_text("\n".join(lines), encoding="utf-8")
    result["srt"] = p

if "vtt" in cfg.output_formats:
    p = out_dir / f"{stem}.vtt"
    p.write_text("\n".join(lines), encoding="utf-8")
    result["vtt"] = p

if "json" in cfg.output_formats:
    p = out_dir / f"{stem}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    result["json"] = p

return result
```

The result dict contains exactly the formats in `cfg.output_formats` that were written.
If `output_formats=frozenset()`, returns `{}`.

**Behavior-preserving for current callers (INV-3):**
The only current caller is `watcher.process()`, which does:
```python
write_outputs(cfg, cfg.output_dir, src.stem, segments, info)
```
It does not capture the return value. After the change it becomes:
```python
output_stems = write_outputs(cfg, cfg.output_dir, src.stem, segments, info)
```
File writing behavior is identical. No existing test asserts the return value of
`write_outputs()`. All existing `test_outputs.py` tests remain green.

---

## 6. watcher.py Call Sites

### New imports required (add to watcher.py imports)

```python
from datetime import datetime, timezone
from .notify import (
    notify,
    build_done_payload,
    build_failed_payload,
    build_started_payload,
)
```

Remove the existing `import time` usage for `t0` (it is still needed for `time.sleep` in
`is_stable()` and `run_watch()`). The `t0 = time.time()` pattern in `process()` is retired.

### Design decision: started_at lives in handle(), not process()

The DDR's §7 shows `started_at` both inside `process()` (where it is set) and inside
`handle()`'s except clause (where it is used for `build_failed_payload`). These are
contradictory: a name set inside `process()` is not accessible in `handle()`'s except clause
after `process()` raises.

**Resolution:** `started_at` is set in `handle()` before calling `process()`, and passed as
an argument to `process()`. This satisfies INT-4 ("a single `datetime.now(timezone.utc)` call")
and INT-2 (`build_failed_payload` is callable in `handle()`'s except clause). The timestamp
is passed to `build_started_payload`, `build_done_payload`, and `build_failed_payload` via the
same object reference — one call, no duplication.

### Updated process() signature

```python
def process(cfg: Config, src: Path, started_at: datetime) -> None:
```

This is a breaking change to `process()`'s call signature, but `process()` is an internal
function called only from `handle()`. No external callers exist. The change is owned and named
in the PR description (INV-3).

### Updated process() body

```python
def process(cfg: Config, src: Path, started_at: datetime) -> None:
    log.info("Processing (%s): %s", cfg.backend, src.name)
    notify(cfg, build_started_payload(cfg, src, started_at))      # D6 — fires before transcribe
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
```

Notes:
- `t0 = time.time()` is removed. `wall` in the log line uses `(finished_at - started_at).total_seconds()` which is the same computation via a different clock source. The log output is functionally equivalent.
- `notify()` never raises (by design), so neither call can propagate an exception into `process()`.
- `output_stems` captures the new return value of `write_outputs()`.

### Updated handle() body

```python
def handle(cfg: Config, path: Path) -> None:
    if path.suffix.lower() not in cfg.media_exts or not is_stable(path, cfg.stability_seconds):
        return
    started_at = datetime.now(timezone.utc)       # single timestamp — shared across all payloads
    try:
        process(cfg, path, started_at)
        shutil.move(str(path), str(cfg.done_dir / path.name))
    except Exception as e:
        log.error("Failed on %s: %s", path.name, e)
        notify(cfg, build_failed_payload(cfg, path, e, started_at, datetime.now(timezone.utc)))
        shutil.move(str(path), str(cfg.failed_dir / path.name))
```

**INV-1 compliance confirmed:**
- Move to `done_dir` is strictly after `process()` returns (outputs written, notify called
  inside process before return).
- Exception path moves to `failed_dir` after the notify call. `notify()` never raises, so
  the `shutil.move` to `failed_dir` is always reached.
- Move ordering is unchanged from current behavior.

**INV-7 compliance:** `notify()` is called with a payload built by `build_failed_payload()`,
which calls `_base_payload()` — which uses `src.name` only, not `str(src)`. The `str(error)`
field carries only the exception message. No absolute path or secret appears in the payload.

---

## 7. Redaction: Enforced by Construction (INV-7)

**How a test can prove no absolute path leaks:**

```python
import json
from pathlib import Path
payload = build_done_payload(cfg, Path("/home/user/inbox/meeting.mp4"), info, stems, t0, t1)
serialized = json.dumps(payload)
assert "/home" not in serialized
assert "inbox" not in serialized
assert "meeting.mp4" in payload["file"]     # filename only
```

**How a test can prove no api_key leaks:**

```python
cfg_with_key = dataclasses.replace(cfg, api_key="sk-secret")
payload = build_done_payload(cfg_with_key, src, info, stems, t0, t1)
assert "sk-secret" not in json.dumps(payload)
```

**Structural guarantees (by construction, not convention):**

1. `_base_payload` sets `"file": src.name` — `Path.name` is the final component only, never
   the full path string.
2. `_base_payload` references only `cfg.backend` (an identifier like `"api"`) from `Config`.
   It does not reference `cfg.api_key`, `cfg.notify_hmac_secret`, `cfg.notify_webhook`, or
   any directory field.
3. `build_done_payload` adds `info.backend` (e.g. `"api:whisper-large-v3-turbo"`), `info.language`,
   `info.duration`, and `{fmt: path.name}` — all filename-safe values from `TranscriptInfo`.
4. `build_failed_payload` adds `str(error)` — exception messages are not guaranteed to be
   secret-free in general, but `RuntimeError`, `ConnectionError`, and similar pipeline errors
   do not typically embed API keys. This is a convention, not a structural guarantee; it is
   acceptable for v1.
5. `_format_ntfy` only reads fields from the already-redacted `raw` dict using `.get()`. It
   cannot introduce fields not present in the input, so no new path or secret leakage is
   possible through the formatter layer.
6. `_sign` never logs `secret`, `body_bytes`, or the computed HMAC value (only the header
   value leaves the function, to be sent as an HTTP header).

---

## 8. Characterization-Test Strategy

### File: tests/test_char_notify.py (written before any code changes)

These four tests pin the CURRENT `notify(cfg, text, meta)` stub's observable behaviors.
They must be green against the stub before any implementation change is made.

```
CHAR-1 [survives]: notify_webhook="" — requests.post never called
CHAR-2 [survives]: requests.post raises Exception — notify() returns normally
CHAR-3 [superseded]: notify_webhook set + meta={"file": "x.mp4"} — requests.post called
                     with json={"text": "hello", "file": "x.mp4"}
CHAR-4 [superseded]: notify_webhook set — requests.post called with timeout=15
```

**Superseded char tests:**
CHAR-3 and CHAR-4 document behavior that is intentionally replaced by the new design. After
the implementation sprint:
- CHAR-3 is superseded by `test_posts_generic_payload` (FMT-1): the new payload shape is
  the structured v1 dict, not `{"text": ..., **meta}`.
- CHAR-4 is superseded by `test_timeout_from_config` (REL-1): timeout comes from
  `cfg.notify_timeout_sec` (default 5.0), not the hardcoded literal 15.

CHAR-3 and CHAR-4 should be **deleted** in the same commit that rewrites `notify.py`. The PR
description names them as owned supersessions (INV-3). CHAR-1 and CHAR-2 remain in the test
suite after the rewrite because the surviving behaviors are preserved by the new design.

**Mock seam for char tests (current stub):**
```python
monkeypatch.setattr("electric_blue.notify.requests", mock_requests_module)
```
This does not work for the current stub because `requests` is imported lazily inside the
function body. For the char tests, use:
```python
with patch("electric_blue.notify.requests") as mock_req:
    ...
```
OR monkeypatch the module's lazy import target. After the rewrite (module-level import),
the mock target is `electric_blue.notify.requests.post`.

For CHAR tests only: since `requests` is imported inside the try block in the current stub,
char tests should use `unittest.mock.patch("builtins.__import__", ...)` or, more practically,
set up a minimal real `requests` mock via `sys.modules`:

```python
import sys, types, unittest.mock

def test_char_3(monkeypatch, tmp_path):
    fake_requests = types.ModuleType("requests")
    fake_requests.post = unittest.mock.MagicMock()
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    ...
```

This is the correct hermetic seam for a lazy-import module. Alternatively, since `requests`
is always installed (core dep), `monkeypatch.setattr("requests.post", mock_fn)` works:
the lazy `import requests` inside notify.py will resolve to the already-imported module where
the attr has been patched.

### File: tests/test_notify.py (written against the new implementation)

All tests patch `electric_blue.notify.requests.post` via monkeypatch (module-level import).
Config instances are built via `dataclasses.replace(Config.from_env(), ...)` with a minimal
set of monkeypatched env vars, or via a shared fixture.

| Test name | Covers |
|-----------|--------|
| `test_done_payload_fields` | PAY-1: all expected fields present and typed correctly |
| `test_failed_payload_fields` | PAY-2: event/status/error present; no duration_sec/language/outputs |
| `test_wall_sec_is_derived` | PAY-3+PAY-4: 90s and 86400s gaps yield correct wall_sec |
| `test_started_event_omits_finished` | STA-1: no finished_at, no wall_sec |
| `test_no_absolute_paths` | RED-1+RED-2: file==filename; no "/home" in serialized payload |
| `test_no_api_key_in_payload` | RED-3: api_key not in json.dumps(payload) |
| `test_no_op_when_unset` | CHAR-1 (survives): requests.post not called when webhook="" |
| `test_swallows_exception` | CHAR-2 (survives): requests.post raises; notify returns normally |
| `test_posts_generic_payload` | FMT-1: notify_format="generic"; post called with v1 dict |
| `test_format_ntfy_done` | FMT-2: _format_ntfy(done_payload) has title/message/priority/tags |
| `test_format_ntfy_failed_no_optional_fields` | FMT-2 edge: failed payload missing optional fields; no raise |
| `test_swallows_connection_error` | REL-2: ConnectionError; notify returns normally |
| `test_swallows_timeout` | REL-3: requests.Timeout; notify returns normally |
| `test_swallows_http_500` | REL-4: HTTP 500; notify returns normally |
| `test_retry_on_5xx` | REL-5+REL-6: notify_retries=1; 500 then 200; called twice |
| `test_no_retry_on_4xx` | REL-7: notify_retries=1; HTTP 400; called exactly once |
| `test_warning_level_only` | REL-8: all failures log at WARNING, not ERROR |
| `test_timeout_from_config` | REL-1: timeout= argument equals cfg.notify_timeout_sec |
| `test_hmac_header_present` | HMAC-2+HMAC-3: secret set; header present; value matches sha256=... |
| `test_hmac_absent_when_no_secret` | HMAC-1: secret=""; no X-Electric-Blue-Signature header |
| `test_hmac_over_formatted_body` | HMAC-4: signing happens post-_format_payload |
| `test_timestamps_parse_as_utc` | PAY-5: started_at/finished_at parse with fromisoformat() + UTC tz |
| `test_watcher_started_fires_before_transcribe` | STA-2: integration via handle(); started notify precedes transcribe |
| `test_watcher_done_on_success` | INT-1: successful transcription triggers build_done_payload notify |
| `test_watcher_failed_on_exception` | INT-2: exception triggers build_failed_payload notify before move |

---

## 9. Mock Seams and Hermeticity (INV-8)

All `test_notify.py` tests are hermetic:
- `requests.post` is monkeypatched at `electric_blue.notify.requests.post`
- No real network calls
- No real filesystem (payload builders are pure functions)
- Config instances created via `dataclasses.replace(base_cfg, notify_webhook="http://fake/hook", ...)`

Fixture pattern:

```python
import dataclasses
import pytest
from electric_blue.config import Config

@pytest.fixture()
def webhook_cfg(monkeypatch):
    """Config with webhook set and safe defaults for all new fields."""
    monkeypatch.delenv("NOTIFY_WEBHOOK", raising=False)
    cfg = dataclasses.replace(
        Config.from_env(),
        notify_webhook="http://fake.invalid/hook",
        notify_timeout_sec=1.0,
        notify_retries=0,
        notify_format="generic",
        notify_hmac_secret="",
    )
    return cfg
```

For watcher integration tests (STA-2, INT-1, INT-2), also monkeypatch `transcribe` and
assert on the notify call arguments:

```python
monkeypatch.setattr("electric_blue.watcher.transcribe", fake_transcribe_fn)
monkeypatch.setattr("electric_blue.watcher.notify", mock_notify)
```

This patches `notify` in the `watcher` module's namespace (post-import binding), so the
watcher call sites are tested without exercising the full notify stack.

---

## 10. File-by-File Change Map

| File | Change type | Description |
|------|-------------|-------------|
| `src/electric_blue/notify.py` | Rewrite | 25 lines → ~125 lines. New imports (hashlib, hmac, json, datetime, Path, requests at module level). Seven new functions (_base_payload, build_*_payload x3, _format_ntfy, _format_payload, _sign, _post_with_retry). Public API changes from notify(cfg, text, meta) to notify(cfg, payload). |
| `src/electric_blue/config.py` | Additive | +4 dataclass fields + 4 from_env() lines. No existing fields change. |
| `src/electric_blue/outputs.py` | Targeted | write_outputs() return type None → dict[str, Path]. Add result dict, populate alongside existing writes, return it. ~10 lines touched. |
| `src/electric_blue/watcher.py` | Call sites | +2 imports (datetime, timezone, 3 payload builders). process() signature gains started_at param. handle() stamps started_at, passes to process(), calls build_failed_payload in except. t0/time.time() wall-time removed from process(). |
| `tests/test_char_notify.py` | New file | 4 characterization tests (CHAR-1 through CHAR-4). Written and committed before any code changes. |
| `tests/test_notify.py` | New file | 25 tests covering the new implementation (see section 8). Written after the rewrite. |
| `tests/test_config.py` | Additive | test_defaults() adds 4 new default assertions. New test_notify_format_lowercased. |
| `tests/test_outputs.py` | Additive | 2 new tests (OUT-1, OUT-2). All existing tests unchanged. |
| `tests/test_watcher.py` | Verify | Existing tests call handle() which is unchanged externally. Verify they remain green; no edits anticipated. |

### Import graph (after this sprint)

```
watcher.py
  ├── notify.py          (notify, build_done_payload, build_failed_payload, build_started_payload)
  │     ├── config.py   (Config)
  │     ├── models.py   (TranscriptInfo)
  │     └── requests    (third-party, core dep)
  ├── config.py          (Config)
  ├── outputs.py         (write_outputs)
  │     ├── config.py   (Config)
  │     └── models.py   (Segment, TranscriptInfo)
  └── backends/          (transcribe)
        └── config.py   (Config)
```

No new third-party dependencies are introduced.

---

## 11. Patterns

| Pattern | Usage | Rationale |
|---------|-------|-----------|
| Pure builder functions | All build_*_payload functions | No side effects; testable without mocking anything; redaction is structural (INV-7) |
| Module-level requests import | notify.py top of file | Requests is a core dep; module-level import allows clean mock seam at electric_blue.notify.requests.post (INV-8) |
| Never-raises public function | notify() and _post_with_retry() | Pipeline resilience — no exception from the notify path may reach the transcription engine (INV-1) |
| Outer guard + inner exception handler | notify() structure | Early return on empty webhook; outer try/except catches formatter/signer errors; _post_with_retry handles its own exceptions |
| dataclasses.replace for test fixtures | All notify tests | Frozen dataclass (INV-3); no env mutation needed for most tests |
| Characterization tests first | test_char_notify.py committed before code changes | INV-3 compliance — behavior change is pinned before the delta |
| Formatter as identity for unknown format | _format_payload default case | Forward-compatible; new format strings added later without breaking existing deployments |

---

## 12. Flagged Current-Behavior Concerns

**FLAG-1 — DDR _post_with_retry retries on 4xx (bug in proposed code)**
The DDR's §3 proposed `_post_with_retry` uses `r.raise_for_status()` then catches `Exception`
uniformly. This retries 4xx responses, violating locked D3 ("Retry on network errors and HTTP
5xx only — NOT on 4xx"). This architecture corrects it with explicit `r.status_code` branching.
No human decision needed — D3 is locked. Called out as a correction over the DDR.

**FLAG-2 — started_at scope inconsistency in DDR §7**
The DDR shows `started_at` set inside `process()` but used in `handle()`'s except clause.
Python scoping makes this impossible as written. Architecture resolves it by moving
`started_at` to `handle()` and passing it as an argument to `process()`. Satisfies all
INT-* requirements. No HALT; the correct design is clear.

**FLAG-3 — t0/time.time() removal changes wall-time reference point**
Currently `t0 = time.time()` is set just before `transcribe()`. In the new design, `started_at`
is set in `handle()` before the `started` notification, which is before `transcribe()`. The
`wall_sec` in the payload will include the started-event HTTP round-trip time (bounded by
`notify_timeout_sec`, default 5s). This is a slight behavior change in what "wall time" means
in the log line and payload, but it is an intentional and documented owned change (INT-4 requires
the single timestamp). The difference is bounded by the notify timeout and is not operationally
significant.

**FLAG-4 — Existing watcher tests do not mock notify()**
`test_handle_success_moves_to_done` and `test_handle_failure_moves_to_failed` call `handle()`
which now calls `notify()` in both the success and failure paths (via `process()` and directly).
Since `notify_webhook=""` by default in test config, `notify()` returns immediately with no
side effects. No test changes required. However, if a future test adds `notify_webhook` to
the config fixture, it would require mocking `requests.post`. This is a minor maintainability
note, not a blocker.

---

## Dependencies

No new dependencies. All required stdlib modules (hashlib, hmac, json, datetime) are built in.
`requests>=2.28` is already a core dependency.

| Dependency | Version | Purpose |
|------------|---------|---------|
| `requests` | `>=2.28` (core dep) | HTTP POST; already in pyproject.toml |
| `hashlib` | stdlib | SHA-256 digest for HMAC |
| `hmac` | stdlib | HMAC-SHA256 signing |
| `json` | stdlib | Canonical JSON serialization for HMAC |
| `datetime` | stdlib | UTC timestamp generation and ISO-8601 serialization |

---

## Status

- Components defined: 13
- Schemas defined: 6 (done payload, failed payload, started payload, ntfy formatted payload,
  Config additions, write_outputs return type)
- Correction over DDR: 1 (FLAG-1 — 4xx retry bug)
- Design refinements over DDR: 1 (FLAG-2 — started_at scoping)
- Flagged behavioral notes: 2 (FLAG-3, FLAG-4 — non-blocking, no human decision needed)
- Status: COMPLETE
