# DDR-03 — Groq Batch Async Backend

- **Status:** PROPOSED
- **Author:** reed
- **Date:** 2026-06-14
- **Sprint (on approval):** `groq-batch-backend`
- **Depends on:** DDR-02 (backend seam + AsyncBackend protocol) — PROPOSED
- **Blocks:** DDR-04 (completion webhook)
- **Supersedes:** —

---

## Context

DDR-02 §3 defined an `AsyncBackend` sub-protocol (`submit` / `poll` / `fetch`) to
accommodate asynchronous transcription providers without burdening sync backends.
Groq's Batch API is the first concrete consumer of that seam.

Groq Batch offers approximately 50% cost reduction relative to synchronous
`/audio/transcriptions` calls in exchange for up to ~24 hours of latency. For the
homelab use-case — overnight recordings, long-form content that doesn't need immediate
turnaround — this is the right trade-off.

The distinguishing constraint is the **process-restart boundary**: a job submitted now
may be retrieved hours later by a fresh process that never saw it in memory. The sync
watcher cannot block waiting for batch completion; `handle()` must return immediately
after submission. A separate drain path must be able to reconstitute enough state to
retrieve any pending job from a cold start.

**Critical pre-condition (D6):** Groq's Batch API must support `/audio/transcriptions`
as a batchable endpoint. If it does not, this DDR requires revision. The seam (DDR-02
§3) and job-store design (§4 below) remain valid regardless.

No behavior of the existing `local` or `api` backends changes under this DDR.

## Principle

Own the process-restart boundary explicitly. Every state transition of a batch job is
written to the job-state store before the corresponding filesystem or network action is
taken. The drain path is idempotent: running it twice on the same set of pending jobs
produces the same outputs and the same final state as running it once. Submission and
retrieval are fully decoupled; they share nothing except the state store.

---

## Decision

### 1. Backend class: `backends/batch_groq.py`

Anchors to the `AsyncBackend` protocol defined in DDR-02 §3. This DDR does not
redefine the seam; it provides the implementation.

```python
# src/electric_blue/backends/batch_groq.py

class GroqBatchBackend:
    name: str = "batch"
    capabilities: Capabilities  # is_async=True, needs_network=True,
                                # max_upload_mb=<VERIFY D8>, needs_gpu_recommended=False

    def submit(self, cfg: Config, src: Path) -> JobRef: ...
    def poll(self, cfg: Config, job: JobRef) -> JobStatus: ...
    def fetch(self, cfg: Config, job: JobRef) -> Transcript: ...
```

`GroqBatchBackend` is registered in the backend registry under key `"batch"` (DDR-02
§1). The synchronous `transcribe(cfg, src)` dispatcher in `backends/__init__.py` never
routes to it. Its callers are `watcher.handle_batch()` (submission) and
`drain.drain_batch()` (poll + fetch), both defined below.

### 2. Audio encoding

Reuse the existing ffmpeg encode path from `api.py`:

```python
extract(cfg, src, mp3_path, compressed=True)   # 64k MP3, same as the api backend
```

The existing `cfg.api_bitrate` (`"64k"`) and `cfg.ffmpeg_bin` apply unchanged. The
sync backend's 24 MB cap (`cfg.api_max_mb`) does not apply here without verification —
batch may accept larger files. A guard is still warranted; the threshold becomes
`cfg.batch_max_mb` (new Config field, §9, **VERIFY D8**).

### 3. Groq Batch API lifecycle

Modeled on the OpenAI Batch API pattern that Groq claims to follow. The general flow
is described below. **Every step is marked with its verification requirement; do not
treat any endpoint, field name, or schema as confirmed until checked against Groq's
current Batch API docs.**

---

**Step 3a — Upload audio file**

*VERIFY D6 first: is `/audio/transcriptions` a supported batch endpoint at all?*

```
POST <cfg.api_base_url>/files
  Authorization: Bearer <cfg.batch_api_key>
  Content-Type: multipart/form-data
  body: { file: <mp3 bytes, filename="a.mp3">, purpose: "batch" }
        # VERIFY: correct purpose value for audio files
→ { "id": "<audio_file_id>", "object": "file", ... }
```

