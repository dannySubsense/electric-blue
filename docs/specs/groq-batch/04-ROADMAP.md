# Implementation Roadmap: groq-batch

- **Status:** DRAFT (post-review revision 2026-06-16)
- **Author:** reed
- **Date:** 2026-06-16
- **Requirements:** 01-REQUIREMENTS.md (67 ACs across 10 families)
- **Architecture:** 02-ARCHITECTURE.md (18 components, 9 schemas, A1–A6 resolved)
- **DDR:** DDR-03-groq-batch-backend.md (ACCEPTED 2026-06-16, Sprint Decisions authoritative)
- **Sprint:** groq-batch-backend (GitHub issue #15)

---

## Overview

Seven code slices (S1–S7) plus one process gate (S8). S1 is the char-tests-first slice: five
characterization tests committed and green against pre-change code before any source file is
touched (INV-3). Each subsequent slice ends gate-green before the next begins (CADENCE P3,
no partial slices).

The DDR's suggested build order (config+dirs → batch_store → backend lifecycle w/ mocked HTTP
→ drain → watcher wiring + CLI → integration) is followed. `drain.py` (S6) precedes
`watcher.py` additions (S7) because drain has no dependency on watcher; both depend on the
backend and store.

Gate command at every slice boundary:

```
PATH="$PWD/.venv/bin:$PATH" make gate
```

---

## Slice Summary

| Slice | Title | Key Deliverable | Gate Exit Condition |
|-------|-------|-----------------|---------------------|
| S1 | Characterization tests | Pin pre-change behavior | 5 CHAR tests green; zero prod files changed |
| S2 | Config additions + Capabilities | 8 new batch Config fields; is_async on Capabilities | CFG-1..9 green; CHAR-1..5 still green |
| S3 | BatchStore + data schemas | JobRef/JobStatus/JobRecord + SidecarBatchStore | STORE-1..8 green; all prior green |
| S4 | UrlStager + FunnelStager | staging.py Protocol + implementation | STAG-1..3 green; all prior green |
| S5 | AsyncBackend + GroqBatchBackend | batch_groq.py; mocked HTTP lifecycle | ASYNC-1..12 + STAG-4 + STAG-7 green; all prior green |
| S6 | drain_batch + completion hook | drain.py; idempotent drain + best-effort hook | DRAIN-1..8 + DRAIN-10 + HOOK-1..3 + FAIL-1..4 + STAG-5 green |
| S7 | handle_batch + watcher observer + CLI | watcher.py additions; --drain-batch flag; --file fix | SUBMIT-1..8 + STAG-6 + DRAIN-9 + CFG-10 + CLI-1 green; all prior green |
| S8 | Final gate + smoke + Frank BUILD gate | SHIP verdict | make gate green; smoke attested; Frank SHIP |

---

## Dependency Graph

```
S1 ─► S2 ─► S3 ─► S4 ─► S5 ─► S6 ─► S7 ─► S8
```

- **S1 → S2:** INV-3 requires char tests committed and green before any source change to
  `watcher.py`, `backends/base.py`, `config.py`, or `cli.py`.
- **S2 → S3:** `make_store(cfg)` factory references `cfg.batch_store_path` (new in S2); test
  fixtures use `dataclasses.replace(Config.from_env(), batch_store_path=tmp_path)`, which
  requires the field to exist.
- **S2 → S4:** `make_stager(cfg)` references `cfg.batch_stage_dir` and
  `cfg.batch_funnel_base_url` (new in S2).
- **S3 + S4 → S5:** `batch_groq.py` imports `JobRef`, `JobStatus` from `batch_store.py` and
  `UrlStager` from `staging.py`. Both must exist before S5.
- **S5 → S6:** `drain.py` imports `make_groq_batch_backend` and `AsyncBackend` from
  `batch_groq.py`.
- **S5 → S7:** `handle_batch()` in `watcher.py` calls `make_groq_batch_backend(cfg)`.
- **S6 → S7:** Logical; watcher is the last new production module. S7 also adds the CLI flag
  that calls `drain_batch()` — drain must exist.
- **S7 → S8:** All code complete before final process gate.

No circular dependencies. `batch_store.py` does not import from `batch_groq.py`, `drain.py`,
or `watcher.py`. `staging.py` does not import from `batch_groq.py`, `drain.py`, or
`watcher.py`.

---

## Behavior-Preservation Checkpoints

At every slice boundary touching an existing file, all CHAR tests must remain green:

| After slice | CHAR tests required green | Notes |
|-------------|--------------------------|-------|
| S1 | CHAR-1, CHAR-2, CHAR-3, CHAR-4, CHAR-5 | Baseline; no prod code changed |
| S2 | CHAR-1, CHAR-2, CHAR-3, CHAR-4, CHAR-5 | Config additions are additive; base.py gets is_async with default False; CHAR-4 explicitly does not assert the absence of is_async so it survives |
| S3 | CHAR-1, CHAR-2, CHAR-3, CHAR-4, CHAR-5 | New file only; no existing behavior touched |
| S4 | CHAR-1, CHAR-2, CHAR-3, CHAR-4, CHAR-5 | New file only |
| S5 | CHAR-1, CHAR-2, CHAR-3, CHAR-4, CHAR-5 | New file only |
| S6 | CHAR-1, CHAR-2, CHAR-3, CHAR-4, CHAR-5 | New file only; drain.py does not touch watcher.py |
| S7 | CHAR-1, CHAR-2, CHAR-3, CHAR-4, CHAR-5 | watcher.py additions are additive; sync observer branch and handle() are untouched; CHAR-3 confirms one observer when batch_inbox_dir is None; CHAR-5 pins cli.py dispatch before --drain-batch branch is inserted |

INV-1 compliance at S6 (drain success path): `shutil.move(staged → done_dir)` is strictly
before `store.update(completed)` — verified by the annotated flow in 02-ARCHITECTURE §11.
INV-1 at S7 (handle_batch): `store.save(record)` is strictly before `shutil.move(src →
batch_submitted_dir)` — verified by 02-ARCHITECTURE §12.

---

## Flags Incorporated

The following architecture flags are carried as notes in the relevant slices rather than
blocking deliverables:

**FLAG-1 — D7/D8 remain VERIFY**
Gate tests use mocked HTTP schemas consistent with 02-ARCHITECTURE §5. Before the live smoke,
the operator must verify exact Groq JSONL field names (D7) and the audio file size cap (D8)
against live Groq Batch API docs. These are pre-smoke steps, not slice gates.

**FLAG-2 — Concurrent drain invocations are unsupported**
Per-job sidecar files are independent so cross-job corruption is bounded, but simultaneous
`--drain-batch` invocations updating the same sidecar are explicitly unsupported. This is
documented in S6's implementation notes and in the Deferred Work section. File locking is a
future optimization.

Note: The pre-existing `--file` mode crash (formerly FLAG-1 in the pre-review roadmap) is
**now in scope** as CLI-1. The fix is delivered in S7. CHAR-5 (S1) pins the pre-fix dispatch
behavior before S7 edits cli.py.

---

## S1 — Characterization Tests

**Goal:** Commit five characterization tests green against the current (pre-change) code,
pinning the observable behaviors that this sprint touches. No production file is modified.

**Depends on:** nothing

**Files:**
- `tests/test_char_batch.py` — create (5 tests)

