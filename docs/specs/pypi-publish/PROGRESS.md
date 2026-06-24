# Progress: pypi-publish (DDR-06)

## Status: COMPLETE (CODE-MERGED pending PR #23 squash-merge; NOT LIVE)

Branch: `sprint/pypi-publish` (off `main` @ bdbcdfa). Spec set merged via PR #22.
Build PR: #23. Frank SPEC gate: SHIP. Frank BUILD gate: SHIP (after one HALT — see Fix Attempts).

## Slices
- [x] S-1: pyproject.toml metadata finalization — COMPLETE
- [x] S-2: README pre-publish edit — COMPLETE (incl. Frank-HALT fix: diarize fully de-advertised)
- [x] S-3: release.yml workflow — COMPLETE
- [ ] S-4: CHANGELOG.md — DEFERRED (optional; GitHub Releases is the changelog vehicle per DDR-06 §5 / roadmap S-4)

Human operational steps (NOT forge slices — remaining for the live publish, owned by Danny):
- [ ] HOP-1: create `testpypi` + `pypi` GitHub Environments (mandatory `pypi` reviewer)
- [ ] HOP-2: TestPyPI Trusted Publisher record
- [ ] HOP-3: PyPI Trusted Publisher record
- [ ] HFS-1: push `v0.1.0` tag, verify end-to-end (incl. `tar tzf` sdist eyeball, INV-7 backstop)

## Final gate results (all green)
- `make gate`: 195 passed / 2 deselected
- `make smoke`: 1 passed (real tiny model) — INV-4 attestation
- `python -m build` + `twine check --strict dist/*`: both artifacts PASSED
- release.yml: valid YAML; `workflow_dispatch` cannot reach real PyPI (publish-pypi if-gated to tag pushes)
- INV-7 secret scan: CLEAN · ci.yml: unchanged
- @qc-agent deep review: PASS
- Frank BUILD gate: SHIP; Frank final pre-merge pass: SHIP

## Fix Attempts
| Test/File | Attempts | Last Error |
|-----------|----------|------------|
| README.md | 1 (resolved) | Frank BUILD gate HALT (INV-9): S-2 removed the diarize *install command* but left diarize advertised in the backends table (L16-22), WHISPER_BACKEND options (L97), and a diarize config block (L113-115). S-2's edit-list under-specified ("Configuration table NOT changed"); the locked de-advertise decision + INV-9 override it. Fixed: all three regions de-advertised, only the "deferred to 0.2.0" note remains; rebuild + twine --strict PASSED. Frank re-gate: SHIP. |

## Notes
- DDR-06 lands CODE-MERGED-but-NOT-LIVE. Merging publishes nothing — release.yml is tag/dispatch-triggered only; HOP-1/2/3 + the v0.1.0 tag (HFS-1) are the remaining human steps before `pip install electric-blue` is real.
- S-2's spec edit-list was incomplete on diarize de-advertisement; the locked decision (de-advertise) is authoritative over the under-specified edit-list. Worth a CADENCE/spec note: a "de-advertise X" decision must enumerate ALL surfaces (feature table, options, config block), not just install commands.
- S-4 deferred (optional). Revisit if a CHANGELOG.md file is wanted over GitHub Releases.
