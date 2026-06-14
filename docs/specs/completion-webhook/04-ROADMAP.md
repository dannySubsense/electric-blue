# Implementation Roadmap: completion-webhook

- **Status:** DRAFT
- **Author:** reed
- **Date:** 2026-06-14
- **Requirements:** 01-REQUIREMENTS.md
- **Architecture:** 02-ARCHITECTURE.md
- **DDR:** DDR-04-completion-webhook.md
- **Sprint:** completion-webhook (GitHub issue #10)

---

## Overview

Six slices (S1–S6). S1–S5 are code slices; S6 is the final process gate. Each slice ends gate-green
before the next begins (CADENCE P3). Characterization tests (S1) are committed and green against the
**pre-change** stub before any code is touched (INV-3). Two corrections from the DDR are embedded in
the relevant slice steps; they do not require a human decision.

Gate command at every slice boundary:

```
PATH="$PWD/.venv/bin:$PATH" make gate
```

---

## Slice Summary

| Slice | Title | Key Deliverable | Gate |
|-------|-------|----------------|------|
| S1 | Characterization tests | Pin current stub behavior | 4 CHAR tests green |
| S2 | Config additions | 4 new frozen fields + from_env() | CFG-1..7 pass |
| S3 | Payload builders + redaction tests | Pure builder functions + 7 tests | PAY/STA/RED tests pass |
| S4 | write_outputs() return value | `dict[str, Path]` return type | OUT-1..3 pass; existing tests unchanged |
| S5 | notify() rewrite + watcher integration | Full notify.py + watcher call sites | All 15 DDR §8 in-scope tests pass |
| S6 | Final gate + smoke + Frank | SHIP verdict | Frank BUILD gate SHIP |

---

## Dependency Graph

```
S1 ─► S2 ─► S3 ─► S4 ─► S5 ─► S6
```

- **S1 → S2**: INV-3 requires char tests committed and green before any code change.
- **S2 → S3**: Builders need new Config fields (`notify_timeout_sec`, `notify_retries`,
  `notify_format`, `notify_hmac_secret`) in test fixtures; those fields are added in S2.
- **S3 → S4**: Logical sequence per DDR §Sequencing (builders before outputs change). S4 does not
  technically depend on S3 code, but the DDR step order is preserved.
- **S4 → S5**: S5 `watcher.py` captures `output_stems = write_outputs(...)` — requires S4's
  return-value change to be already in place so the value is available for `build_done_payload()`.
- **S5 → S6**: All code must be merged before final process gate.

No circular dependencies.

---

## Behavior-Preservation Checkpoints

At every slice boundary that touches `notify.py`, `watcher.py`, or `outputs.py`, the following
checks confirm INV-1 (no data loss) and INV-3 (behavior preserved unless owned):

| After slice | Char tests required green | Notes |
|-------------|--------------------------|-------|
| S1 | CHAR-1, CHAR-2, CHAR-3, CHAR-4 | Baseline established; no code changed |
| S2 | CHAR-1, CHAR-2, CHAR-3, CHAR-4 | Config additions are additive; notify stub unchanged |
| S3 | CHAR-1, CHAR-2, CHAR-3, CHAR-4 | Builders added to notify.py; old notify() stub untouched |
| S4 | CHAR-1, CHAR-2, CHAR-3, CHAR-4 | Outputs change; notify/watcher untouched |
| S5 | CHAR-1 (as `test_no_op_when_unset`), CHAR-2 (as `test_swallows_exception`) survive; CHAR-3 and CHAR-4 deleted as named owned supersessions | Rewrite commit; see S5 steps for owned change list |

INV-1 compliance at S5: `shutil.move` to `done_dir` is strictly after `process()` returns
(outputs written, done-notify called inside process). `shutil.move` to `failed_dir` is guaranteed
because `notify()` never raises, so the move always executes.

---

## DDR Corrections Embedded in Slices

Two corrections from the architecture over the DDR's proposed code are incorporated here without
requiring human decisions (the architecture documents them as FLAG-1 and FLAG-2):

**Correction 1 (FLAG-1 — 4xx-no-retry, in S5):** The DDR §3 proposed `_post_with_retry` calls
`r.raise_for_status()` and catches all exceptions uniformly. This would retry HTTP 4xx responses,
violating locked D3 ("Retry on network errors and HTTP 5xx only — NOT on 4xx"). S5 implements the
corrected design: explicit `r.status_code` branching returns immediately on 4xx without retry.
Test REL-7 (`test_no_retry_on_4xx`) verifies this.

**Correction 2 (FLAG-2 — started_at scoping, in S5):** The DDR §7 shows `started_at` set inside
`process()` but used in `handle()`'s except clause. A name set inside `process()` is inaccessible
in `handle()`'s except clause after `process()` raises. S5 resolves by stamping `started_at` in
`handle()` before calling `process()`, and passing it as a parameter. INT-4 verifies the single
`datetime.now(timezone.utc)` call.

---

## S1 — Characterization Tests

**Goal:** Pin the current `notify(cfg, text, meta)` stub's four observable behaviors against the
pre-change code. No production code is touched in this slice.

**Depends on:** nothing

**Files:**
- `tests/test_char_notify.py` — create (4 tests)

**Steps:**

1. Create `tests/test_char_notify.py` with the four char tests listed below. Mock seam: because
   `requests` is imported lazily inside the stub's `try` block, use
   `monkeypatch.setattr("requests.post", mock_fn)` (the lazy `import requests` resolves to the
   already-imported module where `post` is patched), or use `sys.modules` injection per architecture
   §8. Both patterns work against the current stub.

2. CHAR-1 (`test_char_no_op_when_webhook_unset`): `cfg.notify_webhook=""` → `requests.post` is
   never called. Marked `survives` in docstring.

3. CHAR-2 (`test_char_never_raises`): `requests.post` raises `Exception("boom")` →
   `notify()` returns normally. Marked `survives` in docstring.

4. CHAR-3 (`test_char_old_payload_shape`): `cfg.notify_webhook` set, `meta={"file": "x.mp4"}` →
   `requests.post` called once with `json={"text": "hello", "file": "x.mp4"}`. Marked `superseded`
   in docstring (superseded by `test_posts_generic_payload` in S5).

5. CHAR-4 (`test_char_timeout_15`): `cfg.notify_webhook` set → `requests.post` called with
   `timeout=15`. Marked `superseded` in docstring (superseded by `test_timeout_from_config` in S5).

6. Run gate: all four tests green; no production file is modified.

**Verification gate:**

```
PATH="$PWD/.venv/bin:$PATH" make gate
```

Pass condition: all existing tests pass AND 4 new CHAR tests pass. Zero production files changed.

ACs satisfied: CHAR-1, CHAR-2, CHAR-3, CHAR-4

**Rollback:** delete `tests/test_char_notify.py` (no production code to revert).

---

## S2 — Config Additions

**Goal:** Add four new frozen `Config` fields with safe defaults. Update `test_config.py` to cover
all new fields. No existing field is modified or removed.

**Depends on:** S1 (INV-3: char tests committed and green before any code change)

**Files:**
- `src/electric_blue/config.py` — modify (additive)
- `tests/test_config.py` — modify (additive)

**Steps:**

1. In `src/electric_blue/config.py`, insert four fields in the `# Notifications` block after
   `notify_webhook: str`:

   ```python
   notify_timeout_sec: float
   notify_retries: int
   notify_format: str
   notify_hmac_secret: str
   ```

2. In `from_env()`, add four lines after the `notify_webhook=` line:

   ```python
   notify_timeout_sec=float(os.environ.get("NOTIFY_TIMEOUT_SEC", "5.0")),
   notify_retries=int(os.environ.get("NOTIFY_RETRIES", "0")),
   notify_format=os.environ.get("NOTIFY_FORMAT", "generic").lower(),
   notify_hmac_secret=os.environ.get("NOTIFY_HMAC_SECRET", ""),
   ```

   The `.lower()` on `notify_format` satisfies CFG-4.

3. In `tests/test_config.py`, extend `test_defaults()` with four additional assertions
   (after the existing `assert cfg.notify_webhook == ""`):

   ```python
   assert cfg.notify_timeout_sec == 5.0
   assert isinstance(cfg.notify_timeout_sec, float)
   assert cfg.notify_retries == 0
   assert isinstance(cfg.notify_retries, int)
   assert cfg.notify_format == "generic"
   assert cfg.notify_hmac_secret == ""
   ```

4. Add a new test `test_notify_format_lowercased` that monkeypatches `NOTIFY_FORMAT="NTFY"` and
   asserts `cfg.notify_format == "ntfy"`.

5. Confirm `test_config_is_frozen` still covers that assignment to a new field raises
   `AttributeError` or `TypeError` (CFG-7 — frozen dataclass is already validated by the existing
   test; no new test needed if the pattern is already exercised).

6. Run gate. All CHAR-1..4 tests still green.

**Verification gate:**

```
PATH="$PWD/.venv/bin:$PATH" make gate
```

Pass condition: `test_defaults()` passes with new assertions; `test_notify_format_lowercased` passes;
all existing `test_config.py` tests unchanged and passing; CHAR-1..4 still green.

ACs satisfied: CFG-1, CFG-2, CFG-3, CFG-4, CFG-5, CFG-6, CFG-7

**Rollback:** revert `src/electric_blue/config.py` and `tests/test_config.py` to pre-S2 state.

---

## S3 — Payload Builders + Redaction Tests

**Goal:** Add `_base_payload`, `build_started_payload`, `build_done_payload`, and
`build_failed_payload` as pure functions to `notify.py`. Write tests covering payload structure,
timing, started-event fields, and redaction guarantees. The existing `notify(cfg, text, meta)` stub
is NOT touched; this is a purely additive change.

**Depends on:** S2 (test fixtures use new Config fields via `dataclasses.replace`)

**Files:**
- `src/electric_blue/notify.py` — modify (additive: 4 new functions + new imports)
- `tests/test_notify.py` — create (7 tests covering PAY/STA/RED ACs)

**Steps:**

1. Add imports to `src/electric_blue/notify.py` (at the top, after existing imports):

   ```python
   import json
   from datetime import datetime
   from pathlib import Path
   from .models import TranscriptInfo
   ```

   Do NOT add `import requests` at module level yet (stays lazy inside the existing stub). Do NOT
   add `import hashlib` or `import hmac` yet. Those come in S5.

2. Add `_base_payload(event, cfg, src, started_at, finished_at=None) -> dict` per architecture §3.
   Uses `src.name` (never `str(src)`); only reads `cfg.backend`; never touches `cfg.api_key` or
   `cfg.notify_hmac_secret`.

3. Add `build_started_payload(cfg, src, started_at) -> dict` — delegates to `_base_payload` with
   `finished_at=None`.

4. Add `build_done_payload(cfg, src, info, output_stems, started_at, finished_at) -> dict` per
   architecture §3.

5. Add `build_failed_payload(cfg, src, error, started_at, finished_at) -> dict` per architecture §3.

6. Create `tests/test_notify.py` with the following tests (use `dataclasses.replace(Config.from_env(),
   notify_webhook="http://fake.invalid/hook", notify_timeout_sec=1.0, notify_retries=0,
   notify_format="generic", notify_hmac_secret="")` fixture or inline construction):

   - `test_done_payload_fields` (PAY-1): all 11 required keys present with correct types.
   - `test_failed_payload_fields` (PAY-2): event/status/error present; `duration_sec`, `language`,
     `outputs` absent.
   - `test_wall_sec_is_derived` (PAY-3 + PAY-4): 90s gap → `wall_sec == 90.0`; 86400s gap →
     `wall_sec == 86400.0`.
   - `test_started_event_omits_finished` (STA-1): `finished_at` key absent; `wall_sec` key absent.
   - `test_no_absolute_paths` (RED-1 + RED-2): `src=Path("/home/user/inbox/meeting.mp4")` →
     `payload["file"] == "meeting.mp4"`; `"/home"` not in `json.dumps(payload)`.
   - `test_no_api_key_in_payload` (RED-3): `cfg.api_key="sk-secret"` →
     `"sk-secret" not in json.dumps(payload)`.
   - `test_timestamps_parse_as_utc` (PAY-5): `datetime.fromisoformat(payload["started_at"])` succeeds
     and carries UTC timezone info; same for `finished_at`.

7. Run gate. All CHAR-1..4 tests still green. New builder/redaction tests green.

**Verification gate:**

```
PATH="$PWD/.venv/bin:$PATH" make gate
```

Pass condition: 7 new tests in `test_notify.py` pass; CHAR-1..4 still green; old `notify()` stub
unchanged and still callable with `(cfg, text, meta)`.

DDR §8 tests satisfied here: `test_done_payload_fields`, `test_failed_payload_fields`,
`test_wall_sec_is_derived`, `test_started_event_omits_finished`, `test_no_absolute_paths`,
`test_no_api_key_in_payload`.

ACs satisfied: PAY-1, PAY-2, PAY-3, PAY-4, PAY-5, STA-1, RED-1, RED-2, RED-3, RED-4

**Rollback:** revert `src/electric_blue/notify.py` to pre-S3 (remove 4 builder functions + new
imports); delete `tests/test_notify.py`.

---

## S4 — write_outputs() Return Value

**Goal:** Update `write_outputs()` to return `dict[str, Path]` mapping each written format to its
absolute output path. All existing file-writing behavior is identical; only the return type changes.

**Depends on:** S3 (logical DDR step order; also ensures existing gate is fully green before this
purely additive outputs change)

**Files:**
- `src/electric_blue/outputs.py` — modify (targeted: ~10 lines)
- `tests/test_outputs.py` — modify (additive: 2 new tests)

**Steps:**

1. In `src/electric_blue/outputs.py`, change the return annotation of `write_outputs` from `-> None`
   to `-> dict[str, Path]`.

2. Add `result: dict[str, Path] = {}` at the top of the function body, before the `seg_dicts` line.

3. In each format block, assign to `result` alongside the existing write call. For example the `txt`
   block becomes:

   ```python
   if "txt" in cfg.output_formats:
       p = out_dir / f"{stem}.txt"
       p.write_text(full + "\n", encoding="utf-8")
       result["txt"] = p
   ```

   Apply the same pattern for `srt`, `vtt`, and `json` blocks.

4. Add `return result` as the last line of the function body.

5. The existing caller in `watcher.py` (`write_outputs(cfg, cfg.output_dir, src.stem, segments, info)`)
   ignores the return value; Python does not raise on an ignored return value. No change to
   `watcher.py` in this slice.

6. In `tests/test_outputs.py`, add two new tests:

   - `test_return_value_all_formats` (OUT-1): `cfg.output_formats = frozenset({"txt","srt","vtt","json"})` →
     returned dict has exactly 4 entries; each value is a `Path` ending in the correct stem + extension.
   - `test_return_value_single_format` (OUT-2): `cfg.output_formats = frozenset({"txt"})` →
     returned dict has exactly 1 entry `{"txt": Path(...)}`.

7. Verify all 6 existing `test_outputs.py` tests remain green (OUT-3). File content is unchanged.

**Verification gate:**

```
PATH="$PWD/.venv/bin:$PATH" make gate
```

Pass condition: 2 new return-value tests pass; all 6 existing `test_outputs.py` tests still green;
CHAR-1..4 still green; zero behavior change to watcher (it ignores the return value).

ACs satisfied: OUT-1, OUT-2, OUT-3

**Rollback:** revert `src/electric_blue/outputs.py` return type/body to `-> None`; remove 2 new
tests from `tests/test_outputs.py`.

---

## S5 — notify() Rewrite + Watcher Call Site Integration

**Goal:** Complete the notify.py rewrite (new `notify(cfg, payload)` function replacing the 3-arg
stub; add `_format_payload`, `_format_ntfy`, `_sign`, `_post_with_retry` with the corrected 4xx
no-retry logic); update `watcher.py` call sites (`handle()` stamps `started_at`, `process()` gains
`started_at` parameter, call sites use payload builders, `output_stems` captured); delete CHAR-3 and
CHAR-4 (named owned supersessions); update CHAR-1 and CHAR-2 to the new calling convention; add
all reliability, formatting, HMAC, and watcher-integration tests.

**Depends on:** S3 (builder functions must be in notify.py), S4 (write_outputs() must return
`dict[str, Path]` for `output_stems` capture in watcher.py)

**Files:**
- `src/electric_blue/notify.py` — rewrite (replace `notify(cfg, text, meta)` stub with new function;
  add `_format_payload`, `_format_ntfy`, `_sign`, `_post_with_retry`; add `import requests` at
  module level; add `import hashlib`, `import hmac as _hmac`)
- `src/electric_blue/watcher.py` — targeted edits (new imports; `handle()` stamps `started_at`;
  `process()` signature gains `started_at: datetime` param; call sites replaced; `t0`/`time.time()`
  wall-time removed from `process()`)
- `tests/test_char_notify.py` — modify (delete CHAR-3, CHAR-4; update CHAR-1, CHAR-2 for new
  2-arg notify() signature — owned changes listed in PR description)
- `tests/test_notify.py` — modify (add 19 new tests covering REL, FMT, HMAC, watcher integration)
- `tests/test_watcher.py` — verify only (no edits anticipated; existing tests should pass unchanged)

**Steps:**

1. **notify.py: add module-level imports.** Replace the existing `import logging / from .config
   import Config` block with the full import list from architecture §3:

   ```python
   import hashlib
   import hmac as _hmac
   import json
   import logging
   from datetime import datetime
   from pathlib import Path

   import requests

   from .config import Config
   from .models import TranscriptInfo
   ```

   The lazy `import requests` inside the old stub's try block is removed along with the old stub.

2. **notify.py: add `_format_ntfy(raw: dict) -> dict`.** Handles all three event types and missing
   optional fields (failed has no `outputs`, `duration_sec`, `language`). Does not introduce fields
   derived from absolute paths or config secrets.

3. **notify.py: add `_format_payload(raw: dict, fmt: str) -> dict`.** Dispatches to `_format_ntfy`
   when `fmt == "ntfy"`; returns `raw` unchanged for `"generic"` or any unrecognised value.

4. **notify.py: add `_sign(body_bytes: bytes, secret: str) -> str`.** Returns
   `"sha256=" + _hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()`. Secret is never
   logged, never returned in any field — RED-4 compliance.

5. **notify.py: add `_post_with_retry(url, body, cfg, headers=None) -> None`.** Use explicit
   `r.status_code` branching per the DDR Correction 1 (FLAG-1):
   - HTTP 4xx → log at WARNING, `return` immediately (do NOT retry — D3 locked).
   - HTTP 5xx → log at WARNING, fall through to next retry iteration.
   - Network exception → log at WARNING, fall through to next retry.
   - Total loop iterations: `range(1 + cfg.notify_retries)`.
   - Never raises.

6. **notify.py: add new `notify(cfg: Config, payload: dict) -> None`.** Flow: guard on
   `cfg.notify_webhook` → `_format_payload(payload, cfg.notify_format)` → optionally compute HMAC
   signature header → `_post_with_retry(...)`. Outer `try/except Exception` catches any error from
   formatting or signing. Logs at WARNING, never at ERROR. Never raises.

7. **watcher.py: update imports.**

   ```python
   from datetime import datetime, timezone
   from .notify import (
       notify,
       build_done_payload,
       build_failed_payload,
       build_started_payload,
   )
   ```

   `import time` remains (still needed for `time.sleep` in `is_stable()` and `run_watch()`).

8. **watcher.py: update `handle()`.** Per DDR Correction 2 (FLAG-2 — `started_at` scoping):

   ```python
   def handle(cfg: Config, path: Path) -> None:
       if path.suffix.lower() not in cfg.media_exts or not is_stable(path, cfg.stability_seconds):
           return
       started_at = datetime.now(timezone.utc)   # single timestamp — INT-4
       try:
           process(cfg, path, started_at)
           shutil.move(str(path), str(cfg.done_dir / path.name))
       except Exception as e:
           log.error("Failed on %s: %s", path.name, e)
           notify(cfg, build_failed_payload(cfg, path, e, started_at, datetime.now(timezone.utc)))
           shutil.move(str(path), str(cfg.failed_dir / path.name))
   ```

   `notify()` never raises, so `shutil.move` to `failed_dir` is always reached (INV-1).

9. **watcher.py: update `process()`.** New signature: `def process(cfg: Config, src: Path,
   started_at: datetime) -> None`. Remove `t0 = time.time()` and the `time.time() - t0` expression.
   Replace `(time.time() - t0)` in the log line with `(finished_at - started_at).total_seconds()`.
   Fire `notify(cfg, build_started_payload(cfg, src, started_at))` before `transcribe()` (D6).
   Capture `output_stems = write_outputs(...)`. Fire `notify(cfg, build_done_payload(..., output_stems,
   started_at, finished_at))` after writing outputs.

10. **test_char_notify.py: owned supersessions.** In the same commit as the notify.py rewrite:
    - Delete `test_char_old_payload_shape` (CHAR-3) — superseded by `test_posts_generic_payload`.
    - Delete `test_char_timeout_15` (CHAR-4) — superseded by `test_timeout_from_config`.
    - Update `test_char_no_op_when_webhook_unset` (CHAR-1) to call `notify(cfg, {})` (2-arg form).
    - Update `test_char_never_raises` (CHAR-2) to call `notify(cfg, {})` and mock
      `electric_blue.notify.requests.post` to raise `Exception`.
    - Add PR description entry naming each deletion and its replacement.

11. **tests/test_notify.py: add 19 new tests.** Mock seam for all: `monkeypatch.setattr(
    "electric_blue.notify.requests.post", mock_fn)`. Use `webhook_cfg` fixture with
    `dataclasses.replace` pattern from architecture §9.

    Tests to add (grouped by AC family):

    REL family:
    - `test_timeout_from_config` (REL-1): `requests.post` called with `timeout=cfg.notify_timeout_sec`.
    - `test_swallows_connection_error` (REL-2): `ConnectionError` raised → `notify()` returns normally; `post` called once.
    - `test_swallows_timeout` (REL-3): `requests.Timeout` raised → returns normally; `post` called once.
    - `test_swallows_http_500` (REL-4): status 500 → returns normally; `post` called once.
    - `test_retry_on_5xx` (REL-5 + REL-6): `notify_retries=1`; 500 then 200 → `post` called twice.
    - `test_no_retry_on_4xx` (REL-7): `notify_retries=1`; HTTP 400 → `post` called exactly once.
    - `test_warning_level_only` (REL-8): on failure, log records are all at WARNING.

    FMT family:
    - `test_posts_generic_payload` (FMT-1): `notify_format="generic"` → `post` receives raw v1 dict unchanged.
    - `test_format_ntfy_done` (FMT-2 + FMT-3): `_format_ntfy(done_payload)` → `set(result.keys()) == {"title",
      "message", "priority", "tags"}` (exact set — formatter introduces no new fields, FMT-3) and
      `json.dumps(result)` contains no `"/"`-prefixed path string.
    - `test_format_ntfy_failed_no_optional_fields` (FMT-2 edge): `_format_ntfy(failed_payload)` with no `outputs`/`duration_sec`/`language` → no raise.

    HMAC family:
    - `test_hmac_absent_when_no_secret` (HMAC-1): `notify_hmac_secret=""` → no `X-Electric-Blue-Signature` header.
    - `test_hmac_header_present` (HMAC-2 + HMAC-3): `notify_hmac_secret="s"` → header present matching `sha256=[0-9a-f]{64}`; value equals `_sign()` output.
    - `test_hmac_over_formatted_body` (HMAC-4): HMAC computed post-`_format_payload`, not over raw v1 dict.
    - `test_no_hmac_secret_leak` (RED-4 / INV-7): `notify_hmac_secret="topsecret"`; run `notify(cfg, payload)`;
      assert `"topsecret"` NOT in the serialized POST body (`json.dumps`) AND NOT in `caplog.text` across the
      `_sign`/`notify` path. (Closes the security-coverage gap: the secret signs but never appears in payload or logs.)

    Watcher integration (patch `electric_blue.watcher.transcribe` and `electric_blue.watcher.notify`):
    - `test_watcher_started_fires_before_transcribe` (STA-2): `notify` called with `event="started"` payload before `transcribe` is invoked.
    - `test_watcher_done_on_success` (INT-1): successful transcription → `notify` called with `event="done"` payload containing `output_stems` filenames.
    - `test_watcher_failed_on_exception` (INT-2): `transcribe` raises → `notify` called with `event="failed"` payload before `shutil.move` to `failed_dir`.
    - `test_started_at_shared` (INT-4): capture both `notify` calls (started + done); assert
      `started_payload["started_at"] == done_payload["started_at"]` — one `datetime.now(timezone.utc)` is
      stamped in `handle()` and passed into `process()` (the architecture's scoping correction), not stamped twice.

    **G4 — surviving char-test placement (definitive):** the surviving contracts (no-op-when-unset,
    never-raises) live in **`tests/test_char_notify.py`** — updated in step 10 to the 2-arg API as the
    renamed `test_char_no_op_when_webhook_unset` (CHAR-1) and `test_char_never_raises` (CHAR-2). They are
    NOT duplicated in `tests/test_notify.py`. `test_notify.py` holds only the new builder/REL/FMT/HMAC/
    watcher tests. One home each — no overlap.

12. **test_watcher.py: verify.** Run existing tests unchanged. `NOTIFY_WEBHOOK=""` by default in
    test configs so `notify()` returns at the guard with no network call. No edits to
    `test_watcher.py` anticipated (FLAG-4 in architecture: default empty webhook makes notify a
    no-op before any call path is exercised).

**Verification gate:**

```
PATH="$PWD/.venv/bin:$PATH" make gate
```

Pass condition:
- CHAR-1 and CHAR-2 in `test_char_notify.py` green under new 2-arg signature.
- CHAR-3 and CHAR-4 are gone (named supersessions; PR description documents them).
- All 7 builder/redaction tests from S3 still green.
- All 19 new tests (REL, FMT, HMAC, watcher integration) green.
- All existing `test_watcher.py` tests green.
- All existing `test_outputs.py` tests green.
- INV-1: `grep -nE 'shutil\.move' src/electric_blue/watcher.py` shows move-to-done strictly after
  `process()` returns; move-to-failed strictly after `notify()` call in except clause.
- INV-7: `grep -nE 'api_key|hmac_secret|notify_webhook' src/electric_blue/notify.py` shows no
  logging of secret fields except inside `_sign()` where only the computed header value exits.

DDR §8 tests satisfied here: `test_no_op_when_unset`, `test_posts_generic_payload`,
`test_swallows_connection_error`, `test_swallows_timeout`, `test_swallows_http_500`,
`test_retry_on_failure`, `test_format_ntfy`, `test_hmac_header_present`,
`test_hmac_absent_when_no_secret`. (Total with S3: 15 of 15 in-scope §8 tests.)

ACs satisfied: REL-1, REL-2, REL-3, REL-4, REL-5, REL-6, REL-7, REL-8, FMT-1, FMT-2, FMT-3,
HMAC-1, HMAC-2, HMAC-3, HMAC-4, STA-2, INT-1, INT-2, INT-3, INT-4

**Rollback:** revert `src/electric_blue/notify.py` to post-S3 state; revert `src/electric_blue/
watcher.py` to pre-S5 state; revert `tests/test_char_notify.py` to 4-test S1 state; remove the
19 new tests from `tests/test_notify.py`. Last gate-green revert target is the S4 commit.

---

## S6 — Final Gate + Smoke + Frank BUILD Gate

**Goal:** Confirm the full sprint is gate-green and smoke-green, complete the secret scan, and
obtain a Frank SHIP verdict before opening the PR.

**Depends on:** S5 (all code complete and gate-green)

**Files:** none

**Steps:**

1. **Full gate:**

   ```
   PATH="$PWD/.venv/bin:$PATH" make gate
   ```

   Must exit 0. This runs `black --check .`, `ruff check .`, and `pytest -m "not smoke"`.

2. **Smoke gate (CADENCE P6 — attestation required):**

   ```
   PATH="$PWD/.venv/bin:$PATH" make smoke
   ```

   Must exit 0. Run locally or via `workflow_dispatch` on the sprint branch. Capture the green result
   as an artifact to attach to the PR. CI does not run smoke automatically on PRs (deliberate cost
   decision per CADENCE P6).

3. **Secret scan (CADENCE P7):**
   Run deny-list grep over the diff: check for Tailscale `100.x` IPs, DB DSN, API keys, relay
   creds, `notify_webhook` values, `gh auth token` output. Diff must be clean.

4. **Frank BUILD gate (CADENCE P8):**
   Frank reviews the built slices against the spec and invariants reading the code. Gate criteria:
   `make gate` green (P5), `make smoke` attested green (P6), secret scan clean (P7), no invariant
   tripped, all 15 in-scope DDR §8 tests present and passing, all sprint ACs met.

5. **PR (CADENCE P9):**
   Open PR with gate artifact, smoke attestation, and Frank SHIP verdict attached.

**Verification gate:** Frank BUILD gate verdict = SHIP.

---

## Deferred Work

The following items are explicitly out of scope for this sprint per locked decisions:

| Item | Decision | Future path |
|------|----------|-------------|
| `_format_slack` formatter + `test_format_slack` | D2 (Slack deferred) | Future DDR |
| `_format_teams` formatter + `test_format_teams` | D2 (Teams deferred; Microsoft legacy connector deprecated) | Future DDR |
| Per-event URL routing (`NOTIFY_WEBHOOK_DONE`, etc.) | D5 | Future DDR |
| `snippet` field in v1 payload | D1 | Future DDR |
| Exponential or fixed backoff between retries | D3 (count-based only) | Future DDR |
| Fire-and-forget via thread pool | Out of scope | Future DDR |
| DDR-03 async drain hook wiring | Blocked on DDR-03 drain interface | DDR-03 sprint |
| `test_format_slack`, `test_format_teams` (2 of DDR §8's 17 tests) | D2 | Not in this sprint |

---

## AC Coverage Ledger

| Slice | ACs Covered |
|-------|-------------|
| S1 | CHAR-1, CHAR-2, CHAR-3, CHAR-4 |
| S2 | CFG-1, CFG-2, CFG-3, CFG-4, CFG-5, CFG-6, CFG-7 |
| S3 | PAY-1, PAY-2, PAY-3, PAY-4, PAY-5, STA-1, RED-1, RED-2, RED-3, RED-4 |
| S4 | OUT-1, OUT-2, OUT-3 |
| S5 | REL-1, REL-2, REL-3, REL-4, REL-5, REL-6, REL-7, REL-8, FMT-1, FMT-2, FMT-3, HMAC-1, HMAC-2, HMAC-3, HMAC-4, STA-2, INT-1, INT-2, INT-3, INT-4 |
| S6 | Process gate (all ACs verified by Frank) |

All 44 sprint ACs covered. 15 of 17 DDR §8 tests in scope covered (2 deferred by D2); plus 2 added
review-gap coverage tests (`test_no_hmac_secret_leak`, `test_started_at_shared`) → 19 new tests in S5.