**Tests added (all must be green before S2 begins):**

- `test_char_handle_success` **(CHAR-1):** `handle(cfg, path)` with a mock `process()` that
  succeeds → file moved to `done_dir`; `failed_dir` untouched. Verifies current watcher
  success path. Marked `survives` in docstring (unchanged by this sprint).

- `test_char_handle_failure` **(CHAR-2):** `handle(cfg, path)` with `process()` raising
  `Exception` → file moved to `failed_dir`; `done_dir` untouched. Verifies current watcher
  failure path. Marked `survives` in docstring.

- `test_char_single_observer_when_no_batch` **(CHAR-3):** Verify that `run_watch(cfg)` with
  no batch field schedules exactly one observer (the sync `H` handler against `cfg.input_dir`).

  **Seam — two patches are required to prevent the test from hanging:**
  1. Replace the entire `Observer` class: `monkeypatch.setattr("watchdog.observers.Observer",
     FakeObserver)` where `FakeObserver` is a `MagicMock` or a hand-rolled stub whose
     `schedule`, `start`, `stop`, and `join` methods are no-ops that record calls. Because
     `run_watch` does `from watchdog.observers import Observer` at function entry, patching
     `watchdog.observers.Observer` is the correct target — the local name resolves from that
     module attribute at call time.
  2. Break the event loop: `monkeypatch.setattr(electric_blue.watcher.time, "sleep",
     Mock(side_effect=KeyboardInterrupt))` (add `from unittest.mock import Mock`; targeting the module-level `import time` in `watcher.py`,
     accessible as `electric_blue.watcher.time`). The first `sleep` call raises
     `KeyboardInterrupt`, driving `run_watch` into its `except` branch (`obs.stop()`) and
     returning normally. Patching only `Observer.schedule` leaves the `while True` loop alive
     and the test hangs indefinitely.
  - `cfg` must have `tmp_path`-based dirs (`input_dir`, `done_dir`, `failed_dir`) so
    `run_once(cfg)` — called at the start of `run_watch` — succeeds without error (it logs
    "Nothing in …" and returns).

  Assertions: the `FakeObserver` instance's `schedule` call count == 1; `start` was called;
  `stop` was called (driven by the `KeyboardInterrupt` path). Marked `survives` in docstring —
  after S2 adds `batch_inbox_dir=None` (default) and S7 adds the conditional observer branch,
  `None` still yields schedule count == 1.

- `test_char_capabilities_existing_fields` **(CHAR-4):** Access `LocalBackend.capabilities`
  and `ApiBackend.capabilities`. Assert no `AttributeError`. Assert existing fields match
  pre-change values: `supports_diarization`, `max_upload_mb`, `needs_network`,
  `needs_gpu_recommended`. Do **not** assert the absence of `is_async` — the test is
  written so it survives after S2 adds `is_async: bool = False`. Marked `survives`.

