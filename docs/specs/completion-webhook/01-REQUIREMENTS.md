# Requirements: completion-webhook

- **Status:** DRAFT
- **Author:** reed
- **Date:** 2026-06-14
- **DDR:** DDR-04-completion-webhook.md
- **Sprint:** completion-webhook (GitHub issue #10)

---

## Summary

Formalize the 25-line `notify.py` stub into a tested, versioned, provider-aware webhook. The
feature produces a structured v1 JSON payload (typed builders, `schema_version:1`, canonical
UTC timestamps, redaction guarantees), adds four new `Config` fields, introduces bounded
timeout and retry, ships two provider formatters (generic + ntfy), and adds optional HMAC
signing behind an empty-by-default secret. `write_outputs()` is updated to return
`dict[str, Path]` so builders can include output filenames in the payload. The webhook is
strictly optional and strictly non-blocking: every failure path logs at WARNING and returns
normally.

---

## Locked Constraints (D1 – D6)

These decisions are resolved and closed. Requirements below treat them as immutable.

| ID | Constraint |
|----|-----------|
| D1 | Payload `outputs` carries filenames only (never absolute or relative paths). No `snippet` field in v1. |
| D2 | Provider formatters day one: `generic` + `ntfy` only. Teams and Slack are deferred. |
| D3 | `notify_timeout_sec` default 5.0; `notify_retries` default 0 (single-attempt preserved). Retry on network errors and HTTP 5xx only — NOT on 4xx. Count-based; no backoff in v1. |
| D4 | HMAC signing included but disabled by default (`NOTIFY_HMAC_SECRET=""`). Documented, not required. |
| D5 | Single `NOTIFY_WEBHOOK` URL receives all events. Per-event routing is a future DDR. |
| D6 | `started` event is included. Fired when a file enters processing. |

---

## User Stories

### US-01 — Characterization tests: pin current stub behavior

As a pipeline developer,
I want characterization tests that capture the current `notify()` stub's observable behaviors
before any code is touched,
so that regressions introduced during the implementation sprint are detected immediately.

### US-02 — Structured v1 payload: done and failed builders

As a webhook consumer,
I want structured, versioned JSON payloads with typed fields for done and failed events,
so that I can reliably parse transcription results without reverse-engineering a freeform string.

### US-03 — Started event: build_started_payload builder

As a webhook consumer integrating with long-running diarization jobs (DDR-05),
I want a `started` event fired when a file enters processing,
so that I can set an expectation and avoid polling the filesystem.

### US-04 — Payload redaction: no paths or secrets

As a system operator,
I want a guarantee that the webhook payload never contains absolute filesystem paths, API keys,
or HMAC secrets,
so that credentials and server topology are not leaked to external webhook endpoints.

### US-05 — Config additions: four new environment variables

As a pipeline operator,
I want to configure webhook timeout, retry count, output format, and HMAC secret through
environment variables with safe defaults,
so that reliability and security posture can be tuned per deployment without code changes.

### US-06 — Bounded reliability: configurable timeout and retry

As a pipeline operator,
I want the webhook call to use a configurable timeout and a bounded retry count,
so that transient endpoint failures are handled without blocking the transcription pipeline
for an unbounded duration.

### US-07 — Provider formatters: generic and ntfy

As an ntfy user,
I want webhook payloads automatically formatted for the ntfy JSON publish API,
so that I receive mobile push notifications without building a custom adapter.

### US-08 — Optional HMAC signing

As a webhook consumer that wants to verify payload authenticity,
I want an optional `X-Electric-Blue-Signature` header carrying a SHA-256 HMAC,
so that I can confirm the payload originates from the electric-blue pipeline.

### US-09 — write_outputs() returns dict[str, Path]

As a caller of `write_outputs()`,
I want the function to return a `dict[str, Path]` mapping each enabled format to its output
file path,
so that done-payload builders can include output filenames without re-deriving them.

### US-10 — Watcher call site integration

As a pipeline operator,
I want `watcher.process()` and `watcher.handle()` to call the new typed payload builders
and the updated `notify(cfg, payload)` signature,
so that every transcription event fires a structured webhook notification.

---

## Acceptance Criteria

### US-01 — Characterization tests

These tests are written against the existing stub BEFORE any implementation change. The entire
test suite must be green at this step. Two behaviors survive into the new implementation
(marked **survives**); two are superseded by the new design (marked **superseded**).

- [ ] **[CHAR-1]** Given `cfg.notify_webhook=""`, when `notify(cfg, text, meta)` is called on
  the current stub, then `requests.post` is never called. (**survives** as no-op invariant)
- [ ] **[CHAR-2]** Given `requests.post` raises any `Exception`, when `notify()` is called on
  the current stub, then the function returns normally without re-raising. (**survives** as
  never-raises invariant)
- [ ] **[CHAR-3]** Given `cfg.notify_webhook` is set and `meta={"file": "x.mp4"}`, when
  `notify(cfg, "hello", meta)` is called on the current stub, then `requests.post` is called
  once with JSON body `{"text": "hello", "file": "x.mp4"}`. (**superseded** by v1 payload)
- [ ] **[CHAR-4]** Given `cfg.notify_webhook` is set, when `notify()` is called on the current
  stub, then `requests.post` receives `timeout=15`. (**superseded** by `cfg.notify_timeout_sec`)

### US-02 — Structured v1 payload builders

Corresponds to DDR §8 tests: `test_done_payload_fields`, `test_failed_payload_fields`,
`test_wall_sec_is_derived`, `test_started_event_omits_finished`.

- [ ] **[PAY-1]** Given valid `cfg`, `src=Path("/inbox/meeting.mp4")`, `info`, `output_stems`,
  `started_at`, and `finished_at`, when `build_done_payload()` is called, then the returned
  dict contains exactly: `schema_version=1`, `event="done"`, `file="meeting.mp4"`,
  `backend` (from `info.backend`), `started_at` (ISO-8601 UTC string), `finished_at`
  (ISO-8601 UTC string), `wall_sec` (float, 1 decimal), `status="done"`,
  `duration_sec` (float, 1 decimal, from `info.duration`), `language` (from `info.language`),
  `outputs` (dict of `{format: filename_only}`).
- [ ] **[PAY-2]** Given valid inputs and `error=ValueError("codec error")`, when
  `build_failed_payload()` is called, then the returned dict contains `schema_version=1`,
  `event="failed"`, `status="failed"`, `error="codec error"` (string, no traceback),
  `file`, `backend`, `started_at`, `finished_at`, `wall_sec`. No `duration_sec`, `language`,
  or `outputs` keys are present.
- [ ] **[PAY-3]** Given `started_at` and `finished_at` exactly 90 seconds apart, when
  `build_done_payload()` is called, then `payload["wall_sec"] == 90.0` — computed as
  `round((finished_at - started_at).total_seconds(), 1)`, not from a separate `time.time()`
  reading.
- [ ] **[PAY-4]** Given `started_at` and `finished_at` exactly 86400 seconds (24 hours) apart
  (simulating an async batch boundary), when `build_done_payload()` is called, then
  `payload["wall_sec"] == 86400.0` with no schema change.
- [ ] **[PAY-5]** Given timestamps encoded as ISO-8601 UTC strings in `started_at` /
  `finished_at`, when either payload builder is called, then both string values parse
  successfully with `datetime.fromisoformat()` and carry UTC timezone information.

### US-03 — Started event builder

Corresponds to DDR §8 test: `test_started_event_omits_finished`.

- [ ] **[STA-1]** Given `cfg`, `src=Path("/inbox/file.mp3")`, and `started_at`, when
  `build_started_payload(cfg, src, started_at)` is called, then the returned dict contains
  `schema_version=1`, `event="started"`, `file="file.mp3"`, `backend=cfg.backend`,
  `started_at` (ISO-8601 UTC string), and no `finished_at` key and no `wall_sec` key.
- [ ] **[STA-2]** Given a file arrives in the inbox, when `watcher.process()` begins execution,
  then `notify(cfg, build_started_payload(cfg, src, started_at))` is called before
  `transcribe()` is invoked.

### US-04 — Payload redaction

Corresponds to DDR §8 tests: `test_no_absolute_paths`, `test_no_api_key_in_payload`.

- [ ] **[RED-1]** Given `src=Path("/home/user/inbox/meeting.mp4")`, when any payload builder
  is called, then `payload["file"] == "meeting.mp4"` (filename only, never the full path).
- [ ] **[RED-2]** Given `src=Path("/home/user/inbox/meeting.mp4")`, when any payload builder is
  called, then no field in the serialized payload contains the substring `"/home"` or any
  other absolute-path prefix.
- [ ] **[RED-3]** Given `cfg.api_key="sk-secret"`, when any payload builder is called, then the
  string `"sk-secret"` does not appear anywhere in `json.dumps(payload)`.
- [ ] **[RED-4]** Given `cfg.notify_hmac_secret="topsecret"`, when any payload builder is called
  with that `cfg` and when `_sign()` or `notify()` is invoked, then (a) the string
  `"topsecret"` does not appear in `json.dumps(payload)` for any builder's return value, and
  (b) `"topsecret"` does not appear in any log record at any level — asserted via
  `caplog.text` captured across the `_sign` / `notify` call path. Both halves must pass to
  satisfy INV-7. (`test_no_hmac_secret_leak`)

### US-05 — Config additions

- [ ] **[CFG-1]** Given no `NOTIFY_TIMEOUT_SEC`, `NOTIFY_RETRIES`, `NOTIFY_FORMAT`, or
  `NOTIFY_HMAC_SECRET` environment variables are set, when `Config.from_env()` is called,
  then `cfg.notify_timeout_sec == 5.0` (float), `cfg.notify_retries == 0` (int),
  `cfg.notify_format == "generic"` (str), `cfg.notify_hmac_secret == ""` (str).
- [ ] **[CFG-2]** Given `NOTIFY_TIMEOUT_SEC="2.5"`, when `Config.from_env()` is called, then
  `cfg.notify_timeout_sec == 2.5` and `isinstance(cfg.notify_timeout_sec, float) is True`.
- [ ] **[CFG-3]** Given `NOTIFY_RETRIES="3"`, when `Config.from_env()` is called, then
  `cfg.notify_retries == 3` and `isinstance(cfg.notify_retries, int) is True`.
- [ ] **[CFG-4]** Given `NOTIFY_FORMAT="NTFY"` (uppercase), when `Config.from_env()` is called,
  then `cfg.notify_format == "ntfy"` (lowercased).
- [ ] **[CFG-5]** Given `NOTIFY_HMAC_SECRET="abc123"`, when `Config.from_env()` is called, then
  `cfg.notify_hmac_secret == "abc123"`.
- [ ] **[CFG-6]** No existing `Config` field is removed or has its default changed. All existing
  `test_config.py` tests remain green after the additions.
- [ ] **[CFG-7]** `Config` remains a frozen dataclass; attempting to assign to any new field
  after construction raises `AttributeError` or `TypeError`.

### US-06 — Bounded reliability

Corresponds to DDR §8 tests: `test_swallows_connection_error`, `test_swallows_timeout`,
`test_swallows_http_500`, `test_retry_on_failure`.

- [ ] **[REL-1]** Given `cfg.notify_timeout_sec=5.0`, when `notify()` posts to the webhook,
  then `requests.post` is called with `timeout=5.0` (not the old hardcoded `15`).
- [ ] **[REL-2]** Given `cfg.notify_retries=0` and `requests.post` raises `ConnectionError`,
  when `notify()` is called, then `requests.post` is called exactly once and `notify()`
  returns normally.
- [ ] **[REL-3]** Given `cfg.notify_retries=0` and `requests.post` raises `Timeout`, when
  `notify()` is called, then `requests.post` is called exactly once and `notify()` returns
  normally.
- [ ] **[REL-4]** Given `cfg.notify_retries=0` and `requests.post` returns HTTP 500, when
  `notify()` is called, then `requests.post` is called exactly once and `notify()` returns
  normally.
- [ ] **[REL-5]** Given `cfg.notify_retries=1` and `requests.post` raises `ConnectionError` on
  the first call then succeeds on the second, when `notify()` is called, then
  `requests.post` is called exactly 2 times.
- [ ] **[REL-6]** Given `cfg.notify_retries=1` and `requests.post` returns HTTP 500 on both
  attempts, when `notify()` is called, then `requests.post` is called exactly 2 times and
  `notify()` returns normally.
- [ ] **[REL-7]** Given `cfg.notify_retries=1` and `requests.post` returns HTTP 400 (client
  error), when `notify()` is called, then `requests.post` is called exactly once — 4xx
  responses are NOT retried.
- [ ] **[REL-8]** Given any failure at any retry depth, when `notify()` logs, then the log
  record uses `WARNING` level (never `ERROR` or higher).

### US-07 — Provider formatters

Corresponds to DDR §8 tests: `test_posts_generic_payload`, `test_format_ntfy`.

- [ ] **[FMT-1]** Given `cfg.notify_format="generic"`, when `notify()` is called with a v1
  payload dict, then `requests.post` is called exactly once with that dict passed as the
  JSON body, unmodified.
- [ ] **[FMT-2]** Given a `done_payload` dict (already redacted), when `_format_ntfy(done_payload)`
  is called, then the result is a dict containing all four keys: `"title"`, `"message"`,
  `"priority"`, `"tags"`, and no key in the result contains an absolute path or secret
  value not already present in the input.
- [ ] **[FMT-3]** Given `_format_ntfy(done_payload)` where `done_payload` is an already-redacted
  v1 dict (all string values free of `"/"`-prefixed substrings and free of any known secret
  value), when `_format_ntfy` returns, then `set(result.keys()) == {"title", "message",
  "priority", "tags"}` and `json.dumps(result)` contains no string value that starts with
  `"/"` — confirming the ntfy formatter introduces no absolute-path or secret fields beyond
  those already present in the redacted input.

### US-08 — Optional HMAC signing

Corresponds to DDR §8 tests: `test_hmac_header_present`, `test_hmac_absent_when_no_secret`.

- [ ] **[HMAC-1]** Given `cfg.notify_hmac_secret=""`, when `notify()` posts the payload, then
  `requests.post` is called with no `X-Electric-Blue-Signature` header.
- [ ] **[HMAC-2]** Given `cfg.notify_hmac_secret="s"`, when `notify()` posts the payload, then
  `requests.post` is called with an `X-Electric-Blue-Signature` header whose value matches
  the pattern `sha256=[0-9a-f]{64}`.
- [ ] **[HMAC-3]** Given `cfg.notify_hmac_secret="s"` and a known payload, when `_sign()` is
  called, then the returned value equals
  `"sha256=" + hmac.new(b"s", canonical_json_bytes, hashlib.sha256).hexdigest()` where
  `canonical_json_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()`.
- [ ] **[HMAC-4]** The HMAC is computed over the canonical JSON bytes of the POST body after
  formatting (post `_format_payload`), not over the raw v1 dict before formatting, ensuring
  the signature is stable across Python dict ordering.

### US-09 — write_outputs() returns dict[str, Path]

- [ ] **[OUT-1]** Given `cfg.output_formats=frozenset({"txt","srt","vtt","json"})`, when
  `write_outputs()` is called, then it returns a `dict` with exactly four entries:
  `{"txt": Path(.../"<stem>.txt"), "srt": ..., "vtt": ..., "json": ...}`.
- [ ] **[OUT-2]** Given `cfg.output_formats=frozenset({"txt"})`, when `write_outputs()` is
  called, then it returns `{"txt": Path(.../"<stem>.txt")}` (one entry, not four).
- [ ] **[OUT-3]** All existing `test_outputs.py` tests remain green after the return-value
  change (file content behavior is unchanged; only the return value is added).

### US-10 — Watcher call site integration

- [ ] **[INT-1]** Given a successful transcription, when `watcher.process()` completes, then
  `notify(cfg, build_done_payload(cfg, src, info, output_stems, started_at, finished_at))`
  is called where `output_stems` is the return value of `write_outputs()` and both
  `started_at` / `finished_at` are UTC `datetime` objects.
- [ ] **[INT-2]** Given a transcription exception, when `watcher.handle()` catches it, then
  `notify(cfg, build_failed_payload(cfg, path, e, started_at, finished_at))` is called
  before the file is moved to `failed_dir`.
- [ ] **[INT-3]** The old `notify(cfg, text, meta)` call signature is removed from both
  `watcher.process()` and `watcher.handle()`. No call site in this repo uses the retired
  three-argument form after the sprint.
- [ ] **[INT-4]** Given `watcher.handle()` processes a file and two `notify()` calls are
  captured (one for `"started"`, one for `"done"` or `"failed"`), when both captured payloads
  are inspected, then `started_payload["started_at"] == done_payload["started_at"]` — the
  identical ISO-8601 timestamp string — confirming that a single `datetime.now(timezone.utc)`
  call is recorded once and shared across all payload builders for that file's processing run.

---

## Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| `notify_webhook=""` | `notify()` returns immediately; `requests.post` is never imported or called |
| `notify_retries=0`, endpoint returns HTTP 400 | Single attempt; no retry; `notify()` returns normally |
| `notify_retries=0`, endpoint returns HTTP 500 | Single attempt; no retry; `notify()` returns normally |
| `notify_retries=1`, endpoint returns HTTP 400 | Exactly one attempt; 4xx is not a retryable condition |
| `notify_retries=1`, endpoint returns HTTP 500 | Two attempts total; `notify()` returns normally |
| `started_at == finished_at` (zero-duration file) | `wall_sec == 0.0`; no error |
| `src = Path("/a/b/c/d/e/meeting.mp4")` | `payload["file"] == "meeting.mp4"`; no substring of the parent path appears in any field |
| `cfg.api_key=""` | No leakage concern; behavior unchanged (empty string in redaction check) |
| `notify_hmac_secret=""` (default) | No `X-Electric-Blue-Signature` header; behavior identical to pre-HMAC stub |
| `output_formats=frozenset()` | `write_outputs()` writes no files and returns `{}` |
| `_format_ntfy` called with a `failed` payload (no `outputs`, `duration_sec`, `language`) | Formatter must handle missing optional fields gracefully; does not raise |
| `NOTIFY_FORMAT="GENERIC"` (uppercase in env) | Lowercased to `"generic"` by `Config.from_env()`; routes to identity formatter |
| `requests.post` raises an unexpected exception type (e.g. `OSError`) | `notify()` catches it at the outermost `except Exception` and returns normally |

---

## Out of Scope

- NOT: Slack formatter (`_format_slack`). Deferred by D2.
- NOT: Teams / MessageCard formatter (`_format_teams`). Deferred by D2 (also: Microsoft
  legacy connector is deprecated).
- NOT: Per-event URL routing (`NOTIFY_WEBHOOK_DONE`, `NOTIFY_WEBHOOK_FAILED`, etc.).
  Deferred by D5.
- NOT: `snippet` field (first ~200 chars of transcript text) in the v1 payload. Deferred
  by D1.
- NOT: Exponential or fixed backoff between retries. Count-based only in v1 per D3.
- NOT: DDR-03 async drain hook wiring. DDR-03's drain function calls `build_done_payload()` /
  `build_failed_payload()` directly; this sprint delivers the builders but does not wire
  the DDR-03 call site (blocked on DDR-03's drain interface).
- NOT: Fire-and-forget webhook dispatch via a thread pool. The watcher thread blocks for at
  most `notify_timeout_sec × (1 + notify_retries)` seconds. Threading is a future option.
- NOT: Filter to fire only on specific event types (e.g. failures-only). Single URL, all
  events, per D5.
- NOT: Any user-facing UI, CLI flags, or interactive prompts. Library and systemd service
  only.

---

## Constraints

- **Must:** Webhook is strictly optional. When `notify_webhook=""`, the entire feature is a
  no-op. No exception from the notify path may propagate into the transcription pipeline.
- **Must:** Every failure in the notify path logs at `WARNING` level — never `ERROR` or higher.
- **Must:** All payload builders are pure functions (no side effects, no network calls). Only
  `notify()` triggers I/O.
- **Must:** `wall_sec` is always `round((finished_at - started_at).total_seconds(), 1)`.
  It is never computed from a separate `time.time()` reading.
- **Must:** Both `started_at` and `finished_at` are UTC `datetime` objects passed by the
  caller; they are serialized as ISO-8601 strings with `timespec="seconds"` using
  `.isoformat()`.
- **Must:** Characterization tests (US-01) are committed and green before any implementation
  change is made to `notify.py`, `watcher.py`, `outputs.py`, or `config.py`.
- **Must:** The `make` test gate and `make smoke` must pass green. Frank build gate must
  report SHIP before the sprint is considered complete.
- **Must not:** Any payload builder reference `cfg.api_key` or `cfg.notify_hmac_secret` for
  any purpose other than HMAC signing within `_sign()`.
- **Must not:** Any formatter introduce fields that were not in the incoming (already-redacted)
  payload dict.
- **Assumes:** `requests` is available as a runtime dependency (already used by the API
  backend). No new dependency is introduced.
- **Assumes:** DDR-02 foundation (backend seam, `schema_version` in `outputs.py`) is already
  merged to main at the start of this sprint (confirmed: commit `fab9c71`).
- **Assumes:** The `Config` frozen dataclass pattern from DDR-01 remains unchanged. New
  fields are appended; no field is removed or type-changed.

---

## DDR §8 Test Coverage Map

The 17-test table in DDR §8 maps to this document as follows. Two tests (`test_format_slack`,
`test_format_teams`) are deferred by D2 and are OUT OF SCOPE for this sprint.

| DDR §8 Test | Sprint AC |
|-------------|-----------|
| `test_done_payload_fields` | PAY-1 |
| `test_failed_payload_fields` | PAY-2 |
| `test_wall_sec_is_derived` | PAY-3, PAY-4 |
| `test_started_event_omits_finished` | STA-1 |
| `test_no_absolute_paths` | RED-1, RED-2 |
| `test_no_api_key_in_payload` | RED-3 |
| `test_no_op_when_unset` | CHAR-1 |
| `test_posts_generic_payload` | FMT-1 |
| `test_swallows_connection_error` | REL-2 |
| `test_swallows_timeout` | REL-3 |
| `test_swallows_http_500` | REL-4 |
| `test_retry_on_failure` | REL-5 |
| `test_format_slack` | OUT OF SCOPE (D2 deferred) |
| `test_format_teams` | OUT OF SCOPE (D2 deferred) |
| `test_format_ntfy` | FMT-2 |
| `test_hmac_header_present` | HMAC-2, HMAC-3 |
| `test_hmac_absent_when_no_secret` | HMAC-1 |