**Step 3b — Build JSONL batch request file**

One request line per source file (D4 sets granularity). Each line is a JSON object:

```json
{
  "custom_id": "eb-<src_stem>",
  "method": "POST",
  "url": "/v1/audio/transcriptions",
  "body": {
    "file": "<audio_file_id>",
    "model": "<cfg.api_model>",
    "response_format": "verbose_json",
    "timestamp_granularities": ["segment"]
  }
}
```

VERIFY: whether `body.file` accepts a file ID or requires something else; whether
`timestamp_granularities` is accepted in batch context; how `language` is passed if
`cfg.language` is set; whether the `url` field uses `/v1/...` or a relative path.

**Step 3c — Upload JSONL file**

```
POST <cfg.api_base_url>/files
  body: { file: <jsonl bytes, filename="requests.jsonl">, purpose: "batch" }
        # VERIFY: same purpose as audio file, or a different value?
→ { "id": "<jsonl_file_id>", ... }
```

**Step 3d — Create batch object**

```
POST <cfg.api_base_url>/batches
  Authorization: Bearer <cfg.batch_api_key>
  Content-Type: application/json
  body: {
    "input_file_id": "<jsonl_file_id>",
    "endpoint": "/v1/audio/transcriptions",
    "completion_window": "24h"
  }
  # VERIFY: accepted endpoint string; accepted completion_window values
→ { "id": "<batch_id>", "status": "validating", ... }
```

`submit()` returns after this call succeeds. No blocking.

**Step 3e — Poll batch status** (called by drain path)

```
GET <cfg.api_base_url>/batches/<batch_id>
  Authorization: Bearer <cfg.batch_api_key>
→ {
    "id": "<batch_id>",
    "status": "<status>",
    "output_file_id": "<id> | null",
    "error_file_id": "<id> | null",
    ...
  }
```

VERIFY: complete set of status values (OpenAI uses `validating`, `in_progress`,
`finalizing`, `completed`, `failed`, `expired`, `cancelling`, `cancelled`); which are
terminal; whether `output_file_id` is present only at completion or also during
`finalizing`.

**Step 3f — Download and parse results** (called by drain path, only on `completed`)

```
GET <cfg.api_base_url>/files/<output_file_id>/content
  Authorization: Bearer <cfg.batch_api_key>
→ JSONL: one line per request:
  {
    "id": "...",
    "custom_id": "eb-<src_stem>",
    "response": {
      "status_code": 200,
      "body": {
        "segments": [ { "start": 0.0, "end": 2.4, "text": "..." }, ... ],
        "language": "en",
        "duration": 120.0,
        "text": "..."
      }
    },
    "error": null
  }
```

VERIFY: exact output line schema; whether per-line errors are possible alongside
successes in the same output file (partial completion); how to get the output file ID
(from batch object vs separate listing call); whether a separate error file exists.

Parsing logic mirrors `api.py`: `segments[]` → `list[Segment]`; fallback to single
segment from `text` if no timestamp segments; `language` + `duration` →
`TranscriptInfo(backend="batch:<cfg.api_model>")`.

**Step 3g — Cleanup**

After successful fetch, optionally delete the uploaded audio and JSONL files via the
Files API. VERIFY: Groq's file retention/expiry policy (D9); whether deletion is
required, optional, or unsupported; whether the output file must also be deleted.

---

### 4. Job-state store

A persistence layer mapping `job_id ↔ source file ↔ status`, surviving process
restarts. The backing mechanism is D1 (see Open Questions); the interface is fixed
regardless of choice.

**Data schemas:**

```python
# src/electric_blue/batch_store.py

from dataclasses import dataclass

@dataclass
class JobRef:
    """Returned by submit(); passed to poll() and fetch()."""
    job_id: str           # Groq batch object ID (e.g. "batch_abc123")
    audio_file_id: str    # Groq file ID of the uploaded MP3
    jsonl_file_id: str    # Groq file ID of the uploaded JSONL

@dataclass
class JobStatus:
    """Returned by poll()."""
    raw: str              # provider status string, unmodified
    terminal: bool        # True if no further polling is needed
    succeeded: bool       # True if completed successfully
    output_file_id: str | None
    error: str | None

@dataclass
class JobRecord:
    """Persisted to the state store at submission; updated through drain."""
    job_id: str
    audio_file_id: str
    jsonl_file_id: str
    src_name: str         # original filename (for logging and done/failed move)
    src_stem: str         # used as output file stem
    staged_path: str      # absolute path in batch_submitted_dir
    status: str           # "submitted" | "polling" | "completed" | "failed" | "expired"
    submitted_at: str     # ISO 8601
    completed_at: str | None
    error: str | None
```

