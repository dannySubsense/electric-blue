# INVARIANTS — electric-blue

**Inviolable rules.** This is the wall. A merge candidate that violates any invariant does not
ship — no exceptions, no "just this once." Each invariant is phrased to be **checkable**: a
reviewer (human or Frank) can render a pass/fail verdict against it.

The Forge Advisor loads this file at session start. If you are about to do something that trips an
invariant, **HALT** and escalate — do not work around it.

> Scope split: **INVARIANTS.md is the wall** (runtime-integrity properties + what blocks a merge).
> **[CADENCE.md](CADENCE.md) is the path** you walk to reach the wall (ordered workflow + gates).
> If a rule is "do X in this order," it lives in CADENCE. If a rule is "this must be true or we
> lose data / ship silently-wrong output / leak a secret / don't ship," it lives here.

Authored 2026-06-14 (Reed), judgment-gated by Frank. Grounded in the running code, not aspiration.

**Status legend.** Each invariant is marked **MET** (the current `main` code satisfies it),
**TARGET** (the rule stands, but current code does not yet comply — the named sprint brings it into
compliance), or **PARTIAL** (one half MET, another TARGET or a standing gap — the body spells out
which). A TARGET invariant is still inviolable for the work that establishes it; it is not a
suggestion. This doubles the wall as a compliance ledger — when a TARGET flips to MET, update it here.

| Invariant | Status | Note |
|-----------|--------|------|
| INV-1 No data loss / no orphaned input | **MET** | `watcher.handle()` move-ordering is correct today |
| INV-2 Fail loud; never silently substitute | **PARTIAL** | error-half MET; backend-substitution half violated by `else→local` → fixed by issue #4 |
| INV-3 Behavior preserved unless owned | **MET** | active discipline (enforced per-change) |
| INV-4 Green gate AND smoke before merge | **MET** | gate in CI; smoke by attestation (P6) |
| INV-5 Frank SHIP precedes merge | **MET** | active gate |
| INV-6 Branch-and-PR; never commit to `main` | **MET** | `main` advances only via PRs |
| INV-7 Secrets never pushed / never in artifacts | **MET** | `CLAUDE.md`+`docs/homelab/` gitignored; no secret logging today |
| INV-8 Gate hermetic; smoke the only real lane | **MET** | `smoke` marker; gate is mocked |
| INV-9 ACCEPTED DDR decisions locked | **MET** | active rule (DDR-02 D1–D5) |
| INV-10 `schema_version` data-independent/additive | **TARGET** | not emitted yet — backend-seam S4 |
| INV-11 Dispatch only via Protocol + registry | **TARGET** | current dispatch is `if/else` — backend-seam S2–S3 |
| INV-12 Authorship ≠ judgment | **MET** | active separation |
| INV-13 Reproducible builds (ML stack pinned) | **MET** | model-ids + `faster-whisper>=1.2.0,<2.0` bounded; torch only via future `[diarize]` (whisperx-pinned) |
| INV-14 Gate runs against working-tree `src/` | **MET** | `tests/test_install_editable.py` (gate-marked) — fails on stale/non-editable install |

---

## Runtime integrity — the payload

### INV-1 — No data loss; no orphaned input *(first law of a drop-folder pipeline)*
Every input file terminates in **exactly one** of `done/` or `failed/`. The source is moved out of
`input_dir` **only after** `process()` returns successfully (outputs written). Any exception during
processing routes the source to `failed/`. No code path deletes or unlinks an input file.

- **Why:** the dropped file is frequently the user's only copy. Losing it is the 3am page.
- **Source of truth:** `watcher.py` `handle()` — move-to-`done` is strictly *after* `write_outputs`;
  the `except` path moves to `failed/`.
- **Check:** in `handle()`, the `shutil.move(... done_dir ...)` statement is strictly after the
  `process()` call; the failure path moves to `failed/`; `grep -rnE 'unlink|os\.remove|\.unlink\(' src/`
  finds nothing operating on an input path.

