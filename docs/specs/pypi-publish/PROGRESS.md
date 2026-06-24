# Progress: pypi-publish (DDR-06)

## Status: IN_PROGRESS

Branch: `sprint/pypi-publish` (off `main` @ bdbcdfa). Spec set merged via PR #22.
Frank SPEC gate: SHIP. Forge BUILD gate: pending.

## Slices
- [x] S-1: pyproject.toml metadata finalization — COMPLETE
- [x] S-2: README pre-publish edit — COMPLETE (+ Frank HALT fix: diarize fully de-advertised — table/options/config block removed; only L43 "deferred to 0.2.0" remains; rebuild+twine --strict PASSED)
- [x] S-3: release.yml workflow — COMPLETE

Consolidated verification (all green): gate 195 passed/2 deselected; build exit 0;
twine check --strict PASSED both artifacts; release.yml YAML OK; ci.yml unchanged;
INV-7 secret scan CLEAN; INV-4 `make smoke` 1 passed (real tiny model). Next: @qc-agent → Frank BUILD gate → PR.
- [ ] S-4: CHANGELOG.md — DEFERRED (optional; GitHub Releases is the changelog vehicle per DDR-06 §5 / roadmap S-4)

Human operational steps (NOT forge slices — carried for the live publish):
- [ ] HOP-1: create `testpypi` + `pypi` GitHub Environments (mandatory `pypi` reviewer)
- [ ] HOP-2: TestPyPI Trusted Publisher record
- [ ] HOP-3: PyPI Trusted Publisher record
- [ ] HFS-1: push `v0.1.0` tag, verify end-to-end (incl. `tar tzf` sdist eyeball)

## Current
Slice: S-1
Step: @code-executor
Last updated: 2026-06-24

## Verification lane (adaptation)
These are declarative-config slices, not runtime code. Per-slice verification:
- S-1: `make gate` green (editable install + hermetic suite still pass) + `python -m build && twine check --strict dist/*` exit 0.
- S-2: grep assertions (no holding statement, canonical pip commands, no diarize installable, ffmpeg notice present, no `your-org`) + `twine check --strict` long-description renders.
- S-3: YAML parses + structural assertions (dual trigger, `needs:` chain, version-check `push`-gated, `smoke-wheel` apt-get update + wheel-glob install, canonical TestPyPI URL, `--extra-index-url`, `id-token: write` + `environment:` on publish jobs, `publish-pypi` needs+if-gated, no token secrets, `ci.yml` untouched).

## Fix Attempts
| Test/File | Attempts | Last Error |
|-----------|----------|------------|
| README.md | 1 | Frank BUILD gate HALT (INV-9): S-2 removed the diarize *install command* but left diarize advertised in the backends table (L16-22), WHISPER_BACKEND options (L97), and a diarize config block (L113-115). S-2's edit-list under-specified (it said "Configuration table NOT changed"); the locked de-advertise decision + INV-9 override it. Completing the de-advertisement. pyproject diarize extra stays in the wheel. |

## Notes
- S-4 deferred (optional). Revisit at end-of-feature if a CHANGELOG.md file is wanted over GitHub Releases.
- All three forge slices touch disjoint files; landing in a single PR.