**Store protocol:**

```python
class BatchStore(Protocol):
    def save(self, record: JobRecord) -> None: ...
    def get(self, job_id: str) -> JobRecord | None: ...
    def find_by_src_name(self, src_name: str) -> JobRecord | None: ...
    def list_pending(self) -> list[JobRecord]: ...  # status in ("submitted", "polling")
    def update(self, job_id: str, **kwargs) -> None: ...
```

`make_store(cfg) -> BatchStore` is the factory function, selected by D1. Its location
is `batch_store.py`. All state-store access goes through this interface; no caller
imports a concrete implementation directly.

### 5. Folder / queue model

Three new directories extend the existing `input_dir / output_dir / done_dir /
failed_dir` layout:

| Directory | Env var | Default | Purpose |
|-----------|---------|---------|---------|
| `batch_inbox_dir` | `TRANSCRIBE_BATCH` | `None` (feature off) | Drop files here to submit via batch |
| `batch_submitted_dir` | `TRANSCRIBE_BATCH_SUBMITTED` | `<base>/batch_submitted` | Staging: source file lives here between submit and fetch |
| `batch_store_path` | `TRANSCRIBE_BATCH_STORE` | `<base>/batch_store` | State store location (file path or directory, per D1) |

`batch_inbox_dir` being unset means the batch feature is entirely inactive: no
additional observer is registered, no store is initialized. Existing installs are
unaffected without any configuration change.

**Why a staging directory?** Moving the source file out of `batch_inbox_dir`
immediately after successful `submit()` prevents re-submission on watcher restart. The
file is not moved to `done_dir` until `fetch()` writes all four outputs. On permanent
failure or expiry, it moves to `failed_dir` with an error log entry. The staged file
is the recovery artifact: if the state store is corrupted, an operator can inspect
`batch_submitted/` to identify orphaned files.

The folder model is resolved by D3 (top-level dir vs `batch/` subfolder convention).

### 6. Watcher integration

The existing `handle()` / `run_watch()` path is not modified. A parallel observer is
added to `watcher.py` and scheduled only when `cfg.batch_inbox_dir` is set:

```python
# src/electric_blue/watcher.py  — additions only

def ensure_batch_dirs(cfg: Config) -> None:
    """Create batch staging dirs. Called only when batch_inbox_dir is configured."""
    for d in (cfg.batch_inbox_dir, cfg.batch_submitted_dir):
        d.mkdir(parents=True, exist_ok=True)

def handle_batch(cfg: Config, path: Path) -> None:
    if path.suffix.lower() not in cfg.media_exts or not is_stable(path, cfg.stability_seconds):
        return
    store = make_store(cfg)
    # Guard: don't re-submit if a live record already exists for this filename
    if store.find_by_src_name(path.name) is not None:
        log.warning("Batch: %s already has a pending job, skipping", path.name)
        return
    try:
        backend = GroqBatchBackend()
        job_ref = backend.submit(cfg, path)
        record = JobRecord(
            job_id=job_ref.job_id,
            audio_file_id=job_ref.audio_file_id,
            jsonl_file_id=job_ref.jsonl_file_id,
            src_name=path.name,
            src_stem=path.stem,
            staged_path=str(cfg.batch_submitted_dir / path.name),
            status="submitted",
            submitted_at=_now_iso(),
            completed_at=None,
            error=None,
        )
        store.save(record)                                     # persist BEFORE move
        shutil.move(str(path), record.staged_path)
        log.info("Batch submitted: %s -> job_id=%s", path.name, job_ref.job_id)
    except Exception as e:
        log.error("Batch submit failed: %s: %s", path.name, e)
        shutil.move(str(path), str(cfg.failed_dir / path.name))

# In run_watch(), after setting up the sync observer:
#   if cfg.batch_inbox_dir:
#       obs.schedule(BatchH(), str(cfg.batch_inbox_dir), recursive=False)
```

