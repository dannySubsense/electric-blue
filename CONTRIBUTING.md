# Contributing to electric-blue

## Workflow

All feature work follows this loop:

1. **DDR** — a Decision Record is written in `docs/specs/electric-blue-ddrs/` and approved.
2. **GitHub Issue** — the DDR outcome is captured as an issue.
3. **`/spec-start`** — Forge Advisor reads the DDR and produces the five spec documents.
4. **Frank gate** — specs are reviewed before implementation begins.
5. **`/forge-start`** — Forge Advisor hands a contract to Code Executor sub-agents.
6. **Frank gate** — implementation is reviewed before merge.
7. **PR → merge to `main`**.

## Gate commands

```bash
# Install in editable mode with dev tools
pip install -e ".[dev]"

# Format code
make fmt

# Run the full quality gate (must be green before any push)
make gate
# Equivalent to:
#   black --check .
#   ruff check .
#   pytest -m "not smoke"

# Run the real end-to-end smoke test (requires ffmpeg + faster-whisper)
make smoke
# Equivalent to:
#   pytest -m smoke
```

## Adding a backend

1. Create `src/electric_blue/backends/<name>.py` implementing `transcribe_<name>(cfg, src) -> (segments, info)`.
2. Register it in `src/electric_blue/backends/__init__.py`.
3. Add a corresponding DDR documenting the decision.

## Env vars

See the config table in `README.md`. All configuration flows through `Config.from_env()` —
no module-level globals.

## Deploy examples

`deploy/` contains generalized service templates. Edit placeholders before use:

- `<INSTALL_DIR>` — the directory where the package is installed (e.g. `/opt/electric-blue`)
- `<SERVICE_USER>` — the OS user that should own the process