### INV-2 — Fail loud; never silently substitute
**Status: PARTIALLY MET — error-handling half MET; backend-substitution half TARGET (backend-seam,
issue #4).**
The system never substitutes a different backend, behavior, or output for the one requested.
Misconfiguration **raises**. Unknown `cfg.backend` raises `RuntimeError` (no `else`/default
catch-all that quietly runs a different backend). No `except` swallows a processing error: every
failure is **both logged and notified** (or re-raised).

- **Why:** the generalized form of the unknown-backend silent-fallback bug caught at the DDR-02
  spec gate. Silent substitution produces confidently-wrong output that no one notices.
- **Current state:** the error-handling half is MET — `watcher.handle()`'s `except` logs *and*
  notifies *and* routes to `failed/`. The backend-substitution half is **VIOLATED today**:
  `backends/__init__.py` is `if cfg.backend == "api": … else: transcribe_local`, so an unknown
  backend (e.g. `"batch"`) **silently runs local**. The backend-seam sprint (issue #4) replaces this
  with the registry + `RuntimeError` on unknown — that sprint is what brings dispatch into
  compliance. This invariant exists *because* the current code breaks it.
- **Check (enforced once issue #4 lands):** `grep -rnE 'if .*cfg\.backend ==' src/` finds no dispatch
  branching (dispatch is the registry only — see INV-11); no `except` in `handle`/`process` both
  fails to log *and* fails to notify/re-raise.

### INV-3 — Behavior preserved unless explicitly owned
No change alters the observable behavior of an existing code path **unless** that delta is:
(a) pinned by a characterization test green against the **pre-change** code, (b) carried by a
replacement assertion against the **post-change** code, and (c) **named as an owned change** in the
PR description.

- **Why:** a refactor that "passed" but quietly changed behavior is indistinguishable from a
  regression until production. (Sequencing — "char-tests-first" — lives in CADENCE; the *property*
  lives here.)
- **Check:** any PR touching existing runtime code shows characterization tests that were green
  pre-change; each intentional delta names the superseded test and its replacement.

### INV-7 — Secrets never pushed AND never in runtime artifacts
**(a) Repo:** no secret or personal datum — Tailscale `100.x.x.x` IPs, DB DSN, API keys, relay
creds, `notify_webhook` — appears in any tracked or pushed file. `CLAUDE.md` and `docs/homelab/`
stay gitignored. **(b) Runtime:** secrets are never written to logs, transcripts, output JSON, or
command output; auth tokens are masked in any printed command.

- **Why:** push-scanning catches (a) but not (b) — one `log.debug(cfg)` or one unmasked
  `gh auth token` in CI output leaks the key into a place that gets pasted into a bug report.
- **Secrets surface:** `config.py` carries `api_key`, `notify_webhook`; the push helper embeds an
  inline token.
- **Check:** deny-list grep over tracked content **and** over log/print/serialize sites finds no
  secret; `.gitignore` contains `CLAUDE.md` and `docs/homelab/`; the push command masks the token.

### INV-13 — Reproducible builds: ML stack and model identifiers pinned
**Status: MET.**
The torch / faster-whisper stack and the Whisper model identifiers are pinned/declared so `gate`
and `smoke` are reproducible run-to-run.

- **Why:** a floating model version is a silent-output-change waiting to happen — INV-2 wearing a
  dependency hat.
- **Current state:** model-id defaults are explicit constants in `config.py` (`model_size`
  `"distil-large-v3"`, `api_model` `"whisper-large-v3-turbo"`). The `[local]` ML dep is bounded:
  `faster-whisper>=1.2.0,<2.0` (lower bound aligned with the whisperx floor; upper guards a 2.x
  break — empirically dry-run-resolved). torch is **not** a direct dep here — `faster-whisper` uses
  ctranslate2, not torch — so there is nothing to pin in `[local]`. torch enters only via the future
  `[diarize]` extra, where whisperx owns the `torch~=2.8.0` pin (DDR-05).
- **Check:** `[project.optional-dependencies].local` bounds the ML stack (no bare floating `>=`);
  `model_size` / `api_model` defaults are explicit constants in `config.py`.

---

## Merge wall — what blocks `main`

### INV-4 — Green gate AND green smoke before merge
`main` advances only via a merge candidate where `make gate` exits 0 **and** `make smoke` exits 0,
each **attested by a log/artifact Frank can see**. Never merge red.

- **Enforcement reality (see CADENCE P5/P6):** CI runs `make gate` on every push and PR. CI runs
  `make smoke` **only on `main` and `workflow_dispatch`** — so smoke is *not* automatically run on a
  PR. Therefore smoke is enforced by **attestation**: before the Frank build gate, the green
  `make smoke` result (local run, or a `workflow_dispatch` run on the branch) is captured and
  attached to the PR. CI's smoke-on-`main` is the post-merge backstop, not the pre-merge gate.
- **Check:** both green results are attached/linked on the PR for the branch SHA under review.

### INV-5 — Frank SHIP precedes merge
No PR merges without a recorded Frank verdict of **SHIP** on the build under review.

- **Check:** a Frank verdict artifact exists for the branch SHA and reads SHIP.

### INV-6 — Branch-and-PR; never commit to `main`
No direct commits to `main`; `main` advances only through merged PRs. Push only via masked
inline-token HTTPS (`origin` is SSH read-only-anon).

- **Check:** `git log main` shows only PR-merge commits, no direct human commits; push commands
  mask the token.

### INV-8 — Gate is hermetic; smoke is the only real-dependency lane
`pytest -m "not smoke"` makes **zero** network calls, loads **zero** real models, and requires
**zero** real keys/GPU — mocked seams only. Only `@pytest.mark.smoke` tests touch real ffmpeg / a
real model.

- **Why:** a non-hermetic gate is flaky and unenforceable in CI; it also risks INV-7 (real keys in
  test runs).
- **Check:** `make gate` passes with network disabled and no `WHISPER_*` keys in env; the only tests
  importing `faster_whisper` or making a real `requests.post` are `smoke`-marked.

### INV-14 — The gate runs against working-tree `src/`, never a stale install copy
**Status: MET — enforced by `tests/test_install_editable.py` (gate-marked).**
The package under test resolves to **this checkout's `src/`**, so gate-attested invariants
(INV-3 / INV-4 / INV-8) prove the code under review — not a drifted, non-editable, or stale install copy.

- **Why:** a non-editable venv imports `electric_blue` from a `site-packages` *copy*; the gate then
  goes green against code that is **not** the working tree. Every behavior-preservation proof (INV-3)
  built on that green is hollow — confidently wrong, no signal. (This nearly invalidated the
  backend-seam S3 proof until it was caught.) `make dev` installs editable; the guard makes it
  enforced, not honor-system.
- **Check:** a gate-marked test asserts `Path(electric_blue.__file__).resolve()` is relative to
  `<repo>/src/` (repo root derived from the test file's own location). `make gate` — locally and in CI —
  fails on any non-editable/stale install.

### INV-12 — Authorship and judgment are separated
The role that **judges** (Frank) and the role that **runs gates/git** (the orchestrator) do not
author the implementation or tests under review. No self-certification.

- **Why:** an author grading their own work is not a gate. (The granular who-writes-what is CADENCE
  mechanics; this integrity property is inviolable.)
- **Check:** the PR shows implementation authored by `@code-executor` and tests by `@test-writer`;
  the orchestrator's own diff contains no hand-edits to `src/` or test logic.

---

## Architecture invariants — DDR-derived

### INV-9 — ACCEPTED DDR decisions are locked
No spec or forge change contradicts an ACCEPTED DDR decision. A change requires a **superseding
DDR**, referenced in the PR.

- **Check:** a PR touching a DDR-governed decision cites the superseding DDR id, or it is rejected.
- **Currently locked:** DDR-02 D1–D5 (Protocol, internal-dict registry, no AsyncBackend this phase,
  `schema_version:1` additive/data-independent, capability set without `is_async`).

### INV-10 — `schema_version` is data-independent and additive
**Status: TARGET — established by backend-seam (issue #4, slice S4). No `schema_version` is emitted
today.**
`schema_version` is an **integer literal** independent of input content, present on every JSON
output. New fields are added **without** bumping it; the integer bumps **only** on a breaking change
authorized by a DDR.

- **Current state:** the JSON payload in `outputs.py` is `{**info.to_dict(), "text", "segments"}` —
  no version field yet. Backend-seam S4 adds `"schema_version": 1` as a literal first key; until then
  this Check is unrunnable.
- **Check (once S4 lands):** the `schema_version` value is a literal first key in the `outputs.py`
  payload (not computed from data); a test asserts its presence and `int` type; any bump diff
  references a DDR.

### INV-11 — Backend dispatch only via Protocol + registry
**Status: TARGET — established by backend-seam (issue #4, slices S2–S3). Current dispatch is
`if/else`.**
Backends implement the `Backend` Protocol; dispatch is solely a registry lookup keyed by
`cfg.backend`; no reintroduced backend-name `if/else`. Adding a backend is one `_REGISTRY` entry.

- **Current state:** `backends/__init__.py` is still the `if cfg.backend == "api": … else: …`
  dispatch; the `Backend` Protocol and `_REGISTRY` do not exist yet. Backend-seam builds them.
- **Pairs with INV-2:** the registry's unknown-key `RuntimeError` is the fail-loud enforcement.
- **Check (once issue #4 lands):** `grep -rnE 'if .*backend ==' src/` finds no dispatch branching;
  new backends appear as a single `_REGISTRY` entry plus a `Backend`-conformant class.

---

## On violation

If a merge candidate trips any invariant: **do not merge.** Either fix it within the current slice,
or **HALT** and escalate to the human with the standard HALT format. An invariant is not a
guideline; "we'll fix it in a follow-up" is how the follow-up never ships.