State is written to the store before the filesystem move. If the move fails, the
record exists in the store with `status="submitted"` and `staged_path` not yet present;
the drain path will log an error for that job rather than silently losing it.

### 7. Drain mechanism

```python
# src/electric_blue/drain.py

def drain_batch(cfg: Config) -> None:
    """Poll all pending batch jobs; fetch and finalize completed ones. Idempotent."""
    store = make_store(cfg)
    backend = GroqBatchBackend()
    for record in store.list_pending():
        try:
            job_ref = JobRef(
                job_id=record.job_id,
                audio_file_id=record.audio_file_id,
                jsonl_file_id=record.jsonl_file_id,
            )
            status = backend.poll(cfg, job_ref)
            if not status.terminal:
                store.update(record.job_id, status="polling")
                continue
            if status.succeeded:
                transcript = backend.fetch(cfg, job_ref)
                write_outputs(cfg, cfg.output_dir, record.src_stem,
                              transcript.segments, transcript.info)
                staged = Path(record.staged_path)
                if staged.exists():
                    shutil.move(str(staged), str(cfg.done_dir / record.src_name))
                store.update(record.job_id, status="completed",
                             completed_at=_now_iso())
                _fire_completion_hook(cfg, record, transcript.info)   # §8
            else:
                store.update(record.job_id, status=status.raw,
                             error=status.error or "batch job did not succeed")
                staged = Path(record.staged_path)
                if staged.exists():
                    shutil.move(str(staged), str(cfg.failed_dir / record.src_name))
                log.error("Batch job %s terminal failure: %s",
                          record.job_id, status.raw)
        except Exception as e:
            log.error("drain error for job %s: %s", record.job_id, e)
            # Leave status unchanged; next drain invocation will retry
```

`drain_batch` never re-fetches a job with `status="completed"` — `list_pending()`
filters by `status in ("submitted", "polling")`. The double-move guard (`if
staged.exists()`) handles the crash-between-update-and-move case (see Risks).

The drain trigger mechanism is D2 (see Open Questions). The CLI hook is in `cli.py`:

```python
ap.add_argument("--drain-batch", action="store_true",
                help="Poll pending Groq Batch jobs and retrieve completed ones.")
# In main():
if args.drain_batch:
    from .drain import drain_batch
    drain_batch(cfg)
    return
```

### 8. Completion hook point (DDR-04 boundary)

```python
def _fire_completion_hook(cfg: Config, record: JobRecord,
                          info: TranscriptInfo) -> None:
    """Best-effort hook. DDR-04 will own the full webhook payload shape."""
    mins = round(info.duration / 60, 1)
    notify(
        cfg,
        f"{record.src_name} -> batch done ({mins} min, {info.backend})",
        {
            "file": record.src_name,
            "status": "batch_done",
            "duration_min": mins,
            "backend": info.backend,
            "job_id": record.job_id,
        },
    )
```

The existing `notify()` from `notify.py` is reused unchanged. DDR-04 will either
replace this call body or augment the `meta` dict; the hook point is defined here so
DDR-04 has a named integration seam rather than retrofitting a scattered call site.

### 9. Config additions

New fields appended to the frozen `Config` dataclass; `from_env()` updated:

| Field | Type | Env var | Default | Notes |
|-------|------|---------|---------|-------|
| `batch_inbox_dir` | `Path \| None` | `TRANSCRIBE_BATCH` | `None` | Unset = batch disabled |
| `batch_submitted_dir` | `Path` | `TRANSCRIBE_BATCH_SUBMITTED` | `<base>/batch_submitted` | |
| `batch_store_path` | `Path` | `TRANSCRIBE_BATCH_STORE` | `<base>/batch_store` | Dir or file per D1 |
| `batch_api_key` | `str` | `GROQ_BATCH_API_KEY` | fallback: `WHISPER_API_KEY` | |
| `batch_max_mb` | `int` | `TRANSCRIBE_BATCH_MAX_MB` | 25 (placeholder) | VERIFY D8 |

