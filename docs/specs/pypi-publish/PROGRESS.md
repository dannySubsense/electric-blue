# Progress: pypi-publish (DDR-06)

## Status: CODE-MERGED @ `a497c0c` (PR #22 spec, #23 build, #24 corrective); **LIVE TRACK KILLED 2026-06-25** — will NOT ship

> 🛑 **The LIVE/publish track was killed by Danny on 2026-06-25** as agent-invented ceremony (homelab
> leaf utility, no public audience). Do NOT run `RUNBOOK-LIVE.md`. The code stays CODE-MERGED and
> harmless; revive only on explicit request. See the RUNBOOK banner + LORE `31060675`. The rest of
> this file is the historical build record, retained as-is.

Spec set merged via PR #22 (`bdbcdfa`). Build merged via PR #23 (`c184c7a`). Corrective fix +
live runbook merged via PR #24 (`a497c0c`). Frank SPEC gate: SHIP. Frank BUILD gate: SHIP (after
one HALT — see Fix Attempts). Frank runbook review: SHIP (after one FIX — see Corrective fix).

**(HISTORICAL — LIVE TRACK KILLED, see banner above.)** To go LIVE, follow `RUNBOOK-LIVE.md` (this dir) — HOP-1/2/3 (Trusted Publishers + GitHub
Environments, mandatory `pypi` reviewer) → `workflow_dispatch` rehearsal → tag `v0.1.0` + approve
reviewer gate → verify. Merging published nothing; release.yml is tag/dispatch-only.

## Corrective fix (PR #24) — post-build defect found in Frank's runbook review
The merged `release.yml` would wedge the rehearse→release flow: a `workflow_dispatch` rehearsal
uploads `0.1.0` to TestPyPI; the real tag run re-runs `publish-testpypi` with identical filenames
and 400s — and Warehouse permanently reserves a filename once uploaded (deletion does NOT free it),
so `publish-pypi` (needs publish-testpypi) never reaches the reviewer gate. **Fix:** `skip-existing:
true` on the TestPyPI publish step only (real PyPI stays strict). R-1 residual is now RESOLVED — no
manual TestPyPI delete; the flow is idempotent. Also added `RUNBOOK-LIVE.md`; corrected 02-ARCHITECTURE
§publish-testpypi + §TestPyPI-conflict to the skip-existing model.

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
