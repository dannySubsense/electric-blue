# CADENCE — electric-blue

**The path to the wall.** This file defines the ordered workflow phases and the **gate** at each
phase. [INVARIANTS.md](INVARIANTS.md) is *what must be true*; this is *the route you walk and where
each truth is checked*. The Forge Advisor loads both at session start.

Every phase names its **gate** — the enforcement point where a named check renders pass/fail. A
phase with no gate is a step, not a checkpoint; the gates are where the invariants get enforced.

Authored 2026-06-14 (Reed), judgment-gated by Frank.

---

## The full loop (one sprint)

```
P0 DDR ACCEPTED ─► P1 GitHub issue ─► P2 /spec-start ──[Frank SPEC gate]──►
P3 /forge-start (per-slice build loop) ─► P5 FULL GATE ─► P6 SMOKE GATE ─►
P7 SECRET-SCAN / push-prep ──[Frank BUILD gate]──► P9 PR ─► merge
                                          ▲
                          P4 cross-DDR build order governs which sprint
```

There are **two distinct Frank gates** — spec (P2) and build (P8) — with different criteria. Do not
conflate them.

---

## P0 — DDR ACCEPTED *(upstream precondition)*
The loop starts from an **ACCEPTED** DDR. This locks the constraints the sprint must honor
(enforces **INV-9**). DDR-01 was the one-time bootstrap exception; from DDR-02 onward the full loop
is mandatory.
- **Gate:** the DDR status is ACCEPTED and its decisions are resolved.

## P1 — GitHub issue
Open a sprint issue capturing scope, acceptance criteria, and the resolved DDR decisions.
- **Gate:** issue exists and is OPEN.

## P2 — `/spec-start` → spec docs
Author `01-REQUIREMENTS`, `02-ARCHITECTURE`, `04-ROADMAP`, `05-REVIEW` (UI-SPEC `03` only when there
is a user-facing surface — omit for internal/library work). spec-reviewer drives the doc set to
internally-consistent, zero-gap.
- **Gate: Frank SPEC gate → SHIP required to proceed.** Criteria: DDR fidelity, behavior-preservation
  chain airtight, every AC has an architecture home and a verifying slice, no load-bearing gaps.

## P3 — `/forge-start` → per-slice build loop
Repeat for each slice in `04-ROADMAP`:

```
@code-executor (code, + baked-in lint/format/type)
   └► @test-writer (tests, + baked-in compile/smoke-compile)
        └► @test-runner (run suite + coverage)
             └► @qc-agent (deep spec-compliance review)
                  └► Forge Advisor FINAL CHECK ─► commit
```

Rules:
- **char-tests-first within a refactor slice** — this is the *sequencing* of **INV-3**. The
  characterization tests are written and green against the **pre-change** code before any refactor
  commit.
- each slice ends **gate-green** before the next begins; **no partial slices**.
- `PROGRESS.md` (in the spec dir) tracks slice state + fix attempts. **3+ repeats of the same fix =
  HALT to human.** The revert target on HALT is the **last gate-green slice commit**.
- **Shell-less authoring agents do not self-verify tooling.** `@test-writer` (and any agent without a
  shell) cannot run `black`/`ruff`/`pytest`; its "self-check" is a static trace. The orchestrator or
  `@test-runner` runs the tooling after authoring. The **gate's `black --check` is the trustworthy
  line**; pre-commit hooks (`make dev`) are convenience, not the enforcement point.
- **Run the gate through the editable venv** (`PATH="$PWD/.venv/bin:$PATH" make gate`); the INV-14 guard
  test fails loud if the install isn't this checkout's `src/`.
- **Gate (per slice boundary):** `make gate` green.

## P4 — Cross-DDR build order *(governs which sprint runs)*
Sprints run in order **02 → 04 → 03 → 05 → 06**. Cheap externals (Groq Batch audio verify, PyPI
name availability, dry torch/whisperx install matrix) run **serial, after the relevant Frank gate** —
never in parallel, never on a side branch. They are decision-inputs to later DDRs, not build steps.
- **Gate:** no sprint starts out of order; no external runs before its gate.

