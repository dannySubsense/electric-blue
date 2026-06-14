# DDR-04 — Completion-Ping Webhook

- **Status:** PROPOSED
- **Author:** reed
- **Date:** 2026-06-14
- **Sprint (on approval):** `completion-webhook`
- **Depends on:** DDR-01 (scaffolding — DONE), DDR-02 (backend seam), DDR-03 (async batch — exposes the completion hook this feature consumes)
- **Blocks:** —
- **Supersedes:** —

---

## Context

`notify.py` today is a 25-line stub that POSTs an unstructured `{"text": ..., **meta}` dict to
`NOTIFY_WEBHOOK` with a fixed 15-second timeout and no retry. It is called in two places:

- `watcher.process()` on success — carries `file`, `status`, `duration_min`, `backend` in `meta`
- `watcher.handle()` on failure — carries `file`, `status` only; the error string is smeared into the freeform `text` field

The stub honours the "never break the pipeline" contract (all exceptions are swallowed), but falls short in four areas:

1. **Unversioned, unstructured payload.** No schema version; consumers cannot adapt when fields change. Output filenames are absent, so a consumer cannot locate the transcript without knowing the on-disk layout. The error string is mixed into `text` rather than typed field.
2. **Reliability gaps.** A 15-second timeout on a best-effort call is too long for a synchronous watcher thread; a single transient HTTP 5xx is silently discarded with no retry path.
3. **No provider abstraction.** The homelab uses Microsoft Teams (via the `docs/homelab/README.md` OpenClaw reference) and ntfy for mobile push. Generic JSON works for n8n / home-automation consumers but not for Slack or Teams, which require specific envelope shapes.
4. **Security.** The payload carries no redaction guarantee for absolute paths; no signing mechanism exists for consumers that want to verify origin.

Additionally, two upcoming sprints change the notification surface:
- **DDR-03 (Groq Batch)** is asynchronous: the watcher submits a job and a separate drain/poll path retrieves the transcript later. That path needs its own call site; the current `process()`/`handle()` call sites are synchronous only.
- **DDR-05 (WhisperX diarization)** can run for tens of minutes on long recordings; a `started` event lets consumers set an expectation without polling the filesystem.

This DDR formalises `notify.py` into a tested, versioned, provider-aware feature. DDR-05 is the primary beneficiary for long-job pings.

## Principle

The webhook must remain strictly optional and strictly non-blocking. A consumer whose endpoint is slow, misconfigured, or unreachable has zero impact on transcription throughput or output correctness. Every new mechanism added here fails silently and logs at `WARNING`.

Consumers with a working endpoint deserve structured, stable, signed, and redacted data — not a freeform string they must parse themselves.

---

## Decision

### 1. Structured, versioned payload

Replace the freeform `{"text": ..., **meta}` dict with a typed v1 envelope. A common `_base_payload` function builds the shared fields; event-specific builders extend it.

```python
# notify.py — payload builders (proposed shapes; remaining field set is flagged D1)

def _base_payload(event: str, cfg: Config, src: Path,
                  started_at: datetime, finished_at: datetime | None = None) -> dict:
    p = {
        "schema_version": 1,               # additive policy fixed in DDR-02 D4
        "event": event,                    # "done" | "failed" | "started"   FLAG D6
        "file": src.name,                  # filename only — never str(src) (absolute path)
        "backend": cfg.backend,            # backend identifier; no secrets
        "started_at": started_at.isoformat(timespec="seconds"),   # canonical instant (UTC)
    }
    if finished_at is not None:            # absent only for the "started" event (D6)
        p["finished_at"] = finished_at.isoformat(timespec="seconds")
        p["wall_sec"] = round((finished_at - started_at).total_seconds(), 1)  # DERIVED, see below
    return p

def build_done_payload(
    cfg: Config,
    src: Path,
    info: TranscriptInfo,
    output_stems: dict[str, Path],
    started_at: datetime,
    finished_at: datetime,
) -> dict:
    p = _base_payload("done", cfg, src, started_at, finished_at)
    p.update({
        "status": "done",
        "duration_sec": round(info.duration, 1),   # audio length, not wall-clock
        "language": info.language,
        "backend": info.backend,           # e.g. "api:whisper-large-v3-turbo"
        "outputs": {fmt: path.name for fmt, path in output_stems.items()},
        # FLAG D1: optional "snippet" — first ~200 chars of transcript text?
    })
    return p

def build_failed_payload(
    cfg: Config,
    src: Path,
    error: Exception,
    started_at: datetime,
    finished_at: datetime,
) -> dict:
    p = _base_payload("failed", cfg, src, started_at, finished_at)
    p.update({
        "status": "failed",
        "error": str(error),               # exception message only; no traceback
    })
    return p

# build_started_payload(cfg, src, started_at) -> dict  — _base_payload with finished_at=None;
#                                                         added if D6 resolves to include "started"
```

