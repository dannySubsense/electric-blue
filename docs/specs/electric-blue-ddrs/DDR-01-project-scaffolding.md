# DDR-01 — Project Scaffolding

- **Status:** PROPOSED (awaiting Danny approval)
- **Author:** reed
- **Date:** 2026-06-14
- **Sprint (on approval):** `project-scaffolding`
- **Supersedes:** —

---

## Context

`electric-blue` exists as a working single-file homelab utility (`transcribe_watch.py`)
plus deployment artifacts (`transcribe.service`, `install_windows_service.ps1`) and a
homelab/ASUS-specific `README.md`. The GitHub repo (`dannySubsense/electric-blue`) is now
**public and empty**. Before any feature work, the project needs a correct public-project
skeleton and a runnable quality gate so that every subsequent sprint has something to build
and verify against.

This is the bootstrap sprint. From **DDR-02 onward**, all work flows through the standard
loop: DDR → GitHub issue → `/spec-start` → Frank gate → `/forge-start` → Frank gate → PR.

## Principle

Do it correctly, not conveniently. The existing worker is **decomposed into a proper
installable package** rather than left as a loose root script. The refactor is guarded:
the test suite (including a real transcription smoke run) is written in the same sprint and
must pass **before** the public push, so the decomposition cannot silently change behavior.

---

## Decision

### 1. Target structure

```
electric-blue/
├── .github/workflows/ci.yml          # push/PR: black --check + ruff + pytest; smoke job on main/dispatch
├── deploy/                           # deployment examples, generalized from homelab originals
│   ├── transcribe.service            #   systemd unit template (API backend)
│   └── install_windows_service.ps1   #   Windows/NSSM installer (local GPU)
├── docs/
│   ├── homelab/README.md             # archived original README (R630/ASUS), kept verbatim
│   └── specs/electric-blue-ddrs/
│       └── DDR-01-project-scaffolding.md
├── src/electric_blue/                # worker decomposed along its existing seams
│   ├── __init__.py                   #   version + public exports
│   ├── __main__.py                   #   python -m electric_blue → cli.main
│   ├── cli.py                        #   argparse; build Config; dispatch once/watch/file
│   ├── config.py                     #   frozen Config dataclass + Config.from_env()
│   ├── models.py                     #   Segment, TranscriptInfo dataclasses
│   ├── audio.py                      #   ffmpeg extraction (wav / compressed mp3)
│   ├── outputs.py                    #   fmt_ts + txt/srt/vtt/json writers
│   ├── notify.py                     #   best-effort webhook ping
│   ├── watcher.py                    #   ensure_dirs, is_stable, process/handle, run_once/run_watch
│   └── backends/
│       ├── __init__.py               #   transcribe(cfg, src) → dispatch local|api
│       ├── local.py                  #   faster-whisper backend (lazy model load)
│       └── api.py                    #   OpenAI-compatible /audio/transcriptions backend
├── tests/
│   ├── conftest.py                   # fixtures: tmp dirs, synthetic audio, fake backend
│   ├── test_config.py                # env parsing (hermetic)
│   ├── test_outputs.py               # fmt_ts + all four writers (hermetic)
│   ├── test_watcher.py               # is_stable, ensure_dirs, handle routing (monkeypatched)
│   └── test_smoke.py                 # REAL run: ffmpeg clip → local `tiny` → 4 outputs (marker: smoke)
├── .gitignore                        # in place
├── .pre-commit-config.yaml           # black + ruff hooks
├── CONTRIBUTING.md                   # DDR→spec→Frank→forge workflow + gate commands
├── LICENSE                           # MIT
├── Makefile                          # make gate = black --check + ruff + pytest ; make smoke
├── README.md                         # new, generalized, public-facing (evolving)
└── pyproject.toml                    # hatchling; deps + [local]/[dev] extras; black/ruff/pytest config
```

### 2. Packaging

- **Layout:** `src/` layout (prevents accidental import of the source tree; standard for
  testable, installable packages).