- `test_char_cli_dispatch` **(CHAR-5 / INV-3 pin for cli.py):** This test pins the current
  `cli.main()` dispatch behavior before S7 adds `--drain-batch` and fixes `--file`. INV-3
  requires a pre-change pin for any owned edit to runtime code; `cli.py` is an owned change
  in S7.

  Implementation: use `monkeypatch.setattr(sys, "argv", [...])` plus
  `monkeypatch.setattr("electric_blue.watcher.run_watch", mock_run_watch)` (and similarly for
  `run_once` and `process`) before the lazy imports inside `main()` bind them. Three sub-cases:
  - `sys.argv = ["electric-blue"]` → `run_watch(cfg)` called; `run_once`, `process` not called.
  - `sys.argv = ["electric-blue", "--once"]` → `run_once(cfg)` called; `run_watch`, `process` not called.
  - `sys.argv = ["electric-blue", "--file", "/tmp/x.mp4"]` → `process(cfg, Path("/tmp/x.mp4"))`
    called (two-arg, pre-fix call — do NOT assert argument count; assert function called with the path).

  Mock target for watcher functions: `monkeypatch.setattr("electric_blue.watcher.run_watch", ...)`.
  Since `main()` does `from .watcher import ..., run_watch` lazily inside the function body, patching
  the attribute on `electric_blue.watcher` is the correct interception point — the lazy import reads
  from the module object at call time.

  Marked `partially survives` in docstring: after S7, the `--drain-batch` case is added and
  the `--file` case changes to 3-arg; existing `--once` and default cases are unchanged and
  still green. (CHAR-5 does NOT assert that `--drain-batch` is absent, so it survives S7's addition.)

**Mock seam:** For CHAR-1 and CHAR-2, use `monkeypatch.setattr` targeting
`electric_blue.watcher.process` (or a mock backend). For CHAR-3, two patches are required:
replace `watchdog.observers.Observer` at the module where it is imported (patch
`watchdog.observers.Observer`) AND patch `electric_blue.watcher.time.sleep` to raise
`KeyboardInterrupt` on the first call to break the loop. No requests/network calls in any
CHAR test.

**Done when:**
- [ ] `tests/test_char_batch.py` created with all five tests
- [ ] `make gate` exits 0 with 5 new green tests
- [ ] Zero production source files modified

**ACs satisfied:** CHAR-1, CHAR-2, CHAR-3, CHAR-4
(CHAR-5 is an INV-3 process requirement, not a numbered AC in 01-REQUIREMENTS; it does not
appear in the AC coverage ledger but must be present and green before S2 begins.)

**Rollback:** delete `tests/test_char_batch.py` (no production code to revert).

---

## S2 — Config Additions + Capabilities is_async

**Goal:** Add 8 new frozen batch fields to `Config` and update `from_env()`; add
`is_async: bool = False` to `Capabilities` with explicit `is_async=False` in all three
existing backends. All CHAR tests remain green.

**Depends on:** S1 (INV-3: char tests committed and green before any source change)

**Files:**
- `src/electric_blue/config.py` — modify (additive: +8 fields in dataclass, +8 lines in `from_env()`)
- `src/electric_blue/backends/base.py` — modify (additive: `is_async: bool = False` as last field of `Capabilities`)
- `src/electric_blue/backends/local.py` — targeted edit (add `is_async=False` explicitly to `Capabilities(...)` in `LocalBackend.capabilities`)
- `src/electric_blue/backends/api.py` — targeted edit (add `is_async=False` explicitly to `Capabilities(...)` in `ApiBackend.capabilities`)
- `tests/test_config.py` — modify (additive: CFG-1..9 assertions)

**Config fields added (all 8 in order, appended to the frozen dataclass):**

```python
batch_inbox_dir: Path | None          # TRANSCRIBE_BATCH; None = batch disabled
batch_submitted_dir: Path             # TRANSCRIBE_BATCH_SUBMITTED; default <base>/batch_submitted
batch_store_path: Path                # TRANSCRIBE_BATCH_STORE; default <base>/batch_store
batch_api_key: str                    # GROQ_BATCH_API_KEY then WHISPER_API_KEY fallback (D10)
batch_max_mb: int                     # TRANSCRIBE_BATCH_MAX_MB; default 25
batch_completion_window: str          # TRANSCRIBE_BATCH_COMPLETION_WINDOW; default "24h"
batch_stage_dir: Path                 # TRANSCRIBE_BATCH_STAGE_DIR; default <base>/batch_stage
batch_funnel_base_url: str            # TRANSCRIBE_BATCH_FUNNEL_URL; default ""
```

**`from_env()` additions** (see 02-ARCHITECTURE §4 for exact expressions):
- `batch_api_key` uses `os.environ.get("GROQ_BATCH_API_KEY") or os.environ.get("WHISPER_API_KEY", "")` (D10)
- `batch_max_mb` coerced with `int(...)`
- All Path fields use `Path(...)`

**Capabilities change** (one-line addition to `backends/base.py`):
```python
is_async: bool = False   # A5 OWNED ADDITION — False for local/api; True for GroqBatchBackend
```

**Tests added in `tests/test_config.py`:**

- `test_defaults` extension **(CFG-1):** with no batch env vars, assert all 8 default values:
  `batch_inbox_dir is None`, `batch_submitted_dir == base / "batch_submitted"`,
  `batch_store_path == base / "batch_store"`, `batch_api_key == ""`, `batch_max_mb == 25`,
  `batch_completion_window == "24h"`, `batch_stage_dir == base / "batch_stage"`,
  `batch_funnel_base_url == ""`.

- **(CFG-2):** monkeypatch `TRANSCRIBE_BATCH="/tmp/bi"` → `cfg.batch_inbox_dir == Path("/tmp/bi")`.

- **(CFG-3):** both keys set → `cfg.batch_api_key` uses `GROQ_BATCH_API_KEY` value.

- **(CFG-4):** only `WHISPER_API_KEY` set → `cfg.batch_api_key` equals `WHISPER_API_KEY` value.

- **(CFG-5):** `TRANSCRIBE_BATCH_MAX_MB="50"` → `cfg.batch_max_mb == 50` and
  `isinstance(cfg.batch_max_mb, int) is True`.

- **(CFG-6):** `TRANSCRIBE_BATCH_COMPLETION_WINDOW="7d"` → `cfg.batch_completion_window == "7d"`.

- **(CFG-7):** All pre-existing `test_config.py` tests pass unchanged. No existing field
  removed or default changed.

- **(CFG-8):** Assigning to any new batch field after construction raises `FrozenInstanceError`
  or `AttributeError` (frozen dataclass contract; existing `test_config_is_frozen` may already
  cover this pattern — extend or note).

- **(CFG-9):** With `GROQ_BATCH_API_KEY="gk-secret"` set, call any code path that reads
  `cfg.batch_api_key` (at minimum `Config.from_env()`) with `caplog` enabled; assert
  `"gk-secret" not in caplog.text`. Cross-path verification (backend HTTP auth header never
  logged) is the responsibility of S5 and S6 tests — those tests use `caplog` and assert
  the key value does not appear.

**Note on CFG-10:** CFG-10 tests `ensure_batch_dirs()` raising `RuntimeError` when the Funnel
URL is empty. `ensure_batch_dirs` is implemented in S7 (`watcher.py` additions). CFG-10's
verifying test is therefore in S7, not here.

**Done when:**
- [ ] 8 new fields present in `Config` with correct types and defaults
- [ ] `is_async: bool = False` present in `Capabilities`; `local.py` and `api.py` pass
  `is_async=False` explicitly
- [ ] All CFG-1..9 assertions green in `tests/test_config.py`
- [ ] CHAR-1..5 still green
- [ ] `make gate` exits 0

**ACs satisfied:** CFG-1, CFG-2, CFG-3, CFG-4, CFG-5, CFG-6, CFG-7, CFG-8, CFG-9

**Rollback:** revert `config.py`, `backends/base.py`, `backends/local.py`, `backends/api.py`,
and `tests/test_config.py` to S1 state.

---

## S3 — BatchStore + Data Schemas

**Goal:** Implement `batch_store.py` with `JobRef`, `JobStatus`, `JobRecord` dataclasses;
`BatchStore` Protocol; `SidecarBatchStore` D1 implementation; and `make_store` factory.

**Depends on:** S2 (`cfg.batch_store_path` must exist for `make_store` factory tests)

**Files:**
- `src/electric_blue/batch_store.py` — create
- `tests/test_batch_store.py` — create

**Components in `batch_store.py`:**
- `JobRef` dataclass: `job_id`, `jsonl_file_id`, `staged_url`, `output_file_id: str | None = None`
  (A1: `staged_url` replaces `audio_file_id` from DDR §4)
- `JobStatus` dataclass: `raw`, `terminal`, `succeeded`, `output_file_id`, `error`
- `JobRecord` dataclass: all 10 fields per 02-ARCHITECTURE §3; `staged_url` (not `audio_file_id`)
- `BatchStore` Protocol: `save`, `get`, `find_by_src_name`, `list_pending`, `update`
- `SidecarBatchStore` class: atomic JSON write via temp file + `Path.replace()`
- `make_store(cfg)` factory

**`SidecarBatchStore` implementation notes (02-ARCHITECTURE §10):**
- Sidecar filename: `<store_path>/<job_id>.json`
- Write: `json.dumps(dataclasses.asdict(record))` to temp sibling, then `tmp.replace(final)`
- `list_pending()`: glob `*.json`, filter `status in {"submitted", "polling"}`
- `update(job_id, **kwargs)`: `get()` → `dataclasses.replace(record, **kwargs)` → atomic write
- `find_by_src_name()`: returns any record with matching `src_name` (caller checks live-ness per A4)
- Cold-start: new process + existing `batch_store_path` → `list_pending()` reads sidecars; no
  in-memory state required

**Tests added in `tests/test_batch_store.py`** (all hermetic; use `tmp_path` fixture):

- **(STORE-1):** `BatchStore` Protocol is structural; `SidecarBatchStore` satisfies it; `make_store`
  returns a `BatchStore`-compatible object.

- **(STORE-2):** `store.save(record)` → `<job_id>.json` exists in `store_path`; `json.loads()` →
  all `JobRecord` fields present.

- **(STORE-3):** `list_pending()` returns only records with `status in {"submitted", "polling"}`;
  records with `status="completed"`, `"failed"`, `"expired"`, `"cancelled"` excluded.

- **(STORE-4):** `save(record)` then `update(id, status="completed", completed_at="...")` then
  `get(id)` → `status == "completed"`, `completed_at` set, all other fields unchanged.

- **(STORE-5):** `find_by_src_name("x.mp4")` → matching record returned; no match → `None`.

- **(STORE-6):** Simulate cold-start: `save(record)` in one `make_store()` instance; new
  `make_store(cfg)` call on the same path → `list_pending()` returns the record.

- **(STORE-7):** `update(job_id="A")` → only `A.json` touched; `B.json` hash unchanged.

- **(STORE-8):** `JobRecord` dataclass fields match the spec (all 10 named fields present);
  `dataclasses.asdict(record)` is JSON-serializable without custom encoders; `staged_url`
  field exists (not `audio_file_id`).

**Done when:**
- [ ] `batch_store.py` created with all components
- [ ] STORE-1..8 green in `tests/test_batch_store.py`
- [ ] All CHAR-1..5 + CFG-1..9 still green
- [ ] `make gate` exits 0

**ACs satisfied:** STORE-1, STORE-2, STORE-3, STORE-4, STORE-5, STORE-6, STORE-7, STORE-8

**Rollback:** delete `src/electric_blue/batch_store.py`; delete `tests/test_batch_store.py`.

---

## S4 — UrlStager + FunnelStager

**Goal:** Implement `staging.py` with the `UrlStager` Protocol, `FunnelStager` implementation,
and `make_stager` factory. Test core staging and unstaging behavior hermetically.

**Depends on:** S2 (`cfg.batch_stage_dir` and `cfg.batch_funnel_base_url` must exist)

**Files:**
- `src/electric_blue/staging.py` — create
- `tests/test_staging.py` — create (STAG-1..3; STAG-4/5/6/7 added in S5/S6/S7)

**Components in `staging.py`:**
- `UrlStager` Protocol: `stage(path: Path) -> str`, `unstage(url: str) -> None`
- `FunnelStager` class: `__init__(stage_dir, base_url)`, `stage`, `unstage`
- `make_stager(cfg)` factory: raises `RuntimeError` if `cfg.batch_funnel_base_url == ""`

**`FunnelStager` implementation notes (02-ARCHITECTURE §8):**
- `stage(path)`: `shutil.copy2(path, self.stage_dir / path.name)`; return
  `f"{self.base_url.rstrip('/')}/{path.name}"`. The returned URL contains only the filename,
  never an absolute filesystem path (INV-7). Raises if copy fails. The `path` argument is
  always named `f"{src.stem}.mp3"` by `submit()` callers, ensuring URL uniqueness per source
  file (B3 — verified by STAG-7 in S5).
- `unstage(url)`: derive filename via `url.rsplit("/", 1)[-1]`; delete
  `self.stage_dir / filename` if it exists; silently return if missing (idempotent).

**Tests added in `tests/test_staging.py`:**

- **(STAG-1):** `UrlStager` is a `Protocol`; verify `FunnelStager` satisfies it structurally
  (e.g., `isinstance` check via `runtime_checkable` or duck-type assertion).

- **(STAG-2):** With `base_url="https://host.ts.net/stage"` and `stage_dir=tmp_path`, call
  `stager.stage(Path("/batch_submitted/meeting.mp3"))`. Assert: (a) `tmp_path / "meeting.mp3"`
  exists; (b) returned URL == `"https://host.ts.net/stage/meeting.mp3"` with no absolute
  path component.

- **(STAG-3):** `stager.stage(...)` then `stager.unstage(url)` → staged file deleted from
  `stage_dir`. Second `unstage(url)` call does not raise (idempotent).

**Note on STAG-4, STAG-5, STAG-6, STAG-7:** These are integration ACs requiring GroqBatchBackend
(STAG-4, STAG-7), drain_batch (STAG-5), and handle_batch (STAG-6). They are placed in the test
files most natural for each integration:
- STAG-4 → `tests/test_batch_groq.py` in S5
- STAG-7 → `tests/test_batch_groq.py` in S5 (both (a) stem-name in submit() and (b) URL
  uniqueness are most naturally verified in the submit() test context)
- STAG-6 → `tests/test_handle_batch.py` in S7
- STAG-5 → `tests/test_drain.py` in S6

All appear in `tests/test_staging.py` per 02-ARCHITECTURE §19 if the implementer prefers to
co-locate them there; the placement choice does not affect slice ordering or gate criteria.

**Done when:**
- [ ] `staging.py` created with `UrlStager`, `FunnelStager`, `make_stager`
- [ ] STAG-1, STAG-2, STAG-3 green in `tests/test_staging.py`
- [ ] All prior tests still green
- [ ] `make gate` exits 0

**ACs satisfied:** STAG-1, STAG-2, STAG-3

**Rollback:** delete `src/electric_blue/staging.py`; delete `tests/test_staging.py`.

---

## S5 — AsyncBackend Protocol + GroqBatchBackend (mocked HTTP)

**Goal:** Implement `backends/batch_groq.py` with `AsyncBackend` Protocol and
`GroqBatchBackend`. Test the full submit/poll/fetch lifecycle with zero live network calls
using mocked HTTP (`requests` monkeypatched or `responses` library). Test stager-backend
integration (STAG-4, STAG-7).

**Depends on:** S2 (Config batch fields), S3 (JobRef, JobStatus from batch_store), S4
(UrlStager from staging)

**Files:**
- `src/electric_blue/backends/batch_groq.py` — create
- `tests/test_batch_groq.py` — create (ASYNC-1..12, STAG-4, STAG-7)

**Components in `batch_groq.py`:**
- `AsyncBackend` Protocol: `name: str`, `capabilities: Capabilities`, `submit`, `poll`, `fetch`
- `GroqBatchBackend` class: constructor takes `UrlStager`; not registered in `_REGISTRY` (A6);
  `capabilities` is `Capabilities(is_async=True, needs_network=True, max_upload_mb=None,
  needs_gpu_recommended=False, supports_diarization=False)`
- `make_groq_batch_backend(cfg)` factory

**submit() implementation notes (02-ARCHITECTURE §5):**
1. Guard: `not cfg.batch_api_key` → `RuntimeError` (ASYNC-9, INV-2)
2. Guard: `not cfg.batch_funnel_base_url` → `RuntimeError` (INV-2, A3)
3. `audio.extract(cfg, src, mp3_tmp, compressed=True)` inside `TemporaryDirectory`;
   `mp3_tmp` is named `f"{src.stem}.mp3"` (e.g. `meeting.mp3` for `meeting.mp4`) — ensures
   staged URL is unique per source, prevents filename collisions in `batch_stage_dir` (B3, STAG-7)
4. Size check: `mp3.stat().st_size / 1e6 > cfg.batch_max_mb` → `RuntimeError` (ASYNC-11)
5. `staged_url = self.stager.stage(mp3_tmp)` — raises propagate to caller (STAG-6)
6. Build JSONL line: `"url": staged_url` (no `"file"` field — D6 correction); include
   `"language": cfg.language` only if `cfg.language` is set (ASYNC-10); include
   `"custom_id": f"eb-{src.stem}"` at the top level of the request object
7. POST JSONL to `{cfg.api_base_url}/files` with `Authorization: Bearer {cfg.batch_api_key}`
8. POST to `{cfg.api_base_url}/batches` with `"completion_window": cfg.batch_completion_window`
9. Return `JobRef(job_id=..., jsonl_file_id=..., staged_url=staged_url)`

**HTTP mock seam:** `import requests` at module top in `batch_groq.py`. Mock target:
```python
monkeypatch.setattr("electric_blue.backends.batch_groq.requests.post", mock_post)
monkeypatch.setattr("electric_blue.backends.batch_groq.requests.get", mock_get)
```

`audio.extract` must also be mocked to avoid real ffmpeg calls (use `monkeypatch.setattr`
targeting `electric_blue.backends.batch_groq.audio.extract` or inject via stub).

**Tests in `tests/test_batch_groq.py`:**

- **(ASYNC-1):** `AsyncBackend` is a Protocol; `GroqBatchBackend` satisfies it structurally
  (has `name`, `capabilities`, `submit`, `poll`, `fetch`).

- **(ASYNC-2):** `GroqBatchBackend.capabilities` is `Capabilities` with `is_async=True`,
  `needs_network=True`, `needs_gpu_recommended=False`, and `max_upload_mb is None`. (Size-cap
  enforcement is done internally by `submit()` via `cfg.batch_max_mb`; the `Capabilities` field
  is not used as a per-call cap in the async path.)

- **(ASYNC-3):** Mocked HTTP; verify: (a) `audio.extract` called with `compressed=True`;
  (b) `stager.stage(mp3_path)` called exactly once; (c) JSONL POST body has `"url": staged_url`
  and no `"file"` key in `body`; (d) `"custom_id": f"eb-{src.stem}"` at top-level of request
  object; (e) files POST targets `{api_base_url}/files`; (f) batches POST includes
  `"completion_window": cfg.batch_completion_window`; (g) returned `JobRef.staged_url`
  matches stager's return value.

- **(ASYNC-4):** Mock returns `{"status": "in_progress"}` → `poll()` returns `JobStatus`
  with `terminal=False`, `succeeded=False`, `output_file_id=None`, `error=None`.

- **(ASYNC-5):** Mock returns `{"status": "completed", "output_file_id": "file_abc"}` →
  `poll()` returns `JobStatus(terminal=True, succeeded=True, output_file_id="file_abc")`.

- **(ASYNC-6):** `{"status": "failed"}`, `{"status": "expired"}`, `{"status": "cancelled"}` →
  all return `JobStatus(terminal=True, succeeded=False)`.

- **(ASYNC-7):** Mock output JSONL with `"segments": [{"start": 0.0, "end": 2.4, "text": "hello"}]`
  → `fetch()` returns `Transcript` with `segments[0]` matching and `info.backend == f"batch:{cfg.api_model}"`.

- **(ASYNC-8):** Mock output JSONL with `"text": "hello world"` and no `"segments"` → `fetch()`
  returns `Transcript` with one synthetic segment `Segment(start=0.0, end=<duration>, text="hello world")`.

- **(ASYNC-9):** `cfg.batch_api_key=""` → `submit()` raises `RuntimeError` before any network
  call; `requests.post` is never invoked.

- **(ASYNC-10):** With `cfg.language="fr"` → JSONL body contains `"language": "fr"`. With
  `cfg.language=None` → no `language` key in body.

- **(ASYNC-11):** Given a source file whose encoded MP3 size (in megabytes) exceeds
  `cfg.batch_max_mb`, when `submit(cfg, src)` is called with mocked HTTP (and mocked
  `audio.extract` that produces a large file), then it raises `RuntimeError` before any
  `requests.post` call is made. (Via SUBMIT-5, the source file is subsequently moved to
  `cfg.failed_dir` — that chain is tested in S7.)

- **(ASYNC-12):** Given a mock returning `{"status": "validating"}` or any other unrecognized
  status string, when `poll(cfg, job)` is called, then it returns `JobStatus(raw=<status>,
  terminal=False, succeeded=False, output_file_id=None, error=None)` — the conservative
  "unknown → not terminal" policy ensures drain retries on the next invocation.

- **(STAG-4):** `GroqBatchBackend.submit()` with a `StubStager` that records calls and mocked
  HTTP → `stager.stage()` called exactly once; the returned URL appears verbatim as `body.url`
  in the JSONL POST body.

- **(STAG-7):** Given `src=Path("/batch_inbox/meeting.mp4")`, when `submit(cfg, src)` is called
  with mocked `audio.extract` and a `StubStager`, then: (a) the path passed to `stager.stage()`
  has `.name == "meeting.mp3"` (i.e. `f"{src.stem}.mp3"`, not `"a.mp3"`); (b) the URL
  returned by `StubStager.stage()` matches `f"{cfg.batch_funnel_base_url}/{src.stem}.mp3"`,
  confirming the staged URL is unique per source file and filename collisions in `batch_stage_dir`
  are prevented (B3).

**CFG-9 cross-path coverage:** In ASYNC-3 or a dedicated test, use `caplog` and assert
`cfg.batch_api_key` value is not present in any log output across the submit path.

**Note:** `GroqBatchBackend` does not appear in `backends/__init__.py._REGISTRY`. If
`WHISPER_BACKEND=batch` is set, `get_backend()` raises `RuntimeError("Unknown backend 'batch'...")` —
this is correct INV-2 behavior and requires no code change (A6).

**Done when:**
- [ ] `backends/batch_groq.py` created with `AsyncBackend`, `GroqBatchBackend`,
  `make_groq_batch_backend`
- [ ] ASYNC-1..12 + STAG-4 + STAG-7 green in `tests/test_batch_groq.py`
- [ ] All prior tests (CHAR-1..5, CFG, STORE, STAG-1..3) still green
- [ ] `make gate` exits 0 with zero live network calls

**ACs satisfied:** ASYNC-1, ASYNC-2, ASYNC-3, ASYNC-4, ASYNC-5, ASYNC-6, ASYNC-7, ASYNC-8,
ASYNC-9, ASYNC-10, ASYNC-11, ASYNC-12, STAG-4, STAG-7

**Rollback:** delete `src/electric_blue/backends/batch_groq.py`; delete
`tests/test_batch_groq.py`.

---

## S6 — drain_batch + Completion Hook

**Goal:** Implement `drain.py` with `drain_batch`, `_fire_completion_hook`, `_now_iso`, and
`_maybe_warn_expiry`. Test the full drain lifecycle, per-job exception isolation,
completion hooks, failure/expiry handling, and stager unstage integration — all with injected
mocks. Test `drain_batch` guard when `batch_inbox_dir is None`.

**Depends on:** S2 (Config), S3 (batch_store), S4 (staging), S5 (batch_groq)

**Files:**
- `src/electric_blue/drain.py` — create
- `tests/test_drain.py` — create (DRAIN-1..8, DRAIN-10, HOOK-1..3, FAIL-1..4, STAG-5)

**Components in `drain.py`:**
- `drain_batch(cfg, *, backend=None, stager=None)` — optional DI for hermetic tests
- `_fire_completion_hook(cfg, record, info)` — best-effort; swallows all exceptions
- `_now_iso()` — UTC ISO 8601 with second precision
- `_maybe_warn_expiry(record, cfg)` — warn if `submitted_at` is older than 80% of
  `cfg.batch_completion_window` and status is live (DRAIN-8); threshold scales with the
  parsed window value (e.g. 19.2 h for default "24h", 134.4 h for "7d")

**drain_batch() flow notes (02-ARCHITECTURE §11):**
- Guard: `if cfg.batch_inbox_dir is None: return` (DRAIN-10)
- Build `JobRef` from record fields for poll; use `dataclasses.replace(job_ref, output_file_id=status.output_file_id)` before calling `fetch()` — this is how `output_file_id` flows from poll result to fetch without mutating the original `JobRef`
- B1 defense-in-depth: backend/stager construction is inside the per-job `try` block so any
  `RuntimeError` from `make_stager` (empty funnel URL) is caught per-job and logged, without
  aborting the entire drain. The primary guard is `ensure_batch_dirs()` at startup (S7).
- Success path ordering (INV-1): `fetch()` → `write_outputs()` → `shutil.move(staged → done_dir)` if exists → `store.update(completed)` → `stager.unstage()` → `_fire_completion_hook()`
- Failure path ordering (INV-1): `shutil.move(staged → failed_dir)` if exists → `store.update(failed/expired/cancelled)` → `stager.unstage()`
- Per-job `try/except` at outer loop (DRAIN-7): one job's exception leaves its status unchanged and continues processing the rest

**Tests in `tests/test_drain.py`** (all use `MockBatchStore`, `MockAsyncBackend`, `StubStager` injected via DI — no real filesystem beyond `tmp_path` for output files):

- **(DRAIN-1):** `list_pending()` returns 2 records → `poll()` called exactly twice.

- **(DRAIN-2):** `poll()` returns `terminal=False` → `store.update(status="polling")` called;
  record remains in `list_pending()`.

- **(DRAIN-3):** `poll()` returns `terminal=True, succeeded=True, output_file_id="file_abc"` →
  in order: `fetch()` called, `write_outputs()` called and outputs exist, staged file moved to
  `done_dir`, `store.update(status="completed", completed_at=<now>)` called, `_fire_completion_hook`
  called. Verify order via `unittest.mock.call_order` or side-effect tracking.

- **(DRAIN-4):** `poll()` returns `terminal=True, succeeded=False` → `fetch()` NOT called;
  staged moved to `failed_dir`; `store.update(status=raw, error=...)` called; error logged;
  `done_dir` untouched (INV-1).

- **(DRAIN-5):** Run `drain_batch()` twice on the same pending record with a terminal-success
  mock. Second run: `write_outputs()` idempotent (overwrites); `staged.exists()` guard prevents
  double-move. Final state identical to first run.

- **(DRAIN-6):** Simulate crash between `shutil.move(staged → done_dir)` and
  `store.update(completed)` by having the mock store raise on the first update call. Second
  `drain_batch()` run: record still `status="polling"` → `poll()` returns completed → `fetch()`
  again → `write_outputs()` again → `staged.exists()` is False → no second move →
  `store.update(completed)` succeeds. No data loss (INV-1).

- **(DRAIN-7):** `poll()` raises for job A; `drain_batch()` logs error for A; status unchanged;
  processing continues for job B.

- **(DRAIN-8):** Record with `submitted_at` older than 80% of `cfg.batch_completion_window`
  and `status="polling"` → `WARNING` log emitted with job_id indicating impending expiry.
  Test with both "24h" (warn threshold = 19.2h) and "7d" (warn threshold = 134.4h) to confirm
  threshold scales with the window, not hardcoded to 20h.

- **(DRAIN-10):** `cfg.batch_inbox_dir is None` → `drain_batch()` returns immediately; no
  store access, no network call.

- **(HOOK-1):** Successful drain → `notify(cfg, payload)` called with a dict containing at
  minimum `"schema_version": 1`, `"file": record.src_name`, `"job_id": record.job_id`,
  `"backend": info.backend`, `"status"` indicating batch completion, `"event": "batch_done"`.
  Assert `requests.post` is never called when `cfg.notify_webhook=""` (DDR-04 no-op behavior).

- **(HOOK-2):** `notify()` raises inside `_fire_completion_hook` → exception caught and logged
  at `WARNING`; drain continues (i.e., subsequent mock backend/store calls are not prevented).

- **(HOOK-3):** `cfg.notify_webhook=""` → `requests.post` never invoked through the hook path.

- **(FAIL-1):** `poll()` returns `raw="failed"` → staged moved to `failed_dir`; `store.update(status="failed", error=<non-None>)`; `stager.unstage(record.staged_url)` called.

- **(FAIL-2):** `poll()` returns `raw="expired"` → same as FAIL-1 with `status="expired"`.

- **(FAIL-3):** Staged file does not exist at `record.staged_path` when drain tries to move it
  to `failed_dir` → `WARNING` logged; drain continues normally; no `FileNotFoundError` raised.

- **(FAIL-4):** `stager.unstage(url)` raises during drain (both failure and success paths) →
  exception caught; logged at `WARNING`; drain continues.

- **(STAG-5):** `poll()` returns terminal state (test with `completed`, `failed`, `expired`) →
  `stager.unstage(record.staged_url)` called exactly once for each job in each terminal case.

**CFG-9 cross-path verification:** In at least one test that exercises a code path that reads
`cfg.batch_api_key` (through the injected backend mock or through a code path in drain that
propagates the config), assert `caplog.text` does not contain the key value.

**Note on concurrent drain (FLAG-2):** `drain.py` includes a module-level docstring noting
that simultaneous `--drain-batch` invocations are unsupported. No locking is implemented
this sprint.

**Done when:**
- [ ] `drain.py` created with all components
- [ ] DRAIN-1..8, DRAIN-10, HOOK-1..3, FAIL-1..4, STAG-5 green in `tests/test_drain.py`
- [ ] All prior tests still green
- [ ] `make gate` exits 0

**ACs satisfied:** DRAIN-1, DRAIN-2, DRAIN-3, DRAIN-4, DRAIN-5, DRAIN-6, DRAIN-7, DRAIN-8,
DRAIN-10, HOOK-1, HOOK-2, HOOK-3, FAIL-1, FAIL-2, FAIL-3, FAIL-4, STAG-5

**Rollback:** delete `src/electric_blue/drain.py`; delete `tests/test_drain.py`.

---

## S7 — handle_batch + Watcher Batch Observer + CLI

**Goal:** Add `ensure_batch_dirs`, `handle_batch`, and `_BatchHandler` to `watcher.py`; add the
`if cfg.batch_inbox_dir:` observer branch to `run_watch()`; add `--drain-batch` flag and fix
the pre-existing `--file` crash in `cli.py`. Test the batch submission path, duplicate-submission
guard, failure routing, startup validation, and CLI dispatch.

**Depends on:** S2 (Config), S3 (make_store, JobRecord), S4 (make_stager), S5 (make_groq_batch_backend),
S6 (drain_batch in cli.py --drain-batch dispatch)

**Files:**
- `src/electric_blue/watcher.py` — modify (additive: `ensure_batch_dirs`, `handle_batch`,
  `_BatchHandler`; addition to `run_watch()`: batch observer branch after sync observer)
- `src/electric_blue/cli.py` — modify: (1) additive: `--drain-batch` argument + dispatch branch;
  (2) fix: `--file` branch passes `datetime.now(timezone.utc)` as required third argument to `process()`
- `tests/test_handle_batch.py` — create (SUBMIT-1..8, STAG-6, DRAIN-9, CFG-10, CLI-1)

**watcher.py additions (all additive; sync `H`, `handle()`, `run_once()`, `run_watch()` sync
path are NOT modified):**

```python
def ensure_batch_dirs(cfg: Config) -> None:
    """Create batch_inbox_dir, batch_submitted_dir, batch_stage_dir, batch_store_path.

    PRIMARY FUNNEL GUARD (B1, CFG-10): Raises RuntimeError if cfg.batch_funnel_base_url is
    empty when batch is enabled. Called only when cfg.batch_inbox_dir is not None. Any
    RuntimeError raised here propagates through run_watch() and aborts the process — deliberate.
    """

def handle_batch(
    cfg: Config,
    path: Path,
    *,
    backend: "AsyncBackend | None" = None,
    store: "BatchStore | None" = None,
) -> None:
    """Batch submission path with optional DI for test injection."""
```

`handle_batch()` execution order (SUBMIT-1, INV-1 per 02-ARCHITECTURE §12):
1. Suffix check — return if not a media extension (SUBMIT-7)
2. `is_stable(path, cfg.stability_seconds)` — return if not stable
3. `store.find_by_src_name(path.name)` — skip if `existing.status in {"submitted", "polling"}` (A4, SUBMIT-3)
4. Inside `try` block: construct backend (B1 defense-in-depth); `backend.submit(cfg, path)` (SUBMIT-5)
5. `store.save(record)` — BEFORE `shutil.move` (INV-1); `record.staged_path = str(cfg.batch_submitted_dir / path.name)` — DESTINATION unconditionally (SUBMIT-8)
6. `shutil.move(path → batch_submitted_dir / path.name)`
   On exception in steps 4–6: log error, `shutil.move(path → failed_dir)`, no store write.

**run_watch() addition** (after sync observer; sync observer line is unchanged):
```python
if cfg.batch_inbox_dir:
    ensure_batch_dirs(cfg)   # primary B1 guard — raises RuntimeError if funnel URL unset
    obs.schedule(_BatchHandler(cfg), str(cfg.batch_inbox_dir), recursive=False)
```

**cli.py changes** (current `main()` takes no arguments; reads `sys.argv` via `ap.parse_args()`):

```python
# New argument (add before --file and --once branches):
ap.add_argument(
    "--drain-batch",
    action="store_true",
    help="Poll pending Groq Batch jobs and retrieve completed ones. Safe to call from cron.",
)

# In main() — --drain-batch branch is checked FIRST, before --file and --once:
if args.drain_batch:
    from .drain import drain_batch
    drain_batch(cfg)
    return

# --file fix (pre-existing crash: process() requires 3 args; prior call passed 2):
if args.file:
    from datetime import datetime, timezone
    process(cfg, Path(args.file), datetime.now(timezone.utc))
```

The `--file` fix supplies `datetime.now(timezone.utc)` as the required `started_at` argument,
matching the pattern used in `handle()` in `watcher.py`. This closes CLI-1.

**Tests in `tests/test_handle_batch.py`** (inject mock backend and store via DI parameters):

- **(SUBMIT-1):** Successful `handle_batch()` → execution order verified: stability check →
  live-record guard → submit → store.save → shutil.move. Use side-effect tracking to assert order.

- **(SUBMIT-2):** Verify that `run_watch(cfg)` with `cfg.batch_inbox_dir=None` schedules
  exactly one observer (sync only) and never calls `ensure_batch_dirs` or schedules
  `_BatchHandler`.

  **Seam — same two-patch approach as CHAR-3:**
  1. `monkeypatch.setattr("watchdog.observers.Observer", FakeObserver)` where `FakeObserver`
     records calls and spawns no real thread. Because `run_watch` does
     `from watchdog.observers import Observer` at function entry, patching
     `watchdog.observers.Observer` is the correct target.
  2. `monkeypatch.setattr(electric_blue.watcher.time, "sleep", Mock(side_effect=KeyboardInterrupt))`
     (add `from unittest.mock import Mock`) so the first `sleep` raises `KeyboardInterrupt` and `run_watch` returns cleanly via its
     `except` branch. Patching only `Observer.schedule` leaves the `while True` loop alive
     and the test hangs indefinitely.
  - `cfg` must have `batch_inbox_dir=None` and `tmp_path`-based dirs (`input_dir`, `done_dir`,
    `failed_dir`) so `run_once(cfg)` succeeds without error at the start of `run_watch`.

  Assertions: `FakeObserver` instance `.schedule` call count == 1; `ensure_batch_dirs` not
  called (monkeypatch it to a recording stub to verify); `_BatchHandler` never passed to
  `.schedule`.

- **(SUBMIT-3):** Existing record with `status="submitted"` or `status="polling"` for same
  filename → `submit()` NOT called; `WARNING` logged.

- **(SUBMIT-4):** Existing record with `status="failed"` or `status="expired"` for same
  filename → `submit()` IS called; new `JobRecord` created with new `job_id`.

- **(SUBMIT-5):** `backend.submit()` raises → no store record written; file moved to
  `failed_dir`; error logged; `done_dir` untouched (INV-1).

- **(SUBMIT-6):** `store.save()` succeeds; `shutil.move()` raises → store record exists with
  `status="submitted"` and `staged_path == str(cfg.batch_submitted_dir / path.name)` (the
  DESTINATION, set unconditionally before the move); source file remains at
  `batch_inbox_dir / path.name`. On next `handle_batch()` for same filename, live-record
  guard detects the record and skips re-submission.

- **(SUBMIT-7):** File suffix not in `cfg.media_exts` → `handle_batch()` returns immediately;
  `submit()`, `store.save()`, and `shutil.move()` all not called.

- **(SUBMIT-8):** On any successful `store.save(record)` call in `handle_batch()`, assert
  `record.staged_path == str(cfg.batch_submitted_dir / path.name)` — the DESTINATION path.
  This value is set unconditionally before `shutil.move()` executes so that `drain_batch()`
  always knows where the source file should be.

- **(STAG-6):** `stager.stage()` raises (injected via a mock backend whose `submit()` calls
  the stager internally) → exception propagates to `handle_batch()` except block; no
  `JobRecord` written to the store; source file moved to `cfg.failed_dir`; error logged.

- **(CFG-10):** Call `ensure_batch_dirs(cfg)` with a cfg where `batch_inbox_dir` is not `None`
  and `batch_funnel_base_url == ""`. Assert `RuntimeError` is raised. This confirms the primary
  B1 startup guard: watcher aborts before accepting any file when Funnel URL is not configured.
  Also assert that a cfg with a non-empty `batch_funnel_base_url` does NOT raise (and creates
  the expected directories in `tmp_path`).

- **(DRAIN-9):** Test the `--drain-batch` CLI dispatch with the correct mock seam:
  (1) Use `monkeypatch.setattr("electric_blue.drain.drain_batch", mock_drain)` — patch the
  attribute on the `electric_blue.drain` MODULE, NOT on `electric_blue.cli`. The `--drain-batch`
  branch uses a lazy `from .drain import drain_batch` inside `main()`, which reads the attribute
  from `electric_blue.drain` at call time. Patching `electric_blue.cli.drain_batch` will NOT
  intercept it (that name is not bound at module level).
  (2) Use `monkeypatch.setattr(sys, "argv", ["electric-blue", "--drain-batch"])` to set the
  argv that `ap.parse_args()` reads (since `main()` takes no arguments).
  (3) Call `electric_blue.cli.main()` (no arguments).
  Assert: `mock_drain` called exactly once with the `cfg` object; `main()` returns normally.

- **(CLI-1):** Test that the `--file` fix removes the pre-existing `TypeError`: use
  `monkeypatch.setattr(sys, "argv", ["electric-blue", "--file", "/tmp/meeting.mp4"])` and
  mock `process` at `electric_blue.watcher.process` (since it is lazily imported inside
  `main()`). Call `main()`. Assert `process` was called with exactly 3 arguments — `cfg`,
  `Path("/tmp/meeting.mp4")`, and a `datetime` — with no `TypeError` raised. (This would have
  crashed with the 2-arg pre-fix call.)

**Done when:**
- [ ] `watcher.py` modified with `ensure_batch_dirs`, `handle_batch`, `_BatchHandler`, batch
  observer branch in `run_watch()`
- [ ] `cli.py` modified with `--drain-batch` argument + dispatch (lazy import from `.drain`),
  and `--file` branch fixed to pass `datetime.now(timezone.utc)` as third arg to `process()`
- [ ] SUBMIT-1..8, STAG-6, DRAIN-9, CFG-10, CLI-1 green in `tests/test_handle_batch.py`
- [ ] All CHAR-1..5 still green (sync observer behavior unchanged; cli dispatch pre-fix pins untouched)
- [ ] All prior tests still green
- [ ] `make gate` exits 0

**ACs satisfied:** SUBMIT-1, SUBMIT-2, SUBMIT-3, SUBMIT-4, SUBMIT-5, SUBMIT-6, SUBMIT-7,
SUBMIT-8, STAG-6, DRAIN-9, CFG-10, CLI-1

**Rollback:** revert `src/electric_blue/watcher.py` to post-S6 state; revert
`src/electric_blue/cli.py` to pre-S7 state; delete `tests/test_handle_batch.py`.

---

## S8 — Final Gate + Smoke + Frank BUILD Gate

**Goal:** Confirm all code slices are gate-green, smoke is attested, secrets scan is clean,
and obtain a Frank SHIP verdict before opening the PR.

**Depends on:** S7 (all code complete and gate-green)

**Files:** none

**Steps:**

1. **Full gate:**
   ```
   PATH="$PWD/.venv/bin:$PATH" make gate
   ```
   Must exit 0 with all 67 sprint ACs exercised and green. Zero live network calls; no
   `GROQ_BATCH_API_KEY` in the environment.

2. **Pre-smoke doc verification (D7/D8 — VERIFY):** Before triggering the smoke test,
   check Groq Batch API docs for:
   - D7: exact JSONL field names in `body` for `/v1/audio/transcriptions` and the output
     JSONL line schema
   - D8: per-audio-file size cap in batch context vs the `batch_max_mb=25` placeholder
   Document findings. If field names differ from the mocked schemas, patch `batch_groq.py`
   accordingly and re-run `make gate`. This is a pre-smoke verification step, not a slice
   gate — it does not require a new slice unless structural changes are needed.

3. **Smoke gate (live Groq Batch API — REQUIRES PAID KEY):**
   The live smoke is **out of scope for the hermetic gate** (no paid Groq account currently
   exists). This step is deferred until a `GROQ_BATCH_API_KEY` is provisioned. When
   provisioned: run a `@pytest.mark.smoke`-tagged test that exercises the full lifecycle
   against the live Groq Batch API (one audio file → submit → poll until complete → fetch →
   assert output files written). Attach result as a PR artifact. Until then, this step is
   a placeholder and the PR is opened with a note that live smoke is pending key provisioning.

4. **Secret scan (CADENCE P7):** Deny-list grep over the diff for Tailscale `100.x` IPs, DB
   DSN, API keys, relay creds, `notify_webhook` values, `gh auth token` output. Diff must
   be clean. Confirm `CLAUDE.md` and `docs/homelab/` remain gitignored.

5. **Frank BUILD gate (CADENCE P8):** Frank reviews built slices against spec and invariants.
   Gate criteria: `make gate` green (P5), smoke attested or deferred with explanation (P6),
   secret scan clean (P7), no invariant tripped, all 67 sprint ACs present and passing.

6. **PR (CADENCE P9):** Open PR with gate artifact, smoke status, Frank SHIP verdict.

**Done when:** Frank BUILD gate verdict = SHIP.

---

## Deferred Work

Items explicitly out of scope for this sprint:

| Item | Decision | Future path |
|------|----------|-------------|
| Live Groq Batch API smoke test | No paid key exists; INV-8 (gate hermetic) | Provision `GROQ_BATCH_API_KEY`; add `@pytest.mark.smoke` test post-key |
| Groq-side file cleanup (JSONL + output file deletion via Files API) | D9 still VERIFY; A7 defers this | Verify D9; implement in a follow-up |
| Minted-URL stager (Cloudflare R2, Backblaze B2 pre-signed URLs) | UrlStager abstraction is built; second impl is not | Implement `MintedUrlStager` as a new `UrlStager` + new Config fields |
| Batch job aggregation (many files in one JSONL) | D4: one file per batch object throughout | Future DDR if cost/rate-limit reasons emerge |
| Automatic re-submission on failure | D5: fail-loud + operator re-drop | DDR if operator UX requires it |
| Per-audio-file Groq batch size cap verification | D8 VERIFY placeholder at 25 MB | Verify at live smoke step; update `batch_max_mb` default if needed |
| Concurrent drain safety (file locking on sidecar write) | FLAG-2 documented as unsupported | Future: `fcntl.flock` on per-sidecar file or atomic rename pattern |
| D7 field name verification (Groq JSONL schema) | Gate tests use mocked schemas | Verify at pre-smoke step S8.2; patch if needed before smoke |
| DDR-05 diarization features | Out of scope by spec | DDR-05 sprint |

---

## AC Coverage Ledger

| Slice | ACs Covered |
|-------|-------------|
| S1 | CHAR-1, CHAR-2, CHAR-3, CHAR-4 |
| S2 | CFG-1, CFG-2, CFG-3, CFG-4, CFG-5, CFG-6, CFG-7, CFG-8, CFG-9 |
| S3 | STORE-1, STORE-2, STORE-3, STORE-4, STORE-5, STORE-6, STORE-7, STORE-8 |
| S4 | STAG-1, STAG-2, STAG-3 |
| S5 | ASYNC-1, ASYNC-2, ASYNC-3, ASYNC-4, ASYNC-5, ASYNC-6, ASYNC-7, ASYNC-8, ASYNC-9, ASYNC-10, ASYNC-11, ASYNC-12, STAG-4, STAG-7 |
| S6 | DRAIN-1, DRAIN-2, DRAIN-3, DRAIN-4, DRAIN-5, DRAIN-6, DRAIN-7, DRAIN-8, DRAIN-10, HOOK-1, HOOK-2, HOOK-3, FAIL-1, FAIL-2, FAIL-3, FAIL-4, STAG-5 |
| S7 | SUBMIT-1, SUBMIT-2, SUBMIT-3, SUBMIT-4, SUBMIT-5, SUBMIT-6, SUBMIT-7, SUBMIT-8, STAG-6, DRAIN-9, CFG-10, CLI-1 |
| S8 | Process gate (all ACs verified by Frank) |

**Total ACs covered: 67.** All ACs from 01-REQUIREMENTS.md are assigned to exactly one
code slice. No AC is uncovered. No AC is assigned to more than one slice.

Count by family: CHAR (4) + CFG (9+1=10) + STORE (8) + STAG (3+2+1+1=7) + ASYNC (12) +
SUBMIT (7+1=8) + DRAIN (9+1=10) + HOOK (3) + FAIL (4) + CLI (1) = 67.

Family → slice mapping summary:
- CHAR-1..4 → S1; CFG-1..9 → S2; CFG-10 → S7
- STORE-1..8 → S3
- STAG-1..3 → S4; STAG-4, STAG-7 → S5; STAG-5 → S6; STAG-6 → S7
- ASYNC-1..12 → S5
- SUBMIT-1..8 → S7
- DRAIN-1..8, DRAIN-10 → S6; DRAIN-9 → S7
- HOOK-1..3 → S6; FAIL-1..4 → S6
- CLI-1 → S7
