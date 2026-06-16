# Requirements: groq-batch

- **Status:** DRAFT (post-review revision 2026-06-16)
- **Author:** reed
- **Date:** 2026-06-16
- **DDR:** DDR-03-groq-batch-backend.md (ACCEPTED 2026-06-16, Danny)
- **Sprint:** groq-batch-backend (GitHub issue #15)
- **Acceptance Criteria:** 67 (CHAR 4 + CFG 10 + STORE 8 + STAG 7 + ASYNC 12 + SUBMIT 8 + DRAIN 10 + HOOK 3 + FAIL 4 + CLI 1)

---

## Summary

Add an `AsyncBackend` sub-protocol and its first concrete implementation (`GroqBatchBackend`)
to the electric-blue drop-folder pipeline. Files dropped into a separate `batch_inbox_dir` are
encoded to MP3, staged to a Tailscale Funnel public HTTPS URL via a `UrlStager` abstraction,
submitted to the Groq Batch API as a JSONL job, and retrieved asynchronously by a separate drain
path (`electric-blue --drain-batch`). A sidecar-JSON job-state store (`BatchStore`) persists
every state transition before any filesystem action so the drain path can reconstitute full job
state from a cold process start. All existing sync paths (`local`, `api`, `watcher.handle()`,
`watcher.run_once()`, `watcher.run_watch()`) are untouched.

---

## Locked Constraints (DDR-03 Sprint Decisions — LOCKED 2026-06-16)

These decisions are resolved and closed. All requirements below treat them as immutable.
Supersede any conflicting "Lean" notes in the DDR Open Questions section.

| ID | Constraint |
|----|-----------|
| D1 | Job-state store: sidecar JSON files (`batch_store/<job_id>.json`). Zero new deps; human-inspectable; no migration story. |
| D2 | Drain trigger: `electric-blue --drain-batch` CLI flag + cron (e.g. every 30 min). No long-running drain daemon. |
| D3 | Batch inbox: separate top-level directory, env var `TRANSCRIBE_BATCH`. Fully decoupled from `input_dir`. |
| D4 | Batch granularity: one audio file per batch object. Aggregation is a future optimization. |
| D5 | Terminal failure/expiry: staged source moves to `failed_dir`; operator re-drops to retry. No automatic re-submission. |
| D6 | Groq Batch API accepts `/v1/audio/transcriptions` (confirmed). Audio input is **PUBLIC HTTPS URL only** — no Groq-side audio file upload. |
| D10 | Batch API key: `GROQ_BATCH_API_KEY` with fallback to `WHISPER_API_KEY`. |
| Staging | Stage local MP3 to Tailscale Funnel public HTTPS URL. Staging MUST be behind a `UrlStager` protocol (`stage(path) -> url`, `unstage(url)`), with `FunnelStager` as the first implementation. R2/B2 minted-URL is a future drop-in requiring no backend rearchitect. |
| completion_window | Default `"24h"` (Groq-documented minimum). Configurable. Bounds how long the staged Funnel URL must remain reachable. |

---

## Flagged Assumptions

The following items are required by the Sprint Decisions but are either not specified in DDR §9
or conflict with DDR body text that the Sprint Decisions supersede. Each must be confirmed by the
architect before the implementation slice.

**A1 — `JobRef`/`JobRecord` schema correction (DDR §4 vs Sprint Decisions)**

DDR §4 defines `JobRef.audio_file_id: str` ("Groq file ID of the uploaded MP3") and
`JobRecord.audio_file_id: str`. The Sprint Decisions explicitly remove the audio file upload step
(§3a) and the `body.file` field (§3b). In the URL-based model, no audio file is uploaded to
Groq; only the JSONL file is uploaded. Therefore `audio_file_id` is inapplicable as a Groq file
ID. **Assumed resolution:** both `JobRef.audio_file_id` and `JobRecord.audio_file_id` are
replaced by `staged_url: str` (the public HTTPS URL returned by `stager.stage()`). All
requirements below use this corrected schema. Requires architect confirmation.

**A2 — `batch_completion_window` Config field (not in DDR §9 table)**

The Sprint Decisions require `completion_window` to be configurable. DDR §9's config additions
table does not list this field. **Assumed:** a new `batch_completion_window: str` field with
default `"24h"` and env var `TRANSCRIBE_BATCH_COMPLETION_WINDOW` is added to `Config`. Requires
architect confirmation of field name and accepted value format.

**A3 — `FunnelStager` Config fields (not in DDR §9 table)**

`FunnelStager` must know (a) the directory from which Tailscale Funnel serves files, and (b) the
public HTTPS base URL. Neither is specified in DDR §9. **Assumed:** two new Config fields are
needed — e.g. `batch_stage_dir: Path` (env `TRANSCRIBE_BATCH_STAGE_DIR`, default
`<base>/batch_stage`) and `batch_funnel_base_url: str` (env `TRANSCRIBE_BATCH_FUNNEL_URL`,
default `""`). Requires architect to name and default these fields.

**A4 — Duplicate-submission guard is live-record-only**

DDR §6 code shows `find_by_src_name() is not None → skip`. If a file was previously failed
and the operator re-drops it (per D5 recovery path), a terminal record exists. The guard must
check for **live** records only (`status in ("submitted", "polling")`) so that operator re-drops
work correctly. Requirements below use this refined guard.

**A5 — `is_async` added to `Capabilities` this sprint**

`base.py` defers `is_async` to DDR-03 with comment "deferred to DDR-03 with AsyncBackend."
`Capabilities` must gain `is_async: bool = False` (with a default to avoid breaking
`LocalBackend` and `ApiBackend` instantiation). Existing capabilities instantiations must
be updated to pass `is_async=False` explicitly (INV-3 char-test required first).

**A6 — `GroqBatchBackend` is instantiated directly, not via sync `_REGISTRY`**

DDR §6-7 code snippets show `backend = GroqBatchBackend()` called directly in `handle_batch()`
and `drain_batch()`. This is consistent with DDR §1 ("the synchronous `transcribe()` dispatcher
never routes to it"). Requirements below treat the batch backend as directly instantiated rather
than registry-dispatched. If the architect places it in `_REGISTRY`, then `WHISPER_BACKEND=batch`
must raise `RuntimeError` at `transcribe()` call time (fail-loud per INV-2).

**A7 — JSONL file cleanup (D9 is VERIFY)**

DDR §3g describes optional cleanup of uploaded JSONL and output files via Groq's Files API after
successful fetch. D9 (Groq file retention policy) is marked VERIFY and is unconfirmed. This
sprint does NOT include Groq-side file deletion. Cleanup is deferred pending D9 verification.

---

## User Stories

### US-01 — Characterization tests: pin pre-change sync-path and Capabilities behavior

As a pipeline developer,
I want characterization tests pinning the observable behaviors of `watcher.handle()`,
`watcher.run_watch()`, `transcribe()`, `write_outputs()`, and the `Capabilities` dataclass
before any batch code is added,
so that any unintended regression in the sync path or existing capabilities contract introduced
during this sprint is detected immediately.

### US-02 — UrlStager abstraction and FunnelStager implementation

As a pipeline operator,
I want audio files staged to a public HTTPS URL via a `UrlStager` protocol with `FunnelStager`
as its first implementation,
so that Groq's URL-only batch input requirement is satisfied without hardcoding the staging
mechanism, enabling a future swap to minted object-storage URLs without modifying
`GroqBatchBackend` or `drain_batch`.

### US-03 — AsyncBackend protocol and GroqBatchBackend

As a pipeline developer,
I want an `AsyncBackend` protocol (`submit` / `poll` / `fetch`) defined alongside
`GroqBatchBackend`,
so that the async transcription lifecycle is typed, independently testable, and decoupled from
the synchronous `Backend` protocol.

### US-04 — Job-state store (BatchStore, sidecar JSON)

As a pipeline operator,
I want every batch job's state persisted to a sidecar JSON file before any corresponding
filesystem or network action is taken,
so that no job is orphaned or silently lost across process restarts (INV-1 extended to the
batch path).

### US-05 — Batch submission path (watcher integration)

As a pipeline operator,
I want files dropped into `batch_inbox_dir` to be automatically picked up, encoded, staged,
submitted to Groq Batch, and moved to `batch_submitted_dir` while the watcher continues
monitoring,
so that I can queue files for overnight batch transcription without blocking the sync watcher
or requiring manual intervention.

### US-06 — Config additions (batch fields)

As a pipeline operator,
I want to configure the batch inbox, staging dirs, store path, API key, file size limit,
completion window, and Funnel URL via environment variables with safe defaults,
so that the batch feature is entirely off by default and can be enabled per deployment without
changing defaults for existing sync installs.

### US-07 — Drain mechanism (`drain_batch` + `--drain-batch` CLI flag)

As a pipeline operator,
I want to run `electric-blue --drain-batch` (or schedule it as a cron job) to poll all pending
batch jobs and finalize completed ones,
so that transcription results are retrieved automatically without requiring a persistent
long-running drain process.

### US-08 — Completion hook (DDR-04 boundary)

As a pipeline operator,
I want a completion notification fired after every successfully drained batch job, using the
existing DDR-04 `notify()` two-argument signature,
so that the same webhook consumer receives consistent structured notifications for both sync and
batch completions without a separate notification path.

### US-09 — Failure and expiry handling

As a pipeline operator,
I want permanently failed or expired batch jobs to have their staged source moved to `failed_dir`
with an error log entry, and the staged URL cleaned up from the Funnel serve path,
so that I can identify failed files and re-drop them to retry, without data loss and without
orphaned staged MP3 files.

---

## Acceptance Criteria

### US-01 — Characterization tests

**Written and committed green BEFORE any source change.** This is the INV-3 / CADENCE
char-tests-first requirement. The entire gate must be green at this step.

- [ ] **[CHAR-1]** Given the existing `watcher.handle()` code, when a supported media file is in
  `input_dir` and `process()` succeeds, then the file is moved to `done_dir` and `failed_dir`
  is untouched — confirmed by a characterization test green against pre-change code.
- [ ] **[CHAR-2]** Given the existing `watcher.handle()` code, when `process()` raises any
  `Exception`, then the file is moved to `failed_dir` and `done_dir` is untouched — confirmed
  by a characterization test green against pre-change code.
- [ ] **[CHAR-3]** Given `cfg.batch_inbox_dir` is `None`, when `run_watch()` is called, then
  exactly one `Observer.schedule()` call occurs (for `cfg.input_dir`); no second observer is
  scheduled — confirmed by a characterization test green against pre-change code.
- [ ] **[CHAR-4]** Given the existing `Capabilities` dataclass, when `LocalBackend.capabilities`
  and `ApiBackend.capabilities` are accessed, then neither raises `AttributeError` and all
  existing capability fields match their pre-change values — confirmed by a characterization
  test that must remain green after `is_async` is added (A5).

### US-02 — UrlStager abstraction and FunnelStager

- [ ] **[STAG-1]** `UrlStager` is a `Protocol` with exactly two methods: `stage(self, path: Path) -> str` and `unstage(self, url: str) -> None`. No explicit base-class inheritance is required; structural match suffices.
- [ ] **[STAG-2]** Given a configured `FunnelStager` with `base_url="https://host.ts.net/stage"` and `stage_dir=<tmp>`, when `stager.stage(Path("/batch_submitted/meeting.mp3"))` is called, then: (a) `meeting.mp3` is copied into `stage_dir`, and (b) the returned string equals `"https://host.ts.net/stage/meeting.mp3"` (no absolute filesystem path component).
- [ ] **[STAG-3]** Given a URL previously returned by `stager.stage()`, when `stager.unstage(url)` is called, then the corresponding file is removed from `stage_dir`. Subsequent calls to `unstage(url)` for the same URL do not raise (idempotent).
- [ ] **[STAG-4]** Given a `UrlStager` mock that records calls, when `GroqBatchBackend.submit()` completes successfully with mocked HTTP, then `stager.stage(mp3_path)` was called exactly once and the returned URL appears verbatim as `body.url` in the JSONL request line.
- [ ] **[STAG-5]** Given a `UrlStager` mock, when a batch job reaches any terminal state (completed, failed, or expired) during `drain_batch()`, then `stager.unstage(record.staged_url)` is called exactly once for that job.
- [ ] **[STAG-6]** Given `stager.stage()` raises any exception, when `handle_batch()` calls `backend.submit()` which calls the stager, then: (a) the exception propagates to `handle_batch()`'s outer `except` block, (b) no `JobRecord` is written to the store, (c) the source file is moved to `cfg.failed_dir`, and (d) an error is logged.
- [ ] **[STAG-7]** Given `src=Path("/batch_inbox/meeting.mp4")`, when `GroqBatchBackend.submit(cfg, src)` encodes the audio and stages the result, then: (a) the MP3 passed to `stager.stage()` is named `f"{src.stem}.mp3"` (i.e., `"meeting.mp3"`, not `"a.mp3"`), and (b) the URL returned by `FunnelStager.stage()` equals `f"{cfg.batch_funnel_base_url}/{src.stem}.mp3"` — ensuring the staged URL is unique per source file and preventing filename collisions in `batch_stage_dir` across concurrent or sequential submissions (closes B3).

### US-03 — AsyncBackend protocol and GroqBatchBackend

- [ ] **[ASYNC-1]** `AsyncBackend` is a `Protocol` with three methods: `submit(self, cfg: Config, src: Path) -> JobRef`, `poll(self, cfg: Config, job: JobRef) -> JobStatus`, `fetch(self, cfg: Config, job: JobRef) -> Transcript`. `GroqBatchBackend` satisfies it structurally.
- [ ] **[ASYNC-2]** `GroqBatchBackend.capabilities` is a `Capabilities` instance with `is_async=True`, `needs_network=True`, `needs_gpu_recommended=False`, and `max_upload_mb is None`. Size-cap enforcement is handled internally by `submit()` via `cfg.batch_max_mb` (see ASYNC-11); the `Capabilities` field is not used as a per-call cap in the async path.
- [ ] **[ASYNC-3]** Given mocked HTTP responses (zero live network), when `GroqBatchBackend.submit(cfg, src)` is called, then it: (a) calls `audio.extract(cfg, src, mp3, compressed=True)` reusing the existing ffmpeg encode path, (b) calls `stager.stage(mp3)` to obtain a public HTTPS URL, (c) constructs exactly one JSONL line containing `"url": <staged_url>` in `body`, no `"file"` field in `body`, and `"custom_id": f"eb-{src.stem}"` at the top level of the request object, (d) POSTs the JSONL to `<cfg.api_base_url>/files`, (e) POSTs to `<cfg.api_base_url>/batches` with `"completion_window": cfg.batch_completion_window`, and (f) returns a `JobRef` with `job_id` and `jsonl_file_id` set and `staged_url` matching the stager's return value.
- [ ] **[ASYNC-4]** Given a mock returning `{"status": "in_progress"}`, when `poll(cfg, job)` is called, then it returns `JobStatus(raw="in_progress", terminal=False, succeeded=False, output_file_id=None, error=None)`.
- [ ] **[ASYNC-5]** Given a mock returning `{"status": "completed", "output_file_id": "file_abc"}`, when `poll(cfg, job)` is called, then it returns `JobStatus(raw="completed", terminal=True, succeeded=True, output_file_id="file_abc", error=None)`.
- [ ] **[ASYNC-6]** Given mocks returning `{"status": "failed"}` and `{"status": "expired"}` and `{"status": "cancelled"}`, when `poll()` is called for each, then all three return `JobStatus(terminal=True, succeeded=False)` (all are recognized terminal-failure states).
- [ ] **[ASYNC-7]** Given a mock `output_file_id` and a mock JSONL output line with `"segments": [{"start": 0.0, "end": 2.4, "text": "hello"}]`, when `fetch(cfg, job)` is called, then it returns a `Transcript` whose `segments` contains one `Segment(start=0.0, end=2.4, text="hello")` and whose `info.backend` equals `f"batch:{cfg.api_model}"`.
- [ ] **[ASYNC-8]** Given a mock JSONL output line with `"text": "hello world"` and no `"segments"` key, when `fetch()` is called, then it returns a `Transcript` with one synthetic segment `Segment(start=0.0, end=<duration>, text="hello world")`, mirroring `api.py` fallback behavior.
- [ ] **[ASYNC-9]** Given `cfg.batch_api_key=""` (empty string, after D10 fallback is exhausted), when `submit()` is called, then it raises `RuntimeError` before making any network call (fail-loud per INV-2; no silent fallback to a different backend).
- [ ] **[ASYNC-10]** Given `cfg.language` is set, when `submit()` constructs the JSONL body, then the `language` field is included in `body` (consistent with `api.py` behavior). Given `cfg.language` is `None`, then no `language` field is present in `body`.
- [ ] **[ASYNC-11]** Given a source file whose encoded MP3 size (in megabytes) exceeds `cfg.batch_max_mb`, when `GroqBatchBackend.submit(cfg, src)` is called with mocked HTTP, then it raises `RuntimeError` (size-cap guard, architecture §5 step 4) before any `requests.post` call is made. Via SUBMIT-5, the source file is subsequently moved to `cfg.failed_dir`.
- [ ] **[ASYNC-12]** Given a mock returning `{"status": "validating"}` or any other unrecognized status string, when `poll(cfg, job)` is called, then it returns `JobStatus(raw=<status>, terminal=False, succeeded=False, output_file_id=None, error=None)` — the conservative "unknown → not terminal" policy ensures drain retries on the next invocation.

### US-04 — Job-state store (BatchStore, sidecar JSON)

- [ ] **[STORE-1]** `BatchStore` is a `Protocol` with methods: `save(record: JobRecord) -> None`, `get(job_id: str) -> JobRecord | None`, `find_by_src_name(src_name: str) -> JobRecord | None`, `list_pending() -> list[JobRecord]`, `update(job_id: str, **kwargs) -> None`. `make_store(cfg) -> BatchStore` is the factory; callers never import a concrete class directly.
- [ ] **[STORE-2]** Given `make_store(cfg).save(record)` is called, then a file named `<record.job_id>.json` exists in `cfg.batch_store_path` containing all `JobRecord` fields as valid JSON.
- [ ] **[STORE-3]** Given `list_pending()` is called, then it returns only records whose `status` is in `{"submitted", "polling"}`; records with `status` in `{"completed", "failed", "expired", "cancelled"}` are excluded.
- [ ] **[STORE-4]** Given `save(record)` followed by `update(record.job_id, status="completed", completed_at="2026-06-16T12:00:00+00:00")`, when `get(record.job_id)` is called, then `record.status == "completed"` and `record.completed_at` equals the provided value, and all other original fields are unchanged.
- [ ] **[STORE-5]** Given `find_by_src_name("meeting.mp4")` is called and a record exists with `src_name="meeting.mp4"`, then that record is returned; given no record has that `src_name`, then `None` is returned.
- [ ] **[STORE-6]** Given a process cold-start (new Python process, new `make_store(cfg)` call on the same `batch_store_path`), when `list_pending()` is called, then it returns the same pending records that were written in the previous process session.
- [ ] **[STORE-7]** Given two sidecar files for distinct `job_id` values exist in `batch_store_path`, when `update(job_id="A", status="completed")` is called, then the sidecar file for `job_id="B"` is not modified.
- [ ] **[STORE-8]** `JobRecord` is a dataclass with at minimum these fields: `job_id: str`, `jsonl_file_id: str`, `staged_url: str`, `src_name: str`, `src_stem: str`, `staged_path: str`, `status: str`, `submitted_at: str`, `completed_at: str | None`, `error: str | None`. All fields are JSON-serializable without custom encoders. (Field `staged_url` replaces the `audio_file_id` field in DDR §4 per assumption A1.)

### US-05 — Batch submission path (watcher integration)

- [ ] **[SUBMIT-1]** Given `cfg.batch_inbox_dir` is set and a valid media file arrives, when `handle_batch(cfg, path)` is called, then the execution order is: (1) `is_stable()` check, (2) `store.find_by_src_name()` live-record guard (A4), (3) `backend.submit()`, (4) `store.save(record)`, (5) `shutil.move(path, batch_submitted_dir / path.name)`. No step is reordered.
- [ ] **[SUBMIT-2]** Given `cfg.batch_inbox_dir` is `None`, when `run_watch()` starts, then no batch observer is registered, `ensure_batch_dirs()` is not called, and the sync observer behaves identically to its pre-change behavior (CHAR-3 companion).
- [ ] **[SUBMIT-3]** Given a file named `meeting.mp4` has an existing store record with `status="submitted"` or `status="polling"`, when `handle_batch()` is called with a new `meeting.mp4`, then `submit()` is NOT called and a `WARNING` is logged. (Live-record guard per A4.)
- [ ] **[SUBMIT-4]** Given a file named `meeting.mp4` has an existing store record with `status="failed"` or `status="expired"`, when `handle_batch()` is called with a re-dropped `meeting.mp4`, then `submit()` IS called and a new `JobRecord` is created. (Terminal records do not block re-submission per A4 and D5.)
- [ ] **[SUBMIT-5]** Given `backend.submit()` raises any exception, when `handle_batch()` catches it, then: (a) no store record is written, (b) the file is moved to `cfg.failed_dir`, and (c) an error is logged. `done_dir` is untouched (INV-1).
- [ ] **[SUBMIT-6]** Given `store.save(record)` succeeds and then `shutil.move()` raises, when the state is inspected, then: the store record exists with `status="submitted"` and `staged_path` equals `str(cfg.batch_submitted_dir / path.name)` (the intended DESTINATION — set unconditionally before the move); the source file remains at `batch_inbox_dir / path.name` because the move did not complete. On the next `handle_batch()` call for the same filename, the live-record guard detects the existing `status="submitted"` record and skips re-submission. Recovery is operator-driven: delete the orphaned sidecar and re-drop the source file (architecture §7).
- [ ] **[SUBMIT-7]** Given a file with a suffix not in `cfg.media_exts`, when `handle_batch()` is called, then it returns without calling `submit()`, `store.save()`, or any filesystem move.
- [ ] **[SUBMIT-8]** Given any successful `store.save(record)` call in `handle_batch()`, then `record.staged_path == str(cfg.batch_submitted_dir / path.name)` — the DESTINATION path, not the source path. This value is set unconditionally before `shutil.move()` executes so that `drain_batch()` always knows where the source file should be, regardless of whether the move completed.

### US-06 — Config additions

- [ ] **[CFG-1]** Given no batch-related env vars are set, when `Config.from_env()` is called, then: `cfg.batch_inbox_dir is None`, `cfg.batch_submitted_dir == cfg.base_dir / "batch_submitted"`, `cfg.batch_store_path == cfg.base_dir / "batch_store"`, `cfg.batch_api_key == ""`, `cfg.batch_max_mb == 25`, `cfg.batch_completion_window == "24h"`, `cfg.batch_stage_dir == cfg.base_dir / "batch_stage"`, and `cfg.batch_funnel_base_url == ""`. (All 8 new batch fields verified.)
- [ ] **[CFG-2]** Given `TRANSCRIBE_BATCH="/home/user/batch_inbox"`, when `Config.from_env()` is called, then `cfg.batch_inbox_dir == Path("/home/user/batch_inbox")`.
- [ ] **[CFG-3]** Given `GROQ_BATCH_API_KEY="gk-abc"` and `WHISPER_API_KEY="sk-xyz"`, when `Config.from_env()` is called, then `cfg.batch_api_key == "gk-abc"` (D10: explicit key takes precedence over fallback).
- [ ] **[CFG-4]** Given no `GROQ_BATCH_API_KEY` and `WHISPER_API_KEY="sk-xyz"`, when `Config.from_env()` is called, then `cfg.batch_api_key == "sk-xyz"` (D10 fallback).
- [ ] **[CFG-5]** Given `TRANSCRIBE_BATCH_MAX_MB="50"`, when `Config.from_env()` is called, then `cfg.batch_max_mb == 50` and `isinstance(cfg.batch_max_mb, int) is True`.
- [ ] **[CFG-6]** Given `TRANSCRIBE_BATCH_COMPLETION_WINDOW="7d"`, when `Config.from_env()` is called, then `cfg.batch_completion_window == "7d"`.
- [ ] **[CFG-7]** No existing `Config` field is removed or has its default changed. All pre-existing `test_config.py` tests remain green after the additions.
- [ ] **[CFG-8]** `Config` remains a frozen dataclass; assigning to any new batch field after construction raises `FrozenInstanceError` (or `AttributeError`).
- [ ] **[CFG-9]** `cfg.batch_api_key` does not appear in any log record at any level — asserted via `caplog.text` across any code path that reads the field (INV-7 — secrets never in runtime artifacts).
- [ ] **[CFG-10]** Given `cfg.batch_inbox_dir` is not `None` and `cfg.batch_funnel_base_url == ""`, when `ensure_batch_dirs(cfg)` is called (as happens in `run_watch()` startup), then it raises `RuntimeError` — causing the watcher process to abort before any file is accepted into the batch inbox. (Primary B1 guard: misconfiguration is discovered at boot, not at first file drop.)

### US-07 — Drain mechanism

- [ ] **[DRAIN-1]** Given `store.list_pending()` returns two records, when `drain_batch(cfg)` is called, then `backend.poll()` is called exactly twice (once per pending record).
- [ ] **[DRAIN-2]** Given `poll()` returns `terminal=False`, when `drain_batch()` processes that record, then `store.update(record.job_id, status="polling")` is called and the record remains in `list_pending()` for the next drain invocation.
- [ ] **[DRAIN-3]** Given `poll()` returns `terminal=True, succeeded=True, output_file_id="file_abc"`, when `drain_batch()` processes that record, then in order: (a) `backend.fetch()` is called, (b) `write_outputs(cfg, cfg.output_dir, record.src_stem, segments, info)` is called and all four output formats are written, (c) the staged file is moved to `cfg.done_dir / record.src_name`, (d) `store.update(record.job_id, status="completed", completed_at=<now_iso>)` is called, (e) `_fire_completion_hook(cfg, record, info)` is called. No step is reordered.
- [ ] **[DRAIN-4]** Given `poll()` returns `terminal=True, succeeded=False`, when `drain_batch()` processes that record, then: (a) `backend.fetch()` is NOT called, (b) the staged file is moved to `cfg.failed_dir / record.src_name`, (c) `store.update(record.job_id, status=status.raw, error=<error>)` is called, (d) an error is logged. `done_dir` is untouched (INV-1).
- [ ] **[DRAIN-5]** `drain_batch()` is idempotent: running it twice on the same set of pending jobs produces the same final state and the same output files as running it once. (DRAIN-3's write_outputs is idempotent; DRAIN-3's `if staged.exists()` guard handles the case where the staged file was already moved.)
- [ ] **[DRAIN-6]** Given a crash between `shutil.move(staged → done_dir)` and `store.update(status="completed")`, when the next `drain_batch()` runs, then: the record is still `status="polling"` in `list_pending()`; `poll()` is called again and returns `completed`; `fetch()` is called again (idempotent); `write_outputs()` overwrites outputs (idempotent); `if staged.exists()` is `False` (already moved), so no second move; `store.update(status="completed")` succeeds. No data is lost (INV-1).
- [ ] **[DRAIN-7]** Given `poll()` raises an exception for one record, when `drain_batch()` processes all pending records, then: (a) the exception is caught and logged as an error, (b) that record's status is NOT updated (enabling retry on the next drain invocation), (c) processing continues for remaining records in the pending list.
- [ ] **[DRAIN-8]** Given a pending record where `submitted_at` is more than 80% of `cfg.batch_completion_window` ago and `status` is still in `{"submitted", "polling"}`, when `drain_batch()` processes it, then a `WARNING` log entry is emitted indicating impending job expiry. (The 80% threshold is derived from the parsed `batch_completion_window` — e.g., 19.2 hours for the default `"24h"`, 134.4 hours for `"7d"`.)
- [ ] **[DRAIN-9]** `electric-blue --drain-batch` is a CLI flag that imports and calls `drain_batch(cfg)`, then returns. It does not require a watcher process to be running and is safe to invoke from cron.
- [ ] **[DRAIN-10]** Given `drain_batch()` is called when `cfg.batch_inbox_dir` is `None` (batch not configured), then it returns immediately without error (defensive guard; cron may call it unconditionally).

### US-08 — Completion hook

- [ ] **[HOOK-1]** Given a batch job completes successfully during drain, when `_fire_completion_hook(cfg, record, info)` is called, then `notify(cfg, payload)` is called with a two-argument `dict` payload (DDR-04 `notify()` signature) that includes at minimum: `"schema_version": 1`, `"file": record.src_name`, `"job_id": record.job_id`, `"backend": info.backend`, and `"status"` indicating batch completion.
- [ ] **[HOOK-2]** Given `notify()` or `_fire_completion_hook()` raises any exception, when `drain_batch()` processes the job, then the exception is caught and logged at `WARNING` level, and drain continues normally. The completion hook is best-effort and non-blocking (consistent with DDR-04's never-raises contract).
- [ ] **[HOOK-3]** Given `cfg.notify_webhook=""`, when `_fire_completion_hook()` is called, then `requests.post` is never invoked (DDR-04 `notify()` no-op behavior inherited; no new network calls introduced by the hook).

### US-09 — Failure and expiry handling

- [ ] **[FAIL-1]** Given `poll()` returns `raw="failed"`, when `drain_batch()` handles the job, then the staged source is moved to `cfg.failed_dir`, `store.update(status="failed", error=<non-None>)` is called, and `stager.unstage(record.staged_url)` is called.
- [ ] **[FAIL-2]** Given `poll()` returns `raw="expired"`, when `drain_batch()` handles the job, then the staged source is moved to `cfg.failed_dir`, `store.update(status="expired", error=<non-None>)` is called, and `stager.unstage(record.staged_url)` is called.
- [ ] **[FAIL-3]** Given the staged file does not exist at `record.staged_path` when `drain_batch()` tries to move it to `failed_dir` (e.g. manual operator deletion), then a `WARNING` is logged and drain continues normally (no crash; the pipeline is not responsible for externally-deleted staged files).
- [ ] **[FAIL-4]** Given `stager.unstage(url)` raises any exception during drain (failed or completed path), then the exception is caught, logged at `WARNING`, and drain continues. (Stale staged files are an acceptable operator-visible artifact; pipeline correctness is not affected.)

### cli.py — pre-existing `--file` fix (architecture §14)

- [ ] **[CLI-1]** Given `sys.argv` contains `--file <path>`, when `main()` is invoked, then `process(cfg, Path(args.file), datetime.now(timezone.utc))` is called with all three required arguments and completes without `TypeError`. (Fixes the pre-existing crash: the prior call `process(cfg, Path(args.file))` was missing the required `started_at` argument added by DDR-04. Fix ratified by orchestrator per architecture §14.)

---

## Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| `batch_inbox_dir` is `None` | Batch path entirely inactive; no observer registered; `drain_batch()` returns immediately (DRAIN-10) |
| `batch_inbox_dir` set but `batch_funnel_base_url` empty | `ensure_batch_dirs()` raises `RuntimeError` at startup; watcher process aborts (CFG-10, primary B1 guard) |
| File suffix not in `cfg.media_exts` dropped in `batch_inbox_dir` | `handle_batch()` returns without action; file remains in `batch_inbox_dir` |
| File not yet stable (`is_stable()` returns False) | `handle_batch()` returns; watchdog `on_created` / `on_moved` will fire again |
| Encoded MP3 exceeds `cfg.batch_max_mb` | `submit()` raises before any `requests.post`; file moves to `failed_dir` (ASYNC-11) |
| `cfg.batch_api_key=""` (D10 fallback exhausted) | `submit()` raises `RuntimeError` before any network call (INV-2 fail-loud) |
| `stager.stage()` raises | No store record written; file moves to `failed_dir` (STAG-6) |
| JSONL file upload to Groq fails (HTTP error) | `submit()` raises; no store record written; file moves to `failed_dir` |
| Batch create POST fails | `submit()` raises; JSONL file was uploaded but batch not created (known accepted partial state); file moves to `failed_dir` |
| Groq poll returns unrecognized status string | `poll()` returns `terminal=False` (conservative); drain retries next cycle (ASYNC-12) |
| Groq poll returns `"validating"` | `poll()` returns `terminal=False`; drain retries (ASYNC-12) |
| `fetch()` fails on `output_file_id` download | Exception propagates to drain's outer `except`; record status unchanged; logged as error; retried next drain |
| `write_outputs()` fails mid-write (e.g. disk full) | Exception propagates to drain's outer `except`; record status unchanged; logged; retried next drain |
| `staged.exists()` is `False` at drain success path | No `shutil.move`; `store.update(completed)` proceeds; `stager.unstage()` still called |
| Concurrent `--drain-batch` invocations | Per-job sidecar files are independent; no cross-job corruption; simultaneously updating the same job's sidecar is explicitly unsupported (documented) |
| `batch_completion_window="7d"` set | Value passed verbatim to Groq batch create body; Funnel URL must remain live for up to 7 days (operator responsibility); expiry warning at 134.4 hours (80% of window) |
| `cfg.language=None` | No `language` field in JSONL body (consistent with `api.py`) |
| `cfg.language="fr"` | `"language": "fr"` included in JSONL body |
| `batch_store_path` directory does not exist at startup | `ensure_batch_dirs()` creates it alongside `batch_inbox_dir` and `batch_submitted_dir` |
| Re-drop of a previously failed file | `find_by_src_name()` returns terminal record; live-guard passes; new `JobRecord` with new `job_id` created (A4, D5) |
| Same source stem submitted twice (e.g. `meeting.mp4` then re-drop) | Each submission stages `meeting.mp3`; second stage overwrites first in `batch_stage_dir` (acceptable: first job already used the URL; operator re-drop is post-terminal) |

---

## Out of Scope

- **NOT:** Live Groq Batch API calls in the hermetic gate (`make gate`). No paid Groq key
  exists; all HTTP in gate tests is mocked (`responses` or `unittest.mock`). Live smoke is deferred
  until a key is provisioned (INV-8).
- **NOT:** Minted-URL stager (Cloudflare R2, Backblaze B2 pre-signed URLs). Deferred as a future
  `UrlStager` implementation. The abstraction is built; the second implementation is not.
- **NOT:** Groq-side file cleanup (JSONL upload, output file deletion via Files API). Deferred
  pending D9 (Groq file retention policy) verification.
- **NOT:** Batch job aggregation (many audio files in one JSONL / one batch object). Deferred by
  D4. One audio file per batch object throughout this sprint.
- **NOT:** Automatic re-submission on failure. D5 requires fail-loud and operator re-drop.
- **NOT:** A dedicated `batch_retry_dir` for intermediate operator review. D5 goes directly to
  `failed_dir`.
- **NOT:** Per-job `completion_window` override. One value per `Config` instance.
- **NOT:** Modifying `local.py`, `api.py`, `backends/__init__.py` (sync backends untouched).
- **NOT:** Modifying `watcher.handle()`, `watcher.run_once()`, `watcher.run_watch()` sync paths.
  Only additions (new functions, new observer branch) are permitted.
- **NOT:** Modifying `outputs.write_outputs()`, `models.py`, `audio.extract()`, or `notify.py`
  (called unchanged; DDR §10 confirmed).
- **NOT:** DDR-05 diarization features.
- **NOT:** Any user-facing UI, interactive prompts, or HTTP server implementation. Tailscale Funnel
  configuration (cert provisioning, `funnel` ACL attribute) is a one-time operator step, not a
  code requirement.
- **NOT:** Configuring the cron schedule. Cron setup is an operator responsibility; this sprint
  delivers the `--drain-batch` target.
- **Deferred:** Per-audio-file Groq batch size cap verification (D8). `batch_max_mb=25` is a
  placeholder; the true cap is VERIFY-at-sprint.
- **Deferred:** Exact Groq Batch API endpoint field names and JSONL output schema (D7). Both must
  be verified against live Groq docs before the smoke test; the hermetic gate uses mocked responses.

---

## Constraints

**Process-restart / no-data-loss boundary (INV-1 extended)**

- **Must:** Every state transition is written to the sidecar JSON store BEFORE the corresponding
  filesystem or network action. `store.save(record)` before `shutil.move(to batch_submitted_dir)`;
  `store.update(completed)` after `shutil.move(to done_dir)` (so a crash before the update leaves
  the record retryable).
- **Must:** Every input file terminates in exactly one of `done_dir` or `failed_dir`. No code path
  in the batch submission or drain path deletes or unlinks an input file without moving it to one of
  these destinations.
- **Must:** `drain_batch()` is idempotent. Running it twice on the same pending job set produces the
  same outputs and final state as running it once.

**Security (INV-7)**

- **Must not:** `cfg.batch_api_key` appear in any log record, transcript, output JSON, or
  serialized payload at any log level.
- **Must not:** Any absolute filesystem path from the server appear in a Groq API request body,
  the staged URL, or any webhook payload field. The staged URL contains only the filename component
  beneath the Funnel base URL.

**Hermeticity (INV-8)**

- **Must:** All gate tests (`pytest -m "not smoke"`) make zero live network calls to Groq (or
  any external host). All HTTP is mocked. Gate passes with no `GROQ_BATCH_API_KEY` or
  `WHISPER_API_KEY` in the environment.
- **Must:** Only `@pytest.mark.smoke` tests may attempt live network or real key access.

**Behavior preservation (INV-3)**

- **Must:** Characterization tests (CHAR-1 through CHAR-4) are committed and green before any
  source change to `watcher.py`, `backends/base.py`, or `config.py`.
- **Must not:** Any existing test in the suite go red as a side effect of this sprint's additions.

**Sync-path isolation**

- **Must not:** `handle()`, `run_once()`, or `run_watch()`'s sync observer behavior change in any
  way. Batch activation is governed solely by `cfg.batch_inbox_dir is not None`.
- **Must not:** `local.py` or `api.py` be modified. `backends/__init__.py`'s `_REGISTRY` and
  `transcribe()` dispatcher are unchanged unless `GroqBatchBackend` registration requires an entry
  (A6; architect decision).

**UrlStager abstraction (DDR hard architectural requirement)**

- **Must:** URL staging be behind the `UrlStager` Protocol. No direct Tailscale-specific call
  appears in `GroqBatchBackend` or `drain_batch`. Swapping `FunnelStager` for a future R2/B2
  stager must require only a `UrlStager` implementation and a config change.

**Process-restart compliance**

- **Must:** A fresh process with only `cfg.batch_store_path` available can call `make_store(cfg)`,
  `list_pending()`, and operate on any previously-saved record. No in-memory state is required
  between submission and drain.

**Assumes:**

- DDR-04 completion-webhook is merged to `main` at sprint start (confirmed: `fe7c7a2`). `notify()`,
  `build_done_payload()`, and `build_failed_payload()` from `notify.py` are available with their
  DDR-04 two-argument signatures.
- DDR-02 backend seam is merged to `main` at sprint start (confirmed: `870d00e`). `Capabilities`,
  `Backend` Protocol, and `_REGISTRY` are in place.
- `requests` is available as a runtime dependency (already used by `api.py`). No new runtime dep
  is introduced by this sprint (D1 sidecar JSON uses stdlib only).
- The `Config` frozen dataclass pattern from DDR-01 is unchanged; new fields are appended; no
  existing field is removed or type-changed.
- Exactly when Groq fetches the staged URL within the 24h window is unconfirmed (DDR open item).
  The design conservatively assumes the URL must remain reachable for the full `completion_window`.
- D7 (exact Groq JSONL schema) and D8 (audio file size cap in batch context) remain VERIFY items
  to be confirmed against live Groq docs during the sprint, before the smoke test. Gate tests use
  mocked schemas consistent with the DDR description.

---

## DDR Decision Coverage Map

| DDR Decision | Addressed by |
|---|---|
| D1 sidecar JSON | STORE-1 through STORE-8; Constraints (process-restart) |
| D2 CLI + cron | DRAIN-9, DRAIN-10; CLI-1 (--file fix co-located in cli.py) |
| D3 separate top-level dir | CFG-1, CFG-2; SUBMIT-2 |
| D4 one file per batch object | ASYNC-3 (one JSONL line per submit call) |
| D5 fail → failed_dir, operator re-drop | FAIL-1, FAIL-2; SUBMIT-4 (re-drop allowed) |
| D6 URL-only input | ASYNC-3 (body.url, no body.file); STAG-4; STAG-7 (stem-named URL) |
| D10 GROQ_BATCH_API_KEY fallback | CFG-3, CFG-4 |
| Staging abstraction | STAG-1 through STAG-7; Constraints (UrlStager) |
| completion_window | CFG-6; ASYNC-3(e); DRAIN-8 (80% threshold scales with window) |
| INV-1 no data loss | SUBMIT-1 (store-before-move), SUBMIT-6/SUBMIT-8 (staged_path = destination), DRAIN-3 (fetch-before-update), DRAIN-6 (crash recovery), CHAR-1/2 |
| INV-2 fail loud | ASYNC-9 (no key), ASYNC-11 (size cap), SUBMIT-5 (submit failure), CFG-10 (startup guard) |
| INV-3 behavior preserved | CHAR-1 through CHAR-4; Constraints |
| INV-7 no secret leak | CFG-9; Constraints; STAG-2 (no path in URL); STAG-7 (stem-only URL) |
| INV-8 hermetic gate | Constraints; Out of Scope (no live Groq in gate) |
| INV-9 DDR decisions locked | All ACs ground decisions back to D1–D10 + Sprint Decisions |
| B1 funnel-URL guard | CFG-10 (ensure_batch_dirs raises at startup — primary guard); in-try construction is defense-in-depth with no dedicated AC — failed-dir routing on raise covered by SUBMIT-5 |
| B2 staged_path = destination | SUBMIT-6 (reworded), SUBMIT-8 (dedicated AC) |
| B3 stem-named MP3 / unique URL | STAG-7; ASYNC-3(c) (custom_id + URL per stem) |
| --file crash fix | CLI-1 |
| Unknown poll status | ASYNC-12 |
| Size-cap guard | ASYNC-11 |