`cfg.backend` remains the sync backend selector (`"local"` or `"api"`). Batch
activation is governed solely by `batch_inbox_dir` being set, allowing sync and batch
to coexist in the same process without conflating two orthogonal concerns.

### 10. What does not change

- `local.py`, `api.py`, `backends/__init__.py` — untouched.
- `watcher.handle()`, `watcher.run_once()`, `watcher.run_watch()` sync paths — untouched.
- `outputs.write_outputs()`, `models.py`, `audio.extract()` — called unchanged.
- `notify.py` — called but not modified.
- All four output formats (txt, srt, vtt, json) — identical to sync backends.
- The existing `ensure_dirs()` call in `cli.py` — unchanged; `ensure_batch_dirs()` is
  called separately only when `cfg.batch_inbox_dir` is not None.

---

## Sequencing (within the sprint)

1. Verify D6 against Groq Batch API docs before any code is written. If audio
   endpoints are unsupported, stop and revise.
2. Characterization tests first (DDR-02 pattern): pin `JobRecord` schema, `BatchStore`
   interface, new Config fields — all hermetic, no network.
3. Add Config batch fields + `ensure_batch_dirs`.
4. Implement `batch_store.py` with the D1 backing mechanism.
5. Implement `backends/batch_groq.py` with mocked HTTP (`responses` or
   `unittest.mock`) — exercise the full lifecycle (3a through 3g) in tests.
6. Implement `drain.py` with mocked store and mocked backend.
7. Wire `handle_batch` + batch observer into `watcher.py`; add `--drain-batch` to
   `cli.py`.
8. Integration test: drive the full lifecycle (submit → poll × N → fetch → outputs
   written → files moved) through `drain_batch()` with mocks.
9. Frank gate. Manual smoke against live Groq Batch API if D6 is confirmed.

## Risks

- **Groq Batch does not support audio transcription** — highest priority to verify
  before sprint start. All of §3 is contingent on D6. The state-store and seam designs
  are not affected; the lifecycle steps would need replacement.
- **Job expiry before drain runs** — if the drain mechanism (D2) is not running and a
  job's 24h window elapses, the transcript is lost. The source file is still in
  `batch_submitted_dir`; recovery is operator-driven re-submission. Mitigate by: logging
  a warning in drain for jobs approaching expiry (e.g. submitted more than 20h ago,
  still pending).
- **Crash between state-store write and filesystem move** — `shutil.move` is not
  atomic. If the process dies after `store.save(record)` but before the move to
  `batch_submitted_dir`, the file remains in `batch_inbox_dir` and a state record
  exists. On next watcher start, `find_by_src_name()` detects the collision and skips
  re-submission. Drain will log an error when it finds the `staged_path` missing.
  Operator resolution: delete the orphaned state record and re-drop the file.
- **Crash between store.update(completed) and move to done_dir** — the `if
  staged.exists()` guard in `drain_batch` handles this: the move is retried on the next
  drain run even though the store record is already `completed`.
- **Groq file storage cost or premature expiry** — uploaded audio files may incur cost
  or be auto-deleted before the batch completes. VERIFY D9.
- **State-store contention** — if `run_watch` and `--drain-batch` run concurrently
  (e.g. watcher is running and cron fires drain), both may write to the store
  simultaneously. For the sidecar-JSON option (D1 lean), each job's file is independent
  so collisions are per-job. For SQLite, WAL mode handles concurrent readers. Either
  way, document that simultaneous `--drain-batch` invocations are unsupported.

## Open questions / DECISIONS TO FLAG

- **D1 — Job-state store backing mechanism.**
  - *SQLite* (`batch_store.db`): ACID, standard library (`sqlite3`), survives partial
    writes, queryable. Requires defining a schema and a trivial migration story.
  - *Sidecar JSON files* (`batch_store/<job_id>.json`): one file per job, human-
    inspectable and manually deletable, no locking concerns for single-process drain,
    no schema migration. Recovery: `ls batch_store/`. Zero new deps.
  - *Single JSON file* (`batch_jobs.json`): simplest but requires a full-file rewrite
    on every update; not crash-safe without an atomic rename dance.
  Lean: sidecar JSON files — the homelab context makes human-inspectability and
  zero-migration more valuable than queryability. **DECISION.**