- **Build backend:** `hatchling`.
- **Python:** `>=3.10`.
- **Entry point:** console script `electric-blue = electric_blue.cli:main` and
  `python -m electric_blue`. The old `transcribe_watch.py` invocation is retired; deploy
  examples are updated to the new entry point.
- **Dependencies:**
  - base: `watchdog>=3`, `requests>=2.28` (watch mode + webhook/api are core to the tool)
  - extra `local`: `faster-whisper>=1.0`
  - extra `dev`: `pytest>=8`, `black>=24`, `ruff>=0.4`, `pre-commit`
- **System dependency:** `ffmpeg` (documented; not pip-installable).

### 3. Decomposition (behavior-preserving)

`transcribe_watch.py`'s logic is split along the section banners it already carries
(config, audio, backends, outputs, file handling, notify, CLI). The one structural change:
env reads move from import-time module globals into a frozen `Config` dataclass
(`Config.from_env()`) threaded through the functions — this is what makes the code testable
without monkeypatching `os.environ` and re-importing. No transcription behavior changes.

### 4. Quality gate

- **Gate command (`make gate`):** `black --check .` + `ruff check .` + `pytest -m "not smoke"`.
- **Smoke (`make smoke`):** `pytest -m smoke` — generates a short clip with ffmpeg, runs the
  **real** local `tiny` backend, asserts a non-empty `TranscriptInfo` and that all four
  output files are written. Skips with a clear reason if ffmpeg/faster-whisper are absent.
- **CI (`.github/workflows/ci.yml`):**
  - job `lint-test` (matrix 3.10–3.12): install `.[dev]`, run the gate (`not smoke`).
  - job `smoke` (push to `main` + `workflow_dispatch`): install ffmpeg + `.[local,dev]`,
    run `pytest -m smoke` with the real `tiny` model.

### 5. README + homelab archival

- Original `README.md` (R630/ASUS-specific) → `docs/homelab/README.md`, **verbatim** (your
  reference copy).
- New root `README.md`: generalized, public-facing, evolving — what it is, install (pip +
  ffmpeg), quickstart (drop-folder + CLI), backend table (generic "a server" / "a GPU box",
  not R630/ASUS), config env table, pointer to `deploy/` examples, license.
- `transcribe.service` and `install_windows_service.ps1` → `deploy/` as generalized
  example templates (placeholders for paths/users instead of `/opt/transcribe` / `dclarke`).

### 6. License

MIT (confirmed with Danny).

---

## Sequencing (guards the refactor)

1. Scaffold packaging + tooling (`pyproject.toml`, configs) — no behavior change.
2. Move code into `src/electric_blue/` decomposed; introduce `Config`.
3. Write the test suite, including the real smoke test.
4. **Run `make gate` and `make smoke` — both green — BEFORE any push.**
5. Archive homelab docs, write the new README, deploy examples.
6. Initial commit → PR → merge to `main`. Subsequent sprints branch off `main`.

## Risks

- **Behavior drift during decomposition** → mitigated by the smoke test + hermetic unit
  tests run before push.
- **CI smoke cost** (model download each run) → isolated to its own job, not on every push.
- **Entry-point change** breaks anyone calling `transcribe_watch.py` → acceptable on a fresh
  public repo; deploy examples updated; noted in README.

## Open questions for Danny

1. License = **MIT** — confirmed. (Recorded; flag if changed.)
2. Should `deploy/` examples stay in the public repo as generalized templates, or be archived
   under `docs/homelab/` as your-setup-only? (Proposed: keep generalized in `deploy/` — they
   are genuinely useful to public users.)
3. Ceremony level for THIS bootstrap sprint: full `/spec-start` (5 spec docs) + Frank +
   `/forge-start`, or treat scaffolding as the documented bootstrap implemented via forge
   subagents against this DDR (no separate 5-doc spec), with Frank gating the result? Either
   is defensible; the bootstrap paradox (forge needs a harness that doesn't exist yet) makes
   the lean path reasonable **for this sprint only**.