**Timing fields — `started_at` / `finished_at` are canonical; `wall_sec` is derived (DDR-02 D4 + Frank's call, 2026-06-14).**
The two timestamps are the source of truth; **`wall_sec` is defined as their difference, never an
independent `time.time() - t_start` reading.** This is async-safe by construction: a sync backend's
`finished_at - started_at` is processing time; an async/batch backend (DDR-03) reports `started_at`
at submission and `finished_at` at completion, and `wall_sec` then honestly spans the queue/batch
latency — the *same* fields mean the *same* thing across backends. No field is reserved "for later"
and no backend forces a v2 bump: DDR-03 fills in the two timestamps it already has. Timestamps are
UTC ISO-8601 (`timespec="seconds"`). `duration_sec` (audio length) is unrelated to `wall_sec`.

Redaction commitments baked into `_base_payload`:
- `src.name` (filename only) — never `str(src)` (absolute path).
- `cfg.api_key` is never referenced in any payload builder.
- `cfg.notify_hmac_secret` is never logged or included in any payload.

### 2. Config additions

Four new fields added to the frozen `Config` dataclass, all optional with safe defaults:

```python
# config.py additions

notify_webhook: str          # NOTIFY_WEBHOOK          — "" = feature disabled (existing)
notify_timeout_sec: float    # NOTIFY_TIMEOUT_SEC      — default 5.0     FLAG D3
notify_retries: int          # NOTIFY_RETRIES          — default 0        FLAG D3
notify_format: str           # NOTIFY_FORMAT           — default "generic" FLAG D2
notify_hmac_secret: str      # NOTIFY_HMAC_SECRET      — default ""       FLAG D4
```

`Config.from_env()` additions:
```python
notify_timeout_sec=float(os.environ.get("NOTIFY_TIMEOUT_SEC", "5.0")),
notify_retries=int(os.environ.get("NOTIFY_RETRIES", "0")),
notify_format=os.environ.get("NOTIFY_FORMAT", "generic").lower(),
notify_hmac_secret=os.environ.get("NOTIFY_HMAC_SECRET", ""),
```

No existing field changes. The feature is disabled when `notify_webhook` is the empty string.

### 3. Reliability: bounded timeout and bounded retry

```python
def _post_with_retry(url: str, body: dict, cfg: Config) -> None:
    """POST body as JSON. Retries cfg.notify_retries times on failure. Never raises."""
    for attempt in range(1 + cfg.notify_retries):
        try:
            r = requests.post(url, json=body, timeout=cfg.notify_timeout_sec)
            r.raise_for_status()
            return
        except Exception as e:
            log.warning("notify attempt %d/%d failed: %s",
                        attempt + 1, 1 + cfg.notify_retries, e)
    # All attempts exhausted — pipeline is unaffected
```

The existing `timeout=15` is replaced by `cfg.notify_timeout_sec` (default 5.0). Retry semantics — number of attempts, backoff, whether 4xx errors are retried — are flagged (D3). Default of `notify_retries=0` keeps the existing single-attempt behaviour.

### 4. Provider formatters

The core `notify()` function always builds the structured v1 payload first. A formatter layer then transforms it into the provider-specific envelope before posting:

```python
def _format_payload(raw: dict, fmt: str) -> dict:
    """Transform structured payload into provider envelope. Default: identity."""
    if fmt == "slack":
        return _format_slack(raw)
    if fmt == "teams":
        return _format_teams(raw)
    if fmt == "ntfy":
        return _format_ntfy(raw)
    return raw   # "generic" — post the structured v1 dict as-is
```

Proposed formatter shapes (subject to D2 on which to include day one):

- **`_format_slack`** — returns `{"text": "<bold filename> — <event> ..."}` matching Slack Incoming Webhook.
- **`_format_teams`** — returns a legacy MessageCard envelope (`@type`, `themeColor`, `text`). Note: Microsoft is deprecating legacy connectors in favour of Power Automate; if Teams is included, this limitation must be documented.
- **`_format_ntfy`** — returns `{"title": ..., "message": ..., "priority": ..., "tags": [...]}` for the ntfy JSON publish API (self-hosted or ntfy.sh).

All formatters operate only on the already-redacted `raw` dict; they cannot introduce new fields that leak paths or secrets.

### 5. Optional HMAC signing

When `cfg.notify_hmac_secret` is non-empty, a `X-Electric-Blue-Signature` header is added:

```python
import hashlib, hmac as _hmac, json as _json

def _sign(body_bytes: bytes, secret: str) -> str:
    """Return 'sha256=<hex>'."""
    return "sha256=" + _hmac.new(
        secret.encode(), body_bytes, hashlib.sha256
    ).hexdigest()
```

The serialised body (canonical JSON: `sort_keys=True`, no extra whitespace) is signed, not the pre-formatted dict, so the signature is stable across Python dict ordering. Whether to include this mechanism at all is flagged (D4). When the secret is empty the header is omitted and behaviour is identical to today.

### 6. Public API of notify.py after this DDR

```python
# Public surface — replaces current notify(cfg, text, meta) signature

def notify(cfg: Config, payload: dict) -> None:
    """Post payload to cfg.notify_webhook. No-ops if webhook unset.
    Applies formatter (D2), optional HMAC (D4), bounded retry (D3). Never raises."""

def build_done_payload(
    cfg: Config,
    src: Path,
    info: TranscriptInfo,
    output_stems: dict[str, Path],
    started_at: datetime,
    finished_at: datetime,
) -> dict: ...

def build_failed_payload(
    cfg: Config,
    src: Path,
    error: Exception,
    started_at: datetime,
    finished_at: datetime,
) -> dict: ...

# build_started_payload(cfg, src, started_at) -> dict  — added if D6 resolves yes
```

The current `notify(cfg, text, meta)` signature is retired. All three call sites are in this repo (`watcher.py` × 2, DDR-03 drain × 1); there is no external API break.

### 7. Integration points

**Sync path (`watcher.py`) — minimal change:**

`watcher.process()` currently calls `notify(cfg, text, meta)` after `write_outputs()` completes.
After this DDR:

```python
# watcher.process() — updated call sites
started_at = datetime.now(timezone.utc)
# FLAG D6: notify(cfg, build_started_payload(cfg, src, started_at)) here if "started" is included
segments, info = transcribe(cfg, src)
output_stems = write_outputs(cfg, cfg.output_dir, src.stem, segments, info)
...
notify(cfg, build_done_payload(cfg, src, info, output_stems,
                               started_at, datetime.now(timezone.utc)))

# watcher.handle() — failure call site
except Exception as e:
    log.error("Failed on %s: %s", path.name, e)
    notify(cfg, build_failed_payload(cfg, path, e,
                                     started_at, datetime.now(timezone.utc)))
    shutil.move(...)
```

`write_outputs()` currently returns `None`. It must be updated to return `dict[str, Path]` (format → output path). This is a behavior-preserving change; the only caller that reads the return value today is `watcher.process()`. **Note (build order `04 → 03`):** DDR-03's drain calls `write_outputs()` too — it is authored *after* this change lands, so it is written against the `dict[str, Path]` return from the start; there is no second caller to retrofit.

**DDR-03 async path:**

DDR-03's drain/retrieval function will expose a completion hook — called after `fetch()` succeeds or a job expires. DDR-04's `build_done_payload()` / `build_failed_payload()` slot into that hook. The exact hook signature is DDR-03's decision; this DDR requires that the hook supplies `(cfg, src_path, info_or_exception, started_at, finished_at)` — and for a batch job those two instants come straight from the job record (`JobRecord.submitted_at` / `completed_at`), **not** from a `time.time()` reading in the draining process. That is the whole point of making the timestamps canonical: the ~24h batch boundary is represented honestly with zero schema change. No polling, no new threads — the drain path calls `notify()` synchronously, same as the sync path.

**DDR-05 (diarization):**

DDR-05 jobs run for minutes to tens of minutes. The `started` event (D6) is particularly valuable here. No structural change is required in DDR-05 beyond calling the same `notify()` call sites; the watcher path is already wired.

### 8. Tests

New test file: `tests/test_notify.py`. All tests monkeypatch `requests.post`; no network calls.

| Test | Asserts |
|------|---------|
| `test_done_payload_fields` | `build_done_payload()` returns correct `schema_version`, `event`, `file`, `status`, `duration_sec`, `language`, `backend`, `outputs`, `started_at`, `finished_at`; `file` is filename only |
| `test_failed_payload_fields` | `build_failed_payload()` returns `event="failed"`, `status="failed"`, typed `error` string, `started_at`, `finished_at` |
| `test_wall_sec_is_derived` | given `started_at` and `finished_at` 90s apart, `wall_sec == 90.0` (exactly `finished_at - started_at`); timestamps are ISO-8601 UTC; an async-style 24h gap yields `wall_sec == 86400.0` with no schema change |
| `test_started_event_omits_finished` | `_base_payload` with `finished_at=None` emits `started_at`, no `finished_at`, no `wall_sec` |
| `test_no_absolute_paths` | `src` is `/home/user/inbox/meeting.mp4`; payload `file == "meeting.mp4"`; no field contains `/home` |
| `test_no_api_key_in_payload` | `cfg.api_key = "sk-secret"`; `"sk-secret"` does not appear anywhere in the serialised payload |
| `test_no_op_when_unset` | `notify_webhook=""` → `requests.post` is never called |
| `test_posts_generic_payload` | `notify_format="generic"` → `requests.post` called once with the raw v1 dict |
| `test_swallows_connection_error` | `requests.post` raises `ConnectionError`; `notify()` returns normally |
| `test_swallows_timeout` | `requests.post` raises `Timeout`; `notify()` returns normally |
| `test_swallows_http_500` | `requests.post` returns status 500; `notify()` returns normally |
| `test_retry_on_failure` | `notify_retries=1`; `requests.post` raises once then succeeds; assert called twice |
| `test_format_slack` | `_format_slack(done_payload)` returns dict with `"text"` key; no absolute paths |
| `test_format_teams` | `_format_teams(done_payload)` returns `@type == "MessageCard"` |
| `test_format_ntfy` | `_format_ntfy(done_payload)` returns `title`, `message`, `priority`, `tags` |
| `test_hmac_header_present` | `notify_hmac_secret="s"` → `requests.post` called with `X-Electric-Blue-Signature` header matching `sha256=...` |
| `test_hmac_absent_when_no_secret` | `notify_hmac_secret=""` → no `X-Electric-Blue-Signature` header |

---

## Sequencing (within the sprint)

1. Write characterization tests against the *current* `notify()` stub — pin existing behaviour (all green before touching code).
2. Add new `Config` fields with defaults; update `test_config.py`.
3. Implement `build_done_payload` / `build_failed_payload`; write payload and redaction tests.
4. Implement `_post_with_retry`, provider formatters (per D2), HMAC signing (per D4).
5. Update `write_outputs()` to return the output stem map; update `watcher.process()` / `watcher.handle()` call sites.
6. Wire DDR-03 completion hook (blocked on DDR-03's drain interface being defined).
7. Frank gate.

## Risks

- **Timeout blocks the watcher thread.** The watcher loop is single-threaded; `notify()` blocks until timeout. At 5 s default this is acceptable for typical drop-folder throughput; high-volume deployments should set `NOTIFY_TIMEOUT_SEC` lower. Fire-and-forget via a thread pool is a future option, not now.
- **Retry multiplies latency.** At `notify_retries=1`, worst case is `2 × notify_timeout_sec` of wall time per failed ping. Default of 0 retries preserves today's single-attempt fast path.
- **`write_outputs()` return-value change.** Currently returns `None`; updating to `dict[str, Path]` is a minor, behaviour-preserving interface change. The one existing caller (`watcher.process()`) ignores the return value today and will be updated in the same commit.
- **Teams connector deprecation.** Microsoft is sunsetting legacy Incoming Webhook connectors in favour of Power Automate flows. If `_format_teams` ships day one, document the limitation prominently.
- **HMAC secret exposure via logging.** `_sign()` must not log the secret or the raw body bytes. Existing `log.warning("notify attempt ... failed: %s", e)` path is safe; take care not to add logging inside `_sign()`.

---

## Open questions / DECISIONS TO FLAG

- **D1 — Payload schema (remaining open bits).** *Resolved:* version policy is **integer, additive, starting at `schema_version: 1`** (fixed in DDR-02 D4 — documented there); **timing fields are `started_at`/`finished_at` canonical with `wall_sec` derived** (Frank's call, §1). *Still open:* should `outputs` carry full relative paths (e.g. `transcripts/meeting.txt`) or just filenames? Should a `snippet` (first ~200 chars of transcript text) be included, or is that scope creep for v1?

- **D2 — Providers day one.** Generic-only (post the structured dict; consumers adapt their own mapping) vs ship built-in Slack / Teams / ntfy formatters from the start. Generic is safe and zero-maintenance. Formatters add direct value for the homelab (Teams/ntfy) but add test surface and the Teams shape is already deprecated-in-flight. *Lean: generic + ntfy day one; Teams deferred.*

- **D3 — Retry policy and timeout value.** `notify_retries=0` (no retry, current behaviour) vs 1 (single immediate retry) vs exponential backoff up to N attempts. Should 4xx responses (likely misconfigured endpoint) be retried, or only 5xx / network errors? Timeout default: 5 s or lower (2 s)?

- **D4 — HMAC signing.** Include in v1 or defer? The mechanism is cheap to add now but adds value only if consumers implement verification. None of the known consumers (n8n, Teams connector, ntfy) verify HMAC natively. *Lean: design and ship the mechanism behind `NOTIFY_HMAC_SECRET=""`; document but do not require it.*

- **D5 — Single endpoint vs per-event routing.** `NOTIFY_WEBHOOK` is currently a single URL that receives all events. Should multiple URLs be supported (`NOTIFY_WEBHOOK_DONE`, `NOTIFY_WEBHOOK_FAILED`)? Should a filter allow firing only on specific event types (e.g. failures-only)? *Lean: single URL + all events for v1; per-event routing is a future DDR.*

- **D6 — `started` event.** Fire a notification when a file enters processing, not just when it completes? Valuable for DDR-05 long diarization jobs. Cost: one extra HTTP round-trip per file at the start of `watcher.process()`, and a corresponding `build_started_payload()` builder. *Lean: include `started` — it is a one-liner call site and pays off for DDR-05.*