- **D2 — Drain trigger mechanism.**
  - *CLI subcommand + cron*: `electric-blue --drain-batch`, e.g. every 30 minutes via
    crontab. No long-running process, testable in isolation. Notification latency up to
    30 min after completion.
  - *Long-running daemon*: dedicated thread or process polling on a configurable
    interval. More responsive; adds process management complexity.
  - *Fold into existing watcher loop*: `run_watch()` calls `drain_batch()` on each
    poll tick. Couples concerns; watcher already does one thing.
  Lean: CLI subcommand + cron. The 30-min latency is acceptable given the 24h window;
  separation of concerns is worth it. **DECISION.**

- **D3 — Batch inbox folder model.**
  - *Separate top-level directory* (e.g. `~/transcribe/batch_inbox`, set via
    `TRANSCRIBE_BATCH`): clean separation, independent of `input_dir`.
  - *Subfolder convention* (`<input_dir>/batch/`): mirrors the homelab `batch/` folder
    design; single base dir contains all queues; no additional env var required (derive
    from `input_dir`).
  No strong lean; the homelab convention is familiar to the existing install, but a
  separately configured directory keeps the sync and batch queues fully decoupled.
  **DECISION.**

- **D4 — Batch granularity: one audio file per batch object vs many.**
  One-file-one-batch-object is the simplest approach: `job_id` maps unambiguously to
  one source file, partial-failure handling is trivial, and the state-store schema stays
  flat. Aggregating many files into a single batch JSONL (one batch object per N files)
  reduces API round-trips and may be required if Groq imposes a minimum batch size.
  VERIFY whether Groq requires or recommends aggregation. Lean: one-per-batch
  initially; aggregation is a future optimization if there is a cost or rate-limit
  reason for it. **DECISION.**

- **D5 — Error and expiry handling policy.**
  When a batch job reaches `failed` or `expired`: move source from `batch_submitted_dir`
  to `failed_dir`, update state store, fire hook with error payload, log prominently.
  Options: (a) automatic re-submission — risky (could re-submit repeatedly if root cause
  is not transient); (b) move to `failed_dir` and require operator to re-drop the file
  into `batch_inbox_dir` — fail loudly, require human re-queue; (c) move to a dedicated
  `batch_retry_dir` for operator review before re-queue.
  Lean: option (b), consistent with how the sync path handles failures. **DECISION.**

- **D6 — VERIFY: Does Groq Batch API support `/audio/transcriptions` as a batchable
  endpoint?** This is the critical pre-condition for the entire DDR. Groq's Batch API
  documentation must be checked before sprint start. If audio transcription is
  unsupported, evaluate whether a Groq async audio job API (if one exists) provides
  equivalent economics.

- **D7 — VERIFY: Groq Batch API endpoints and request/response schemas.** Specifically:
  file upload endpoint URL and `purpose` field value; whether the audio file in the
  JSONL request body is a file ID or something else; batch creation body fields
  (`endpoint`, `completion_window`, accepted values); output JSONL line format; whether
  a separate error file exists alongside the output file.

- **D8 — VERIFY: Audio file size limit for batch uploads.** The sync `api` backend
  enforces 24 MB. Batch may accept larger files (desirable, since that is a primary
  reason to use batch). Until confirmed, `batch_max_mb` defaults to 25 MB with a
  `TRANSCRIBE_BATCH_MAX_MB` env override.

- **D9 — VERIFY: Groq file retention and expiry policy.** How long do uploaded input
  files and batch output files persist on Groq's Files API? Is explicit deletion
  required after fetching results? Does the output file expire before a 30-minute cron
  drain cycle could run?

- **D10 — Separate Groq API key for batch.** `GROQ_BATCH_API_KEY` falling back to
  `WHISPER_API_KEY` allows shared or separated credentials without a required config
  change for most users. Confirm whether the same key and organization scope is
  appropriate for batch submissions, or whether a separate key is needed (e.g. different
  Groq tier). Likely trivial but worth confirming. **DECISION.**
