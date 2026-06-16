# Architecture: groq-batch

- **Status:** DRAFT
- **Author:** reed
- **Date:** 2026-06-16
- **Requirements:** 01-REQUIREMENTS.md
- **DDR:** DDR-03-groq-batch-backend.md (ACCEPTED 2026-06-16)
- **Sprint:** groq-batch-backend (GitHub issue #15)

---

## Summary

This document translates DDR-03 Sprint Decisions, the 01-REQUIREMENTS, and the six flagged
assumptions (A1–A6) into a concrete technical design grounded in the current codebase. It
specifies every module, type signature, state machine, INV-1 ordering guarantee, and test
seam required for implementation.

All six flagged assumptions are resolved explicitly in section 1 before any design detail is
given. Every owned change to existing files is named (INV-3). The sync path (`handle()`,
`run_once()`, `run_watch()`, `local.py`, `api.py`, `backends/__init__.py`) is not touched
except for two targeted single-line edits (A5) called out in section 14.

One pre-existing bug in `cli.py` (`--file` mode passes two arguments to `process()` which
requires three) is fixed in this sprint — see §4 cli.py addition and §14.

---

## 1. Flagged Assumption Resolutions (A1–A6)

### A1 — `staged_url` replaces `audio_file_id` in JobRef and JobRecord

**Decision:** Confirmed. Both `JobRef.audio_file_id` and `JobRecord.audio_file_id` are
removed. Both types gain `staged_url: str` carrying the public HTTPS URL returned by
`stager.stage()`.

**Rationale:** D6 (Sprint Decisions) is explicit: no Groq-side audio file upload occurs.
The JSONL body carries `"url": "<staged_url>"`; there is no Groq file ID for the audio. The
field name `audio_file_id` would be misleading and wrong. `staged_url` accurately names what
it carries. This correction propagates through `batch_groq.py`, `batch_store.py`, `watcher.py`,
and `drain.py`. DDR §4 body text is superseded by the Sprint Decision on this point.

### A2 — `batch_completion_window` Config field

**Decision:** Add `batch_completion_window: str` to `Config`, env var
`TRANSCRIBE_BATCH_COMPLETION_WINDOW`, default `"24h"`.

**Rationale:** Sprint Decisions mandate configurable `completion_window`. The field is a
string passed verbatim to Groq's `"completion_window"` key; no format validation is done in
Config (Groq rejects bad values at API call time). Accepted values per Groq docs: `"24h"`
through `"7d"`. Naming follows the `batch_` prefix convention used for all new batch fields.

### A3 — FunnelStager Config fields

**Decision:** Two new Config fields:

| Field | Type | Env var | Default |
|-------|------|---------|---------|
| `batch_stage_dir` | `Path` | `TRANSCRIBE_BATCH_STAGE_DIR` | `<base>/batch_stage` |
| `batch_funnel_base_url` | `str` | `TRANSCRIBE_BATCH_FUNNEL_URL` | `""` |

**Rationale:** `batch_stage_dir` is the filesystem directory that Tailscale Funnel serves
(the operator configures Funnel to serve this path). `batch_funnel_base_url` is the public
HTTPS base URL including any path prefix (e.g. `"https://myhost.ts.net/stage"`). An empty
`batch_funnel_base_url` means Funnel is not configured; `ensure_batch_dirs()` raises
`RuntimeError` at startup (primary guard — see §4 and §7), and `make_stager()` raises
`RuntimeError` as defense-in-depth (INV-2). These two fields are sufficient for
`FunnelStager` to implement `stage()` (copy + return URL) and `unstage()` (delete by
filename). The `batch_stage_dir` default of `<base>/batch_stage` follows the existing
pattern of `<base>/batch_store` and `<base>/batch_submitted`. Both directories are created by
`ensure_batch_dirs()` at startup.

### A4 — Duplicate-submission guard is live-record-only

**Decision:** `find_by_src_name()` on the `BatchStore` protocol returns any record with
the matching `src_name` (no internal status filter). The caller (`handle_batch()`) checks
whether the returned record's `status` is in `{"submitted", "polling"}`. Only a live record
blocks re-submission. A terminal record (`status in {"completed", "failed", "expired",
"cancelled"}`) allows re-submission (new `JobRecord` with new `job_id`).

**Rationale:** DDR §6 shows `find_by_src_name() is not None → skip`, which incorrectly
blocks operator re-drops (D5). Placing the status check in `handle_batch()` keeps the store
protocol simple (one method, one record returned) while satisfying D5. STORE-5 is unambiguous:
`find_by_src_name()` returns any matching record or `None`. The live-record semantics live in
`handle_batch()`, not in the store.

### A5 — `is_async: bool = False` added to Capabilities

**Decision:** Add `is_async: bool = False` as the last field of `Capabilities` in
`backends/base.py`. Because it has a default, existing positional and keyword `Capabilities()`
calls in `local.py` and `api.py` continue to resolve without modification. However, both are
updated to explicitly pass `is_async=False` in the same commit that adds the field.

**Rationale:** Making the intent explicit in all three files (base.py, local.py, api.py) is
required per A5. A characterization test (CHAR-4) must be committed and green against the
pre-change code before any source change to `base.py`. CHAR-4 pins `LocalBackend.capabilities`
and `ApiBackend.capabilities` field values. After `is_async=False` is added and both backends
updated, CHAR-4 remains green (it does not assert the absence of `is_async`; it only asserts
existing field values). This is an owned change to `backends/base.py`, `backends/local.py`,
and `backends/api.py`, named as such in the PR (INV-3).

### A6 — `GroqBatchBackend` is instantiated directly; not in `_REGISTRY`

**Decision:** `GroqBatchBackend` is NOT registered in `_REGISTRY` in `backends/__init__.py`.
It is instantiated directly by `handle_batch()` and `drain_batch()`. `backends/__init__.py`
is untouched. If `WHISPER_BACKEND=batch` is set, `get_backend()` raises
`RuntimeError("Unknown backend 'batch'...")` — correct INV-2 behavior.

**Rationale:** The `_REGISTRY` and `transcribe()` dispatcher are exclusively for sync
`Backend` Protocol implementors. Registering an `AsyncBackend` there creates an accidental path
where the sync dispatcher calls `transcribe()` on an object that implements only
`submit/poll/fetch` — a confusing `AttributeError` at runtime. The clean separation is:
`_REGISTRY` + `transcribe()` = sync path; direct construction + `handle_batch()`/`drain_batch()` =
async path. This matches INV-11's intent ("dispatch via Protocol + registry" for sync backends)
without conflating two orthogonal dispatch surfaces. No modification to `backends/__init__.py`
is needed or made.

---

## 2. Components

| Component | Responsibility | Location |
|-----------|----------------|----------|
| `Capabilities` (addition) | Gains `is_async: bool = False` field | `backends/base.py` |
| `AsyncBackend` | Protocol: `submit / poll / fetch` typed seam for async transcription | `backends/batch_groq.py` |
| `GroqBatchBackend` | Concrete `AsyncBackend`: encode → stage → JSONL upload → batch create → poll → fetch; holds `UrlStager` | `backends/batch_groq.py` |
| `UrlStager` | Protocol: `stage(path) -> url`, `unstage(url) -> None` | `staging.py` |
| `FunnelStager` | `UrlStager` impl: copy MP3 to `batch_stage_dir`; return Funnel URL; delete on unstage | `staging.py` |
| `make_stager` | Factory: constructs `FunnelStager` from `cfg`; callers never import `FunnelStager` directly | `staging.py` |
| `JobRef` | Typed return value of `submit()`; carries `job_id`, `jsonl_file_id`, `staged_url`, optional `output_file_id` | `batch_store.py` |
| `JobStatus` | Typed return value of `poll()`; terminal/success flags + `output_file_id` | `batch_store.py` |
| `JobRecord` | Persisted state; all fields JSON-serializable; `staged_url` replaces `audio_file_id` (A1) | `batch_store.py` |
| `BatchStore` | Protocol for state store operations | `batch_store.py` |
| `SidecarBatchStore` | D1 implementation: one `<job_id>.json` sidecar per record in `batch_store_path` dir | `batch_store.py` |
| `make_store` | Factory: returns `SidecarBatchStore(cfg.batch_store_path)`; callers never import concrete class | `batch_store.py` |
| `ensure_batch_dirs` | Create `batch_inbox_dir`, `batch_submitted_dir`, `batch_stage_dir`, `batch_store_path`; validate funnel URL at startup | `watcher.py` (addition) |
| `handle_batch` | Batch submission path: stability → live-record guard → submit → save → move; optional DI for backend/store | `watcher.py` (addition) |
| `_BatchHandler` | `FileSystemEventHandler` subclass; routes `on_created`/`on_moved` to `handle_batch` | `watcher.py` (addition) |
| `drain_batch` | Idempotent drain: poll all pending → fetch/move/notify on completion → move/log on failure; optional DI | `drain.py` |
| `_fire_completion_hook` | Best-effort: build batch-done payload, call `notify(cfg, payload)`; swallows all exceptions | `drain.py` |
| `Config` (additions) | 8 new frozen batch fields; `from_env()` updated | `config.py` |
| `cli.py` (additions) | `--drain-batch` flag; calls `drain_batch(cfg)` and returns. Also fixes pre-existing `--file` crash: passes `started_at` as third arg to `process()`. | `cli.py` |

---

## 3. Data Schemas

```python
# src/electric_blue/backends/base.py

@dataclass
class Capabilities:
    """Declarative capability record. Every Backend exposes one."""
    supports_diarization: bool
    max_upload_mb: int | None     # None = no cap (local); 24 = SI megabytes (api); None for batch (size-cap enforced internally via cfg.batch_max_mb)
    needs_network: bool
    needs_gpu_recommended: bool
    is_async: bool = False        # A5 OWNED ADDITION — False for local/api; True for GroqBatchBackend
```

```python
# src/electric_blue/batch_store.py

from dataclasses import dataclass, field

@dataclass
class JobRef:
    """Returned by submit(); passed to poll() and fetch()."""
    job_id: str                   # Groq batch object ID (e.g. "batch_abc123")
    jsonl_file_id: str            # Groq file ID of the uploaded JSONL
    staged_url: str               # Public HTTPS URL returned by stager.stage() — A1 (replaces audio_file_id)
    output_file_id: str | None = None
    # output_file_id is None at submit() time; set by drain before calling fetch()
    # after poll() returns JobStatus(succeeded=True, output_file_id="file_xyz")


@dataclass
class JobStatus:
    """Returned by poll()."""
    raw: str                      # Provider status string, unmodified (e.g. "in_progress", "completed")
    terminal: bool                # True if no further polling is needed
    succeeded: bool               # True if completed successfully (raw == "completed")
    output_file_id: str | None    # Present only when terminal=True and succeeded=True
    error: str | None             # Present for terminal failures


@dataclass
class JobRecord:
    """Persisted to the sidecar JSON store at submission; updated through drain.

    All fields are JSON-serializable without custom encoders (str, str|None).
    staged_url replaces audio_file_id from DDR §4 body (A1 — confirmed correction).
    """
    job_id: str                   # Groq batch ID — used as sidecar filename
    jsonl_file_id: str            # Groq file ID of the uploaded JSONL (for potential cleanup)
    staged_url: str               # Public HTTPS URL (A1) — passed to stager.unstage() at terminal
    src_name: str                 # Original filename (e.g. "meeting.mp4") — for done/failed move
    src_stem: str                 # Stem used for write_outputs (e.g. "meeting")
    staged_path: str              # Absolute path of original source file in batch_submitted_dir (DESTINATION)
    status: str                   # "submitted" | "polling" | "completed" | "failed" | "expired" | "cancelled"
    submitted_at: str             # ISO 8601 UTC, timespec="seconds"
    completed_at: str | None      # ISO 8601 UTC, set when status → "completed"
    error: str | None             # Error description for terminal-failure statuses
```

```python
# src/electric_blue/staging.py

from typing import Protocol
from pathlib import Path

class UrlStager(Protocol):
    """Structural protocol for staging a local file to a public HTTPS URL.

    Implementors require no explicit inheritance — structural match suffices.
    FunnelStager is the first implementation.
    R2/B2 pre-signed URL is a future drop-in requiring only a new class
    and a Config change — no modification to GroqBatchBackend or drain_batch.
    """
    def stage(self, path: Path) -> str: ...
    """Copy path to the serve location; return the public HTTPS URL.
    The returned URL contains only the filename component, never an absolute fs path (INV-7).
    The path passed by submit() is always named f"{src.stem}.mp3" (B3 — see §5 and §8)."""

    def unstage(self, url: str) -> None: ...
    """Remove the staged file corresponding to url. Idempotent (second call does not raise)."""


class FunnelStager:
    """Tailscale Funnel implementation of UrlStager.

    stage_dir: filesystem directory served by Tailscale Funnel (cfg.batch_stage_dir)
    base_url:  public HTTPS base URL, no trailing slash (cfg.batch_funnel_base_url)
               e.g. "https://myhost.ts.net/stage"

    stage(path) copies path.name into stage_dir and returns f"{base_url}/{path.name}".
    Since submit() always passes a path named f"{src.stem}.mp3", the returned URL is
    f"{base_url}/{src.stem}.mp3" — unique per source file, avoiding filename collisions.
    unstage(url) derives the filename via url.rsplit('/', 1)[-1] and deletes stage_dir / filename.
    """
    def __init__(self, stage_dir: Path, base_url: str) -> None: ...
    def stage(self, path: Path) -> str: ...
    def unstage(self, url: str) -> None: ...


def make_stager(cfg: "Config") -> UrlStager:
    """Factory: construct FunnelStager from cfg. Raises RuntimeError if batch_funnel_base_url is empty."""
```

```python
# src/electric_blue/backends/batch_groq.py

from typing import Protocol
from pathlib import Path
from ..config import Config
from ..batch_store import JobRef, JobStatus
from ..backends.base import Capabilities, Transcript

class AsyncBackend(Protocol):
    """Structural protocol for asynchronous transcription backends.

    Implementors require no explicit inheritance — structural match suffices.
    Callers of the async path (handle_batch, drain_batch) use this type for injection points.
    """
    name: str
    capabilities: Capabilities

    def submit(self, cfg: Config, src: Path) -> JobRef: ...
    def poll(self, cfg: Config, job: JobRef) -> JobStatus: ...
    def fetch(self, cfg: Config, job: JobRef) -> Transcript: ...


class GroqBatchBackend:
    """Concrete AsyncBackend implementation.

    Constructor takes a UrlStager (dependency injection for testability).
    Production callers use make_groq_batch_backend(cfg) which constructs FunnelStager internally.
    Not registered in _REGISTRY; never dispatched via transcribe() (A6).
    """
    name: str = "batch"
    capabilities: Capabilities  # is_async=True, needs_network=True,
                                # max_upload_mb=None (guarded internally by cfg.batch_max_mb),
                                # needs_gpu_recommended=False, supports_diarization=False

    def __init__(self, stager: "UrlStager") -> None: ...
    def submit(self, cfg: Config, src: Path) -> JobRef: ...
    def poll(self, cfg: Config, job: JobRef) -> JobStatus: ...
    def fetch(self, cfg: Config, job: JobRef) -> Transcript: ...


def make_groq_batch_backend(cfg: "Config") -> GroqBatchBackend:
    """Factory: construct GroqBatchBackend with FunnelStager from cfg."""
```

```python
# src/electric_blue/batch_store.py (continued)

from typing import Protocol

class BatchStore(Protocol):
    """Structural protocol for the batch job state store."""
    def save(self, record: JobRecord) -> None: ...
    def get(self, job_id: str) -> JobRecord | None: ...
    def find_by_src_name(self, src_name: str) -> JobRecord | None: ...
    """Return any record with src_name == src_name, regardless of status.
    Caller is responsible for checking record.status (see A4)."""
    def list_pending(self) -> list[JobRecord]: ...
    """Return records where status in {"submitted", "polling"} only."""
    def update(self, job_id: str, **kwargs) -> None: ...
    """Update named fields on the record identified by job_id. Raises if job_id not found."""


class SidecarBatchStore:
    """D1 implementation: one <job_id>.json per record in store_path directory.

    file format: JSON object, all JobRecord fields. Written atomically via temp-file
    and os.replace() where available; on supported platforms this is O_CREAT|O_EXCL + rename.
    Zero new runtime dependencies — stdlib json + pathlib only.
    """
    def __init__(self, store_path: Path) -> None: ...


def make_store(cfg: "Config") -> BatchStore:
    """Factory: return SidecarBatchStore(cfg.batch_store_path). Create directory if needed."""
```

### Config additions schema

```python
# New fields appended to Config in config.py (8 total, all batch-related)

batch_inbox_dir: Path | None          # TRANSCRIBE_BATCH; None = batch disabled (D3)
batch_submitted_dir: Path             # TRANSCRIBE_BATCH_SUBMITTED; default <base>/batch_submitted
batch_store_path: Path                # TRANSCRIBE_BATCH_STORE; default <base>/batch_store (D1 dir)
batch_api_key: str                    # GROQ_BATCH_API_KEY then WHISPER_API_KEY fallback (D10)
batch_max_mb: int                     # TRANSCRIBE_BATCH_MAX_MB; default 25 (D8 VERIFY)
batch_completion_window: str          # TRANSCRIBE_BATCH_COMPLETION_WINDOW; default "24h" (A2)
batch_stage_dir: Path                 # TRANSCRIBE_BATCH_STAGE_DIR; default <base>/batch_stage (A3)
batch_funnel_base_url: str            # TRANSCRIBE_BATCH_FUNNEL_URL; default "" (A3)
```

### Batch completion webhook payload schema

```python
# Payload passed to notify(cfg, payload) by _fire_completion_hook()
{
    "schema_version": 1,       # int literal (INV-10)
    "event": "batch_done",
    "file": str,               # record.src_name — filename only, never absolute path (INV-7)
    "job_id": str,             # record.job_id
    "backend": str,            # info.backend, e.g. "batch:whisper-large-v3-turbo"
    "status": "batch_done",
    "duration_min": float,     # round(info.duration / 60, 1)
}
```

---

## 4. API Contracts

### `staging.py`

```python
from pathlib import Path
from typing import Protocol

class UrlStager(Protocol):
    def stage(self, path: Path) -> str: ...
    def unstage(self, url: str) -> None: ...

class FunnelStager:
    def __init__(self, stage_dir: Path, base_url: str) -> None: ...
    def stage(self, path: Path) -> str: ...
    def unstage(self, url: str) -> None: ...

def make_stager(cfg: Config) -> UrlStager: ...
```

### `batch_store.py`

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

@dataclass
class JobRef:
    job_id: str
    jsonl_file_id: str
    staged_url: str
    output_file_id: str | None = None

@dataclass
class JobStatus:
    raw: str
    terminal: bool
    succeeded: bool
    output_file_id: str | None
    error: str | None

@dataclass
class JobRecord:
    job_id: str
    jsonl_file_id: str
    staged_url: str
    src_name: str
    src_stem: str
    staged_path: str
    status: str
    submitted_at: str
    completed_at: str | None
    error: str | None

class BatchStore(Protocol):
    def save(self, record: JobRecord) -> None: ...
    def get(self, job_id: str) -> JobRecord | None: ...
    def find_by_src_name(self, src_name: str) -> JobRecord | None: ...
    def list_pending(self) -> list[JobRecord]: ...
    def update(self, job_id: str, **kwargs) -> None: ...

def make_store(cfg: Config) -> BatchStore: ...
```

### `backends/batch_groq.py`

```python
from pathlib import Path
from typing import Protocol

from ..batch_store import JobRef, JobStatus
from ..backends.base import Capabilities, Transcript
from ..config import Config
from ..staging import UrlStager

class AsyncBackend(Protocol):
    name: str
    capabilities: Capabilities
    def submit(self, cfg: Config, src: Path) -> JobRef: ...
    def poll(self, cfg: Config, job: JobRef) -> JobStatus: ...
    def fetch(self, cfg: Config, job: JobRef) -> Transcript: ...

class GroqBatchBackend:
    name: str = "batch"
    capabilities: Capabilities = Capabilities(
        supports_diarization=False,
        max_upload_mb=None,
        needs_network=True,
        needs_gpu_recommended=False,
        is_async=True,
    )
    def __init__(self, stager: UrlStager) -> None: ...
    def submit(self, cfg: Config, src: Path) -> JobRef: ...
    def poll(self, cfg: Config, job: JobRef) -> JobStatus: ...
    def fetch(self, cfg: Config, job: JobRef) -> Transcript: ...

def make_groq_batch_backend(cfg: Config) -> GroqBatchBackend: ...
```

### `watcher.py` additions

```python
def ensure_batch_dirs(cfg: Config) -> None:
    """Create batch_inbox_dir, batch_submitted_dir, batch_stage_dir, batch_store_path.
    Called only when cfg.batch_inbox_dir is not None.

    PRIMARY FUNNEL GUARD (B1): Raises RuntimeError if cfg.batch_funnel_base_url is empty
    when batch is enabled. This is the primary guard — the system fails loud at startup
    so no file is ever silently stranded in the inbox due to a missing Funnel URL.
    Any RuntimeError raised here propagates up through run_watch() and aborts the process.
    This is the intended behavior: misconfiguration must be discovered at boot, not at
    first file drop.
    """

def handle_batch(
    cfg: Config,
    path: Path,
    *,
    backend: "AsyncBackend | None" = None,
    store: "BatchStore | None" = None,
) -> None:
    """Batch submission path. Optional backend/store for hermetic test injection.

    Execution order (SUBMIT-1):
    1. suffix check + is_stable() — early return if not a media file or not stable
    2. find_by_src_name() + status check — skip if live record exists (A4)
    3. construct backend (INSIDE try block — defense-in-depth for B1; see also ensure_batch_dirs)
    4. backend.submit(cfg, path) — encode, stage, upload JSONL, create batch
    5. store.save(record) — BEFORE shutil.move (INV-1); staged_path is the DESTINATION
    6. shutil.move(path → cfg.batch_submitted_dir / path.name)
    On any exception in step 3–4: log error, shutil.move(path → cfg.failed_dir), no store write.

    Design note: ensure_batch_dirs() (called at startup in run_watch()) is the PRIMARY guard
    for an empty batch_funnel_base_url. Backend construction inside the try block is SECONDARY
    (defense-in-depth) — ensures any RuntimeError from make_groq_batch_backend/make_stager
    routes the file to failed_dir rather than escaping uncaught.
    """

# In run_watch() — addition after existing sync observer:
#   if cfg.batch_inbox_dir:
#       ensure_batch_dirs(cfg)   ← raises RuntimeError at startup if funnel URL is unset (primary guard)
#       obs.schedule(_BatchHandler(cfg), str(cfg.batch_inbox_dir), recursive=False)
```

### `drain.py`

```python
from datetime import datetime, timezone
from pathlib import Path

from .batch_store import JobRef, JobRecord, make_store
from .backends.batch_groq import AsyncBackend, make_groq_batch_backend
from .config import Config
from .models import TranscriptInfo
from .notify import notify
from .outputs import write_outputs
from .staging import UrlStager, make_stager

def drain_batch(
    cfg: Config,
    *,
    backend: "AsyncBackend | None" = None,
    stager: "UrlStager | None" = None,
) -> None:
    """Poll all pending batch jobs. Idempotent. Optional backend/stager for test injection.

    Returns immediately if cfg.batch_inbox_dir is None (DRAIN-10).
    Per-job exceptions are caught and logged; processing continues for remaining jobs (DRAIN-7).
    Stager and backend are constructed inside the per-job try block (defense-in-depth for B1):
    if make_stager raises RuntimeError (empty funnel URL), the exception is caught per-job,
    logged, and that job is skipped without aborting the entire drain.
    """

def _fire_completion_hook(
    cfg: Config,
    record: JobRecord,
    info: TranscriptInfo,
) -> None:
    """Best-effort completion notification. Swallows all exceptions (HOOK-2)."""

def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string with seconds precision."""
```

### `cli.py` additions

```python
# In main():
ap.add_argument(
    "--drain-batch",
    action="store_true",
    help="Poll pending Groq Batch jobs and retrieve completed ones. Safe to call from cron.",
)
# ...
if args.drain_batch:
    from .drain import drain_batch
    drain_batch(cfg)
    return

# --file fix (pre-existing crash: process() requires 3 args; cli.py was passing 2):
if args.file:
    from datetime import datetime, timezone
    process(cfg, Path(args.file), datetime.now(timezone.utc))
```

Note: `process(cfg, src, started_at)` has three required parameters as of DDR-04.
The pre-existing call `process(cfg, Path(args.file))` omits `started_at` and raises
`TypeError` at runtime. The fix supplies `datetime.now(timezone.utc)` as `started_at`,
matching the pattern used in `handle()` in `watcher.py`.

### `config.py` — `from_env()` additions

```python
batch_inbox_dir=Path(os.environ["TRANSCRIBE_BATCH"]) if os.environ.get("TRANSCRIBE_BATCH") else None,
batch_submitted_dir=Path(os.environ.get("TRANSCRIBE_BATCH_SUBMITTED", base_dir / "batch_submitted")),
batch_store_path=Path(os.environ.get("TRANSCRIBE_BATCH_STORE", base_dir / "batch_store")),
batch_api_key=(
    os.environ.get("GROQ_BATCH_API_KEY")
    or os.environ.get("WHISPER_API_KEY", "")
),
batch_max_mb=int(os.environ.get("TRANSCRIBE_BATCH_MAX_MB", "25")),
batch_completion_window=os.environ.get("TRANSCRIBE_BATCH_COMPLETION_WINDOW", "24h"),
batch_stage_dir=Path(os.environ.get("TRANSCRIBE_BATCH_STAGE_DIR", base_dir / "batch_stage")),
batch_funnel_base_url=os.environ.get("TRANSCRIBE_BATCH_FUNNEL_URL", ""),
```

---

## 5. Groq Batch API Lifecycle (corrected for URL-only input)

The steps below reflect the Sprint Decision correction: step 3a (audio file upload) is
removed. The flow within `GroqBatchBackend.submit()`:

```
submit(cfg, src):
  1. Guard: if not cfg.batch_api_key → RuntimeError (INV-2, ASYNC-9)
  2. Guard: if not cfg.batch_funnel_base_url → RuntimeError (INV-2, A3)
  3. encode: extract(cfg, src, mp3_tmp, compressed=True)
     mp3_tmp is a Path inside a TemporaryDirectory named f"{src.stem}.mp3"
     (e.g. src="meeting.mp4" → mp3_tmp.name="meeting.mp3").
     This ensures each staged file has a unique URL and avoids filename collisions
     in batch_stage_dir when multiple jobs are submitted (B3).
     [reuses audio.py path — 64k mono MP3, same as ApiBackend]
  4. size check: if mp3.stat().st_size / 1e6 > cfg.batch_max_mb → RuntimeError
  5. stage: staged_url = self.stager.stage(mp3_tmp)
     staged_url = f"{cfg.batch_funnel_base_url}/{src.stem}.mp3"
     (stager.stage raises → propagates to handle_batch's except; no store record (STAG-6))
  6. build JSONL line:
     {
       "custom_id": f"eb-{src.stem}",
       "method": "POST",
       "url": "/v1/audio/transcriptions",
       "body": {
         "url": staged_url,            # ← D6 correction; no "file" field
         "model": cfg.api_model,
         "response_format": "verbose_json",
         "timestamp_granularities": ["segment"],
         # "language": cfg.language if cfg.language else (omitted)
       }
     }
  7. upload JSONL:
     POST {cfg.api_base_url}/files
       Authorization: Bearer {cfg.batch_api_key}
       multipart: file=("requests.jsonl", jsonl_bytes, "application/jsonl"), purpose="batch"
     → {"id": "<jsonl_file_id>", ...}
  8. create batch:
     POST {cfg.api_base_url}/batches
       Authorization: Bearer {cfg.batch_api_key}
       JSON: {
         "input_file_id": jsonl_file_id,
         "endpoint": "/v1/audio/transcriptions",
         "completion_window": cfg.batch_completion_window
       }
     → {"id": "<batch_id>", "status": "validating", ...}
  9. return JobRef(job_id=batch_id, jsonl_file_id=jsonl_file_id, staged_url=staged_url)
     [mp3_tmp is in a TemporaryDirectory and is deleted when the context manager exits;
      the staged copy in batch_stage_dir persists until stager.unstage() is called]

poll(cfg, job):
  GET {cfg.api_base_url}/batches/{job.job_id}
    Authorization: Bearer {cfg.batch_api_key}
  → map status string:
    "completed"  → JobStatus(raw="completed", terminal=True, succeeded=True, output_file_id=..., error=None)
    "failed"     → JobStatus(raw="failed",    terminal=True, succeeded=False, output_file_id=None, error="...")
    "expired"    → JobStatus(raw="expired",   terminal=True, succeeded=False, output_file_id=None, error="expired")
    "cancelled"  → JobStatus(raw="cancelled", terminal=True, succeeded=False, output_file_id=None, error="cancelled")
    any other    → JobStatus(raw=status, terminal=False, succeeded=False, output_file_id=None, error=None)
    [unknown status → terminal=False (conservative; drain retries)]

fetch(cfg, job):
  # job.output_file_id must be set by caller (drain sets it from poll result)
  GET {cfg.api_base_url}/files/{job.output_file_id}/content
    Authorization: Bearer {cfg.batch_api_key}
  → JSONL; parse first line:
    response.body.segments → list[Segment] (same structure as api.py verbose_json parsing)
    fallback: if no segments and response.body.text → [Segment(0.0, duration, text)]
    info = TranscriptInfo(
      language=response.body.language or cfg.language or "unknown",
      language_probability=None,
      duration=round(float(response.body.duration or 0.0), 2),   # round to 2 dp, matching api.py
      backend=f"batch:{cfg.api_model}"
    )
  → Transcript(segments=segments, info=info)
```

All HTTP calls use `Authorization: Bearer {cfg.batch_api_key}`. The key never appears in
log output (INV-7, CFG-9).

---

## 6. State Machine — `JobRecord.status`

```
                    [handle_batch: submit() succeeds]
                              │
                       store.save(record)         ← INV-1: written BEFORE shutil.move
                       shutil.move(src → batch_submitted_dir)
                              │
                       ┌──────▼──────┐
                       │ "submitted" │  (initial state after successful submit)
                       └──────┬──────┘
                              │
                   [drain: poll() → terminal=False]
                              │
                       store.update(status="polling")
                              │
                       ┌──────▼──────┐
                       │  "polling"  │  (each non-terminal drain cycle)
                       └──────┬──────┘
                    ┌─────────┼──────────┐
                    │         │          │
              succeeded    failed/    poll() raises
                    │    expired/      (status UNCHANGED; logged; retried next drain)
                    │    cancelled
                    │         │
     [drain success path]   [drain failure path]
     fetch() → transcript    (no fetch)
     write_outputs()          shutil.move(staged_path → failed_dir)
     shutil.move(staged_path  [if staged.exists(); else log warning FAIL-3]
       → done_dir)
     [if staged.exists();     store.update(status=raw, error=...)
      else: no-op]
                              try: stager.unstage(staged_url)
     store.update(            except: log warning (FAIL-4)
       status="completed",
       completed_at=now)     log.error(...)
                    │         │
     try: stager.unstage(     │
       staged_url)            │
     except: log warning      │
                    │         │
     _fire_completion_hook()  │
                    │         │
              ┌─────▼──────┐ ┌▼──────────────┐
              │ "completed" │ │ "failed" /    │
              └─────────────┘ │ "expired" /   │
                              │ "cancelled"   │
                              └───────────────┘

Terminal states: "completed", "failed", "expired", "cancelled"
Live (pending) states: "submitted", "polling"
list_pending() returns only live states.
```

Sidecar filename: `<cfg.batch_store_path>/<job_id>.json`

---

## 7. INV-1 Ordering Guarantees

### Startup validation (primary B1 guard)

`ensure_batch_dirs(cfg)` is called by `run_watch()` when `cfg.batch_inbox_dir` is not None.
It raises `RuntimeError` immediately if `cfg.batch_funnel_base_url == ""`. This is the
PRIMARY guard: the process aborts at startup rather than silently accepting files it cannot
stage. No file ever enters `batch_inbox_dir` from the watcher's perspective without a valid
Funnel URL being confirmed.

### Submission path (handle_batch)

The only mandatory write-before-action ordering in the submission path:

```
store.save(record)        ← BEFORE
shutil.move(src → batch_submitted_dir)
```

`staged_path` is set to `str(cfg.batch_submitted_dir / path.name)` — this is the DESTINATION
path of the source file after the move. The record stores the destination unconditionally,
before `shutil.move` executes. If the move fails, `staged_path` points to the intended
location and the file remains at `batch_inbox_dir/name`. Recovery is operator-driven:
delete the sidecar file and re-drop the source file.

Crash between save and move: record exists with `status="submitted"`, source file still in
`batch_inbox_dir`. On next watcher event, `find_by_src_name()` returns the live record and
blocks re-submission. Drain will log an error for the `staged_path` missing. No data loss.

### Accepted partial state — submit() → store.save() window (M11)

There is a crash window between `submit()` returning success (Groq batch created, staged
MP3 in `batch_stage_dir`) and `store.save()` completing:

- **What exists:** an active Groq batch job + a staged MP3 in `batch_stage_dir`
- **What does not exist:** a sidecar record
- **Consequence:** no sidecar record means `find_by_src_name()` returns `None` on the next
  watcher event → the guard passes → the same source file is re-submitted → a second Groq
  batch job is created (double-submit risk). The original job is orphaned and costs credits.
  The source file is not lost (it is still in `batch_inbox_dir`).
- **Operator recovery:** Inspect `batch_stage_dir` for orphaned MP3 files; delete them
  manually and let normal re-submission proceed. The orphaned Groq job expires per
  `batch_completion_window` with no further cost beyond the original submission.
- **Design rationale:** this window is accepted as a low-probability / low-impact partial
  state. Its cost is bounded (one double-submission per crash in this window); it is not
  data loss; and adding a pre-save record with a synthetic "staging" status would complicate
  the guard logic significantly. Documented here for completeness alongside the
  submission-path and drain-path partial-state analyses.

### Drain success path

```
backend.fetch()                             ← idempotent (Groq output available until expiry)
write_outputs()                             ← idempotent (overwrite)
shutil.move(staged_path → done_dir)         ← guarded: if staged.exists()
store.update(status="completed")            ← AFTER move (so crash leaves record retryable)
stager.unstage(staged_url)                  ← best-effort; guarded by try/except
_fire_completion_hook()                     ← best-effort; never raises
```

Crash between move and store.update: record remains `"polling"` in `list_pending()`. Next
drain: re-poll (Groq returns "completed"), re-fetch (idempotent), re-write outputs (idempotent),
`staged.exists()` is False (no second move), update(completed) succeeds. DRAIN-6 satisfied.

### Drain failure path

```
shutil.move(staged_path → failed_dir)       ← guarded: if staged.exists() (FAIL-3)
store.update(status=raw, error=...)         ← AFTER move
stager.unstage(staged_url)                  ← best-effort; guarded by try/except (FAIL-4)
```

Crash between move and store.update: record remains "polling". Next drain: re-poll (returns
failed again), `staged.exists()` is False, update(failed) succeeds. No data loss; operator
sees the source file in `failed_dir`.

### Invariant check

```
grep -n "shutil.move" src/electric_blue/watcher.py src/electric_blue/drain.py
```

In `handle_batch`: `store.save()` must appear in the preceding line.
In drain success: `store.update(completed)` must appear after the `shutil.move` line.
In drain failure: `store.update(failed)` must appear after the `shutil.move` line.
These ordering checks are part of the PR review checklist.

---

## 8. FunnelStager Implementation Contract

`FunnelStager.stage(path: Path) -> str`:
- The `path` argument is always named `f"{src.stem}.mp3"` by callers (§5 step 3); this
  ensures the staged file URL is unique per source file (e.g. `meeting.mp3` for `meeting.mp4`,
  not `a.mp3`). Collisions in `batch_stage_dir` are prevented at the caller level.
- Copies `path` to `self.stage_dir / path.name` (shutil.copy2 to preserve timestamps)
- Returns `f"{self.base_url.rstrip('/')}/{path.name}"` — e.g. `https://myhost.ts.net/stage/meeting.mp3`
- The returned URL contains only the filename (`{src.stem}.mp3`), never any absolute filesystem path (INV-7)
- If `self.base_url` is empty string: raises `RuntimeError("TRANSCRIBE_BATCH_FUNNEL_URL is not set")`
- Raises `RuntimeError` if copy fails — propagates to handle_batch's except block (STAG-6)

`FunnelStager.unstage(url: str) -> None`:
- Derives filename: `url.rsplit("/", 1)[-1]`
- Deletes `self.stage_dir / filename` if it exists
- Silently returns if the file does not exist (idempotent — STAG-3)
- Does not raise on missing file; callers wrap in try/except anyway (FAIL-4)

`make_stager(cfg: Config) -> UrlStager`:
- Returns `FunnelStager(cfg.batch_stage_dir, cfg.batch_funnel_base_url)`
- If `cfg.batch_funnel_base_url == ""`: raises `RuntimeError` immediately (INV-2, A3)

Future drop-in: a `MintedUrlStager(bucket, prefix_url)` implementing `UrlStager` would
require: (a) a new `UrlStager` implementation, (b) new Config fields, (c) a change to
`make_stager()`. No modification to `GroqBatchBackend`, `handle_batch()`, or `drain_batch()`
is required. This satisfies the DDR hard requirement: "that future swap must not require
rearchitecting the backend or drain."

---

## 9. Duplicate-Submission Guard Detail (A4)

```python
# In handle_batch():
store = _store or make_store(cfg)
existing = store.find_by_src_name(path.name)
if existing is not None and existing.status in {"submitted", "polling"}:
    log.warning(
        "Batch: %s already has a live job (%s / %s), skipping",
        path.name, existing.job_id, existing.status,
    )
    return
# otherwise proceed: existing is None OR existing.status is terminal
```

`find_by_src_name()` returns the first record found with that `src_name`. For
`SidecarBatchStore`, this means scanning all sidecars. If multiple records exist for the same
name (e.g. from multiple failed/re-drop cycles), the scan returns the first live one found, or
any terminal one if none are live. The guard checks live-ness; a terminal record does not block.

---

## 10. SidecarBatchStore Implementation Contract

- **Directory**: `cfg.batch_store_path` (created by `make_store()` if absent)
- **File per record**: `{job_id}.json` — UTF-8 JSON object with all `JobRecord` fields
- **Write**: `json.dumps(dataclasses.asdict(record))` written atomically via
  `tmp_path.write_text(...); tmp_path.replace(final_path)` using a sibling temp file
- **list_pending()**: iterates `*.json` in `batch_store_path`; deserializes each; filters
  `status in {"submitted", "polling"}`; returns the filtered list
- **find_by_src_name(src_name)**: iterates `*.json`; returns first record where
  `record.src_name == src_name` or `None`
- **update(job_id, **kwargs)**: `get(job_id)` → patch fields → atomic write; raises
  `KeyError` if `job_id` not found
- **Cross-job isolation**: updating `job_id="A"` touches only `A.json`; `B.json` is
  not read or written (STORE-7)
- **Cold-start recovery**: `make_store(cfg)` on a new process with an existing
  `batch_store_path` reads whatever sidecars are present; no in-memory state required
  between sessions (STORE-6, DRAIN-10 defensive guard)

---

## 11. drain_batch() Annotated Flow

```python
def drain_batch(
    cfg: Config,
    *,
    backend: AsyncBackend | None = None,
    stager: UrlStager | None = None,
) -> None:
    if cfg.batch_inbox_dir is None:   # DRAIN-10: defensive guard
        return
    store = make_store(cfg)

    for record in store.list_pending():
        try:
            # B1 defense-in-depth: construct per-job inside try so any RuntimeError
            # (e.g. empty funnel URL) is caught by the per-job handler and logged,
            # rather than aborting the entire drain. Primary guard is ensure_batch_dirs().
            _stager = stager if stager is not None else make_stager(cfg)
            _backend = backend if backend is not None else GroqBatchBackend(_stager)

            # DRAIN-8: warn on approaching expiry
            _maybe_warn_expiry(record, cfg)

            job_ref = JobRef(
                job_id=record.job_id,
                jsonl_file_id=record.jsonl_file_id,
                staged_url=record.staged_url,
            )
            status = _backend.poll(cfg, job_ref)

            if not status.terminal:
                store.update(record.job_id, status="polling")  # DRAIN-2
                continue

            if status.succeeded:
                # Set output_file_id so fetch() can download results
                job_ref_for_fetch = dataclasses.replace(
                    job_ref, output_file_id=status.output_file_id
                )
                transcript = _backend.fetch(cfg, job_ref_for_fetch)

                output_stems = write_outputs(
                    cfg, cfg.output_dir, record.src_stem,
                    transcript.segments, transcript.info
                )

                staged = Path(record.staged_path)
                if staged.exists():                             # DRAIN-5 idempotent guard
                    shutil.move(str(staged), str(cfg.done_dir / record.src_name))

                store.update(
                    record.job_id,
                    status="completed",
                    completed_at=_now_iso(),
                )                                               # DRAIN-3(d): AFTER move

                try:                                            # STAG-5, FAIL-4
                    _stager.unstage(record.staged_url)
                except Exception as e:
                    log.warning("unstage failed for %s: %s", record.staged_url, e)

                _fire_completion_hook(cfg, record, transcript.info)  # DRAIN-3(e), HOOK-2

            else:
                # Terminal failure: failed / expired / cancelled
                staged = Path(record.staged_path)
                if staged.exists():                             # FAIL-3
                    shutil.move(str(staged), str(cfg.failed_dir / record.src_name))
                else:
                    log.warning(
                        "staged file missing for failed job %s: %s",
                        record.job_id, record.staged_path,
                    )

                store.update(
                    record.job_id,
                    status=status.raw,
                    error=status.error or f"batch job did not succeed: {status.raw}",
                )

                try:                                            # FAIL-4
                    _stager.unstage(record.staged_url)
                except Exception as e:
                    log.warning("unstage failed for %s: %s", record.staged_url, e)

                log.error(
                    "Batch job %s terminal failure: %s", record.job_id, status.raw
                )

        except Exception as e:                                  # DRAIN-7: per-job guard
            log.error("drain error for job %s: %s", record.job_id, e)
            # Status unchanged — retried on next drain invocation
```

`_maybe_warn_expiry(record, cfg)`: parses `cfg.batch_completion_window` to hours
(`"24h"` → 24.0, `"7d"` → 168.0; falls back to 24.0 if unparseable), then if
`record.submitted_at` is older than 80% of the parsed window and `record.status in
{"submitted", "polling"}`, emits `log.warning("Batch job %s approaching expiry", ...)` (DRAIN-8).
Example: default `"24h"` → warn after 19.2 hours; `"7d"` → warn after 134.4 hours.

---

## 12. handle_batch() Annotated Flow

```python
def handle_batch(
    cfg: Config,
    path: Path,
    *,
    backend: AsyncBackend | None = None,
    store: BatchStore | None = None,
) -> None:
    # SUBMIT-7: extension filter
    if path.suffix.lower() not in cfg.media_exts:
        return
    # SUBMIT-1(1): stability check
    if not is_stable(path, cfg.stability_seconds):
        return

    _store = store if store is not None else make_store(cfg)

    # SUBMIT-1(2): live-record guard (A4)
    existing = _store.find_by_src_name(path.name)
    if existing is not None and existing.status in {"submitted", "polling"}:
        log.warning(
            "Batch: %s already has a live job (%s / %s), skipping",
            path.name, existing.job_id, existing.status,
        )
        return

    try:
        # B1 defense-in-depth: construct inside try so any RuntimeError from
        # make_groq_batch_backend / make_stager routes the file to failed_dir.
        # Primary guard is ensure_batch_dirs() at startup.
        _backend = backend if backend is not None else make_groq_batch_backend(cfg)

        # SUBMIT-1(3): submit — encode, stage, upload JSONL, create batch
        job_ref = _backend.submit(cfg, path)

        # SUBMIT-1(4): save record BEFORE move (INV-1)
        record = JobRecord(
            job_id=job_ref.job_id,
            jsonl_file_id=job_ref.jsonl_file_id,
            staged_url=job_ref.staged_url,
            src_name=path.name,
            src_stem=path.stem,
            # staged_path is the DESTINATION; file moves here in the next step.
            # The record stores the destination unconditionally before the move executes.
            # If shutil.move fails, staged_path points to the intended location and the file
            # remains at batch_inbox_dir/name; recovery is operator-driven per §7.
            staged_path=str(cfg.batch_submitted_dir / path.name),
            status="submitted",
            submitted_at=_now_iso(),
            completed_at=None,
            error=None,
        )
        _store.save(record)

        # SUBMIT-1(5): move source file to batch_submitted_dir
        shutil.move(str(path), record.staged_path)
        log.info("Batch submitted: %s → job_id=%s", path.name, job_ref.job_id)

    except Exception as e:
        # SUBMIT-5: no store write; move to failed_dir
        log.error("Batch submit failed for %s: %s", path.name, e)
        shutil.move(str(path), str(cfg.failed_dir / path.name))
```

---

## 13. run_watch() Batch Observer Addition

```python
# Additions to run_watch() in watcher.py (sync observer logic UNCHANGED):

def run_watch(cfg: Config) -> None:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    class H(FileSystemEventHandler):          # UNCHANGED — sync handler
        def on_created(self, e):
            if not e.is_directory:
                handle(cfg, Path(e.src_path))
        def on_moved(self, e):
            if not e.is_directory:
                handle(cfg, Path(e.dest_path))

    class _BatchHandler(FileSystemEventHandler):   # NEW — batch handler
        def on_created(self, e):
            if not e.is_directory:
                handle_batch(cfg, Path(e.src_path))
        def on_moved(self, e):
            if not e.is_directory:
                handle_batch(cfg, Path(e.dest_path))

    run_once(cfg)   # UNCHANGED
    obs = Observer()
    obs.schedule(H(), str(cfg.input_dir), recursive=False)   # UNCHANGED
    if cfg.batch_inbox_dir:                                   # NEW — gated on config
        ensure_batch_dirs(cfg)   # raises RuntimeError if batch_funnel_base_url is empty (B1 primary guard)
        obs.schedule(_BatchHandler(), str(cfg.batch_inbox_dir), recursive=False)
    obs.start()
    log.info("Watching %s  backend=%s  (Ctrl-C to stop)", cfg.input_dir, cfg.backend)
    # ... rest unchanged
```

The sync observer for `cfg.input_dir` is scheduled unconditionally before the batch branch.
CHAR-3 confirms one observer when `batch_inbox_dir is None`.

---

## 14. Owned Changes to Existing Files (INV-3)

All changes below are named as owned changes in the PR description. Characterization tests
CHAR-1 through CHAR-5 must be committed and green against pre-change code before any of
these edits are made.

| File | Change type | Description |
|------|-------------|-------------|
| `backends/base.py` | Additive | Add `is_async: bool = False` as last field of `Capabilities`. Pre-change: field absent. Post-change: field exists with default False. |
| `backends/local.py` | Targeted | Add `is_async=False` explicitly to `Capabilities(...)` call in `LocalBackend.capabilities`. One line change. No behavior change; INV-3 owned edit. |
| `backends/api.py` | Targeted | Add `is_async=False` explicitly to `Capabilities(...)` call in `ApiBackend.capabilities`. One line change. No behavior change; INV-3 owned edit. |
| `config.py` | Additive | +8 dataclass fields + 8 `from_env()` lines. No existing field modified. Frozen dataclass constraint preserved (CFG-8). |
| `watcher.py` | Additive | New functions: `ensure_batch_dirs()`, `handle_batch()`, `_BatchHandler`. Addition to `run_watch()`: batch observer branch after sync observer. The sync `H`, `run_once()`, `handle()` code is untouched. |
| `cli.py` | Additive + fix | CHAR-5 must be green before this edit (pins `main()` dispatch — INV-3 process pin). (1) `--drain-batch` argument + `if args.drain_batch:` branch. `main()` branching order: `--drain-batch` is checked before `--file` and `--once`. (2) Fix pre-existing `--file` crash: add `from datetime import datetime, timezone` and pass `datetime.now(timezone.utc)` as the required third argument to `process()`. |

New files (no existing behavior affected):
- `src/electric_blue/staging.py`
- `src/electric_blue/batch_store.py`
- `src/electric_blue/backends/batch_groq.py`
- `src/electric_blue/drain.py`

---

## 15. Test Seams and Hermeticity (INV-8)

All gate tests (`pytest -m "not smoke"`) make zero live network calls and require no
`GROQ_BATCH_API_KEY` or Groq account.

### HTTP mock seam

All `requests.post` and `requests.get` calls in `GroqBatchBackend` use module-level
`import requests` in `batch_groq.py`. Mock target:

```python
monkeypatch.setattr("electric_blue.backends.batch_groq.requests.post", mock_post)
monkeypatch.setattr("electric_blue.backends.batch_groq.requests.get", mock_get)
```

Or use the `responses` library to register URL-specific mocks. Both approaches are
acceptable; the seam is the module-level import.

### Store seam

For drain and watcher tests that exercise flow logic, inject a `MockBatchStore`:

```python
class MockBatchStore:
    def __init__(self, records: list[JobRecord]):
        self._records = {r.job_id: r for r in records}

    def list_pending(self) -> list[JobRecord]:
        return [r for r in self._records.values() if r.status in {"submitted", "polling"}]

    def update(self, job_id: str, **kwargs) -> None:
        self._records[job_id] = dataclasses.replace(self._records[job_id], **kwargs)

    # ... etc.
```

For `BatchStore`-specific tests (STORE-*), use a real `SidecarBatchStore` with `tmp_path`:

```python
def test_store_save_and_get(tmp_path):
    cfg = dataclasses.replace(Config.from_env(), batch_store_path=tmp_path / "store")
    store = make_store(cfg)
    record = make_test_record()
    store.save(record)
    assert store.get(record.job_id) == record
```

### Stager seam

Inject a `unittest.mock.MagicMock(spec=FunnelStager)` or a simple stub:

```python
class StubStager:
    def __init__(self):
        self.staged: dict[str, str] = {}
        self.unstaged: list[str] = []
    def stage(self, path: Path) -> str:
        url = f"https://test.ts.net/stage/{path.name}"
        self.staged[url] = str(path)
        return url
    def unstage(self, url: str) -> None:
        self.unstaged.append(url)
```

Inject via `handle_batch(cfg, path, backend=mock_backend)` and
`drain_batch(cfg, backend=mock_backend, stager=stub_stager)`.

### Backend seam (for drain tests)

```python
class MockAsyncBackend:
    def __init__(self, poll_returns: JobStatus, fetch_returns: Transcript | None = None):
        self._poll_returns = poll_returns
        self._fetch_returns = fetch_returns
    def submit(self, cfg, src): raise NotImplementedError
    def poll(self, cfg, job): return self._poll_returns
    def fetch(self, cfg, job): return self._fetch_returns
```

### Char test file: `tests/test_char_batch.py`

Five characterization tests committed and green BEFORE any source change:

- **CHAR-1**: `handle()` success path → file in `done_dir`, `failed_dir` untouched.
  (Tests current `handle()` with a mock `process()`.)
- **CHAR-2**: `handle()` failure path → file in `failed_dir`, `done_dir` untouched.
  (Tests current `handle()` with `process()` raising.)
- **CHAR-3**: `batch_inbox_dir is None` → exactly one `obs.schedule()` call in `run_watch()`.
  (Monkeypatches `Observer`; asserts call count = 1.)
- **CHAR-4**: `LocalBackend.capabilities` and `ApiBackend.capabilities` exist with expected
  current values; no `AttributeError`; `supports_diarization`, `max_upload_mb`,
  `needs_network`, `needs_gpu_recommended` match pre-change values.
  (Does NOT assert the absence of `is_async` — so it remains green after A5 is applied.)
- **CHAR-5**: `main()` dispatch in `cli.py` pins `--once`/`--file`/default paths (mocks `process`; does NOT assert argument count) before S7 edits cli.py.
  Process pin per INV-3; not a numbered AC (does not affect the 67-AC tally).

---

## 16. Integration Points

| Existing component | How this sprint uses it |
|-------------------|------------------------|
| `audio.extract(cfg, src, mp3, compressed=True)` | Called inside `GroqBatchBackend.submit()` to produce the 64k MP3. The output path is named `f"{src.stem}.mp3"` within a TemporaryDirectory. Signature and behavior unchanged. |
| `outputs.write_outputs(cfg, cfg.output_dir, stem, segments, info)` | Called in drain success path. Signature, formats, and return type unchanged. All four formats written identically to sync path. |
| `notify.notify(cfg, payload)` | Called by `_fire_completion_hook()`. The DDR-04 two-argument signature `notify(cfg, dict)` is used. Never-raises contract inherited: `_fire_completion_hook` wraps in try/except for belt-and-suspenders (HOOK-2). Note: `notify._format_ntfy` has no `batch_done` branch — ntfy users receive the generic fallback title for this event. This is not a bug; adding a dedicated ntfy format for `batch_done` is a DDR-04 follow-up if desired. |
| `models.Segment`, `models.TranscriptInfo` | Instantiated in `GroqBatchBackend.fetch()` for parsing output JSONL. Identical to `api.py` parsing path. |
| `backends.base.Capabilities` | `GroqBatchBackend.capabilities` uses it with `is_async=True`. The `Transcript` dataclass from `base.py` is reused as fetch()'s return type. |
| `watcher.is_stable()` | Called in `handle_batch()` with `cfg.stability_seconds`. Unchanged. |
| `config.Config` | Extended with 8 new frozen fields. `from_env()` updated. All existing fields unchanged. |
| `backends/__init__.py._REGISTRY` | Untouched. `GroqBatchBackend` is not in `_REGISTRY` (A6). |

---

## 17. Patterns

| Pattern | Usage | Rationale |
|---------|-------|-----------|
| Structural protocols | `UrlStager`, `AsyncBackend`, `BatchStore` | No explicit inheritance; structural match; swap-in without modifying callers. Required for R2/B2 future stager. |
| Optional dependency injection | `handle_batch(*, backend=None, store=None)`, `drain_batch(*, backend=None, stager=None)` | Enables hermetic tests without monkeypatching globals. Production code uses factory defaults. |
| Factory functions over direct construction | `make_store()`, `make_stager()`, `make_groq_batch_backend()` | Callers never import concrete classes; swap implementations in one place. |
| Store-before-move (submission) | `store.save()` before `shutil.move()` in handle_batch | INV-1: crash-safe; submitted job always has a persisted record before source file is moved. |
| Move-before-update (drain terminal) | `shutil.move()` to done/failed before `store.update(completed/failed)` | INV-1 crash recovery: an update-incomplete state leaves the record retryable; idempotent on retry. |
| Per-job exception isolation | `try/except` wrapping each record iteration in drain_batch | DRAIN-7: one job's failure does not abort processing of remaining jobs. |
| Best-effort hook (never-raises) | `_fire_completion_hook` wraps `notify()` in try/except | Consistent with DDR-04 contract; notification failure never propagates into the drain pipeline. |
| Batch inbox activation gate | `if cfg.batch_inbox_dir is None: return` in all batch-specific code | Batch is entirely off by default; existing installs unaffected without any config change. |
| Module-level requests import | `batch_groq.py` imports `requests` at module top | Same pattern as `api.py`; allows clean mock at `electric_blue.backends.batch_groq.requests.post`. |
| Atomic sidecar write | Temp file + `os.replace()` for sidecar JSON | Avoids partial-write corruption; Python `Path.replace()` is atomic on POSIX. |

---

## 18. Dependencies

No new runtime dependencies. All batch infrastructure uses stdlib only (json, pathlib, dataclasses,
shutil, datetime, os) plus `requests` (already a core dep) for HTTP.

| Dependency | Version | Purpose |
|------------|---------|---------|
| `requests` | `>=2.28` (core dep) | HTTP calls to Groq Batch API in `batch_groq.py` |
| `json` | stdlib | JSONL line construction + sidecar serialization |
| `pathlib` | stdlib | All file/directory operations |
| `dataclasses` | stdlib | `JobRef`, `JobStatus`, `JobRecord`; `dataclasses.asdict()` for serialization; `dataclasses.replace()` for drain |
| `shutil` | stdlib | `shutil.copy2()` (FunnelStager), `shutil.move()` (handle_batch, drain) |
| `datetime` | stdlib | ISO 8601 timestamps for `submitted_at`, `completed_at`; `started_at` in cli.py `--file` fix |
| `os` | stdlib | `os.replace()` for atomic sidecar write |
| `tempfile` | stdlib | Temporary directory for MP3 encoding in `submit()` |

---

## 19. Module Layout

```
src/electric_blue/
    backends/
        base.py           — OWNED CHANGE: Capabilities gains is_async: bool = False
        local.py          — TARGETED EDIT: explicit is_async=False in Capabilities() (A5)
        api.py            — TARGETED EDIT: explicit is_async=False in Capabilities() (A5)
        __init__.py       — UNCHANGED
        batch_groq.py     — NEW: AsyncBackend Protocol, GroqBatchBackend, make_groq_batch_backend
    staging.py            — NEW: UrlStager Protocol, FunnelStager, make_stager
    batch_store.py        — NEW: JobRef, JobStatus, JobRecord, BatchStore Protocol,
                                 SidecarBatchStore, make_store
    drain.py              — NEW: drain_batch, _fire_completion_hook, _now_iso, _maybe_warn_expiry
    watcher.py            — OWNED ADDITIONS: ensure_batch_dirs, handle_batch, _BatchHandler,
                                 batch observer branch in run_watch()
    config.py             — OWNED ADDITIONS: 8 new batch fields in dataclass + from_env()
    cli.py                — OWNED ADDITIONS + FIX: --drain-batch flag; --file started_at fix

tests/
    test_char_batch.py    — NEW (written FIRST, before any source change): CHAR-1 through CHAR-5
    test_staging.py       — NEW: STAG-1 through STAG-7
    test_batch_store.py   — NEW: STORE-1 through STORE-8
    test_batch_groq.py    — NEW: ASYNC-1 through ASYNC-12 (all HTTP mocked); also STAG-4, STAG-7
    test_handle_batch.py  — NEW: SUBMIT-1 through SUBMIT-8; also STAG-6, DRAIN-9, CFG-10, CLI-1
    test_drain.py         — NEW: DRAIN-1..8, DRAIN-10, HOOK-1..3, FAIL-1..4 (DRAIN-9 in test_handle_batch.py — see 04 AC Coverage Ledger)
    test_config.py        — ADDITIVE: 8 new field assertions in test_defaults(); CFG-1 through CFG-10
```

Import graph for new modules:

```
watcher.py (additions)
  ├── staging.py         (make_stager, UrlStager)
  │     └── config.py
  ├── batch_store.py     (make_store, BatchStore, JobRecord, JobRef)
  │     └── config.py
  └── backends/batch_groq.py  (make_groq_batch_backend, AsyncBackend)
        ├── staging.py
        ├── batch_store.py    (JobRef, JobStatus)
        ├── backends/base.py  (Capabilities, Transcript)
        ├── audio.py          (extract)
        └── config.py

drain.py
  ├── batch_store.py
  ├── backends/batch_groq.py
  ├── staging.py
  ├── config.py
  ├── models.py               (TranscriptInfo)
  ├── notify.py               (notify)
  └── outputs.py              (write_outputs)
```

No import cycles. `batch_store.py` imports only `config.py` (for factory). `staging.py`
imports only `config.py`. `batch_groq.py` does not import `drain.py` or `watcher.py`.

---

## 20. Flags (Non-Blocking)

**FLAG-1 — D7 (Groq JSONL schema) and D8 (batch size cap) remain VERIFY**

All gate tests use mocked HTTP responses consistent with the schemas described in DDR §3f.
Before the smoke test, the exact field names and JSONL output structure must be verified
against live Groq Batch API docs. `batch_max_mb=25` is a placeholder pending D8
confirmation. The architecture accommodates any discovered corrections: field names are
local to `GroqBatchBackend.submit()` and `fetch()` — only those methods change.

**FLAG-2 — Concurrent drain invocations are unsupported**

If `--drain-batch` is invoked while a previous drain is still running (e.g. slow cron
schedule), both processes may write to the same sidecar simultaneously. Per-job sidecar
isolation limits damage to the specific job(s) being updated by both processes. This is
documented as unsupported; the fix (file locking on sidecar write) is deferred. Operators
should ensure drain cron interval exceeds typical drain runtime.

---

## Status

- Components defined: 18
- Schemas defined: 9 (Capabilities addition, JobRef, JobStatus, JobRecord, UrlStager, FunnelStager, AsyncBackend, BatchStore, batch completion webhook payload)
- Config fields added: 8
- Assumptions resolved: 6 (A1–A6)
- Owned changes to existing files: 6 (base.py, local.py, api.py, config.py, watcher.py, cli.py)
- New files: 4 (staging.py, batch_store.py, backends/batch_groq.py, drain.py)
- Flags: 2 (non-blocking)
- Status: COMPLETE