## P5 — FULL GATE
`make gate` green: `black --check .`, `ruff check .`, `pytest -m "not smoke"`. Runs in CI on every
push and PR across Python 3.10 / 3.11 / 3.12.
- **Enforces:** **INV-4** (gate half), **INV-8** (hermetic).
- **Gate:** CI `lint-test` job green for the branch SHA.

## P6 — SMOKE GATE *(named enforcement point — do not skip)*
`make smoke` green: `pytest -m smoke` against a **real tiny faster-whisper model + real ffmpeg**.

**Enforcement reality:** CI runs the `smoke` job **only on `main` and `workflow_dispatch`** — it
does **not** run automatically on a PR (deliberate: each smoke run downloads a model + installs
ffmpeg, too costly per-PR-push). Therefore, pre-merge, smoke is enforced by **attestation**:

- The orchestrator runs `make smoke` — locally, or by triggering the `smoke` job via
  `workflow_dispatch` on the sprint branch — and **captures the green result as an artifact attached
  to the PR**.
- Frank verifies that attestation at the **P8 build gate**.
- CI's automatic smoke-on-`main` is the **post-merge backstop**, not the pre-merge gate.

> **Open policy question for the Composer:** if smoke should *block* PRs automatically, add a
> `pull_request` trigger to the `smoke` job in `ci.yml` (one line) and accept the per-PR cost. Until
> then, attestation is the enforcement point. Flagged, not silently assumed.

- **Enforces:** **INV-4** (smoke half).
- **Gate:** green `make smoke` artifact attached to the PR for the branch SHA.

## P7 — SECRET-SCAN / push-prep
Before any push: run a deny-list scan over the diff (Tailscale `100.x` IPs, DB DSN, API keys, relay
creds, `notify_webhook`, `gh auth token` output). Push via **masked inline-token HTTPS**, never to
`main`.
- **Enforces:** **INV-7** (no secret pushed), **INV-6** (branch-and-PR).
- **Gate:** deny-list scan over the diff is clean; the push target is a feature branch, not `main`.

## P8 — Frank BUILD gate
Frank reviews the built slices against the spec and the invariants — reading the **code**, not
summaries.
- **Enforces:** **INV-5**.
- **Gate: Frank BUILD gate → SHIP required.** Criteria: `make gate` green (P5), `make smoke`
  attested green (P6), secret-scan clean (P7), no invariant tripped, spec ACs met. Distinct from the
  P2 spec gate.

## P9 — PR → merge
Open the PR (gate + smoke artifacts + Frank SHIP attached), merge after review. `main` advances only
here.
- **Gate:** PR carries green gate (P5), attested smoke (P6), clean scan (P7), Frank SHIP (P8).

---

## Roles *(mechanics; the integrity core is INV-12)*

| Role | Does | Does NOT |
|------|------|----------|
| **Orchestrator** (Forge/Spec Advisor) | sequence agents, run `make gate`/`make smoke`, run git, attach artifacts | hand-edit `src/` or test logic |
| **@code-executor** | write implementation per spec | judge its own output |
| **@test-writer** | write tests per spec | write implementation |
| **@test-runner** | run the suite, report | fix code |
| **@qc-agent** | deep spec-compliance review | rewrite code |
| **Frank** | judge — SHIP / NOT YET | author code or tests |

The hard line (**INV-12**): whoever judges does not author; whoever runs gates does not author. No
self-certification.

---

## On HALT
HALT — with the standard format (Reason / Blocking / Needs) — when: a spec doc is missing, an agent
reports HALTED, the same fix fails 3+ times, a human decision is required, or a scope change is
detected. On HALT during P3, the revert target is the last gate-green slice commit.
