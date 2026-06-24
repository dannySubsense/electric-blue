# Implementation Roadmap: pypi-publish

**Sprint:** pypi-publish
**DDR:** DDR-06-pypi-publish.md
**Requirements:** 01-REQUIREMENTS.md
**Architecture:** 02-ARCHITECTURE.md
**Status:** READY
**Date:** 2026-06-24
**Author:** reed (planner pass)

---

## Overview

Three forge-implementable slices produce all deliverables. One optional slice covers
CHANGELOG. Three human operational prerequisites must complete before the tag-triggered
workflow can succeed. One human-executed final step closes the sprint.

No circular dependencies. All forge slices are independent of each other and can land in
one PR or across separate PRs; the only hard ordering constraint is that all forge slices
merge to `main` and all human operational prerequisites are complete before the release tag
is pushed.

---

## Dependency Map

| Unit | Depends On | Who |
|------|------------|-----|
| S-1 pyproject.toml metadata | — | Forge |
| S-2 README pre-publish edit | — | Forge |
| S-3 release.yml workflow | — | Forge |
| S-4 CHANGELOG.md (optional) | — | Forge |
| HOP-1 GitHub Environments | S-3 authored (workflow filename known) | Human (Danny) |
| HOP-2 TestPyPI Trusted Publisher | S-3 authored (workflow filename known) | Human (Danny) |
| HOP-3 PyPI Trusted Publisher | S-3 authored (workflow filename known) | Human (Danny) |
| HFS-1 Push tag v0.1.0 | S-1, S-2, S-3 merged; S-4 if used; HOP-1, HOP-2, HOP-3 complete | Human (Danny) |

HOPs can be performed in parallel with the PR review process once the workflow filename
(`release.yml`) is known from S-3. They do not require the PR to be merged first.

---

## Slice Overview

| Slice | Type | Goal | Files |
|-------|------|------|-------|
| S-1 | Forge | pyproject.toml metadata finalization | `pyproject.toml` |
| S-2 | Forge | README pre-publish edit | `README.md` |
| S-3 | Forge | release.yml release workflow | `.github/workflows/release.yml` |
| S-4 | Forge (optional) | CHANGELOG.md initial entry | `CHANGELOG.md` |
| HOP-1 | Human | Create GitHub Environments | GitHub repo Settings |
| HOP-2 | Human | Configure TestPyPI Trusted Publisher | TestPyPI web UI |
| HOP-3 | Human | Configure PyPI Trusted Publisher | PyPI web UI |
| HFS-1 | Human | Push v0.1.0 tag and verify end-to-end | git + pip |

---

## Forge Slices

---

### S-1: pyproject.toml Metadata Finalization

**Goal:** Add all missing metadata fields required for a compliant, discoverable PyPI listing.
Fix the drift-flagged SPDX license form.

**Depends On:** —

**Files:**
- `pyproject.toml` — modify

**Changes (exact delta from architecture §Data Schemas):**

1. Change license field (drift fix — SPDX form, resolves AC US-8 last bullet):
   - BEFORE: `license = { text = "MIT" }`
   - AFTER: `license = "MIT"`

2. Add classifiers list under `[project]` (currently absent):
   ```toml
   classifiers = [
       "Development Status :: 4 - Beta",
       "Environment :: Console",
       "Intended Audience :: Developers",
       "Intended Audience :: End Users/Desktop",
       "License :: OSI Approved :: MIT License",
       "Operating System :: OS Independent",
       "Programming Language :: Python :: 3",
       "Programming Language :: Python :: 3.10",
       "Programming Language :: Python :: 3.11",
       "Programming Language :: Python :: 3.12",
       "Topic :: Multimedia :: Sound/Audio :: Speech",
       "Topic :: Utilities",
   ]
   ```

3. Add keywords list under `[project]` (currently absent):
   ```toml
   keywords = ["transcription", "whisper", "speech-to-text", "ffmpeg", "drop-folder", "watchdog"]
   ```

4. Add `[project.urls]` section (currently absent):
   ```toml
   [project.urls]
   Homepage = "https://github.com/dannySubsense/electric-blue"
   Repository = "https://github.com/dannySubsense/electric-blue"
   Issues = "https://github.com/dannySubsense/electric-blue/issues"
   ```

**What is NOT changed:**
- `[build-system]`, `[project]` base fields (`name`, `version`, `description`, `readme`,
  `requires-python`, `authors`, `dependencies`), `[project.optional-dependencies]` (all
  three extras — `local`, `diarize`, `dev`), `[project.scripts]`, `[tool.*]` sections.
- `version = "0.1.0"` stays static (locked decision D5).
- `diarize` extra stays in the file and ships in the wheel; it is not advertised at 0.1.0
  (that is README's job — S-2).

**ACs satisfied:** US-8 (all 5 bullets).

**Done When:**
- [ ] `pyproject.toml` `license` field is `"MIT"` (string form, not table form).
- [ ] `classifiers` list is present and contains all 8 required classifiers from AC US-8.
- [ ] `[project.urls]` section is present with `Homepage`, `Repository`, `Issues` all
  pointing to `https://github.com/dannySubsense/electric-blue` (Issues appends `/issues`).
- [ ] `keywords` list is present and includes all 6 required keywords from AC US-8.
- [ ] `python -m build && twine check --strict dist/*` exits 0 with no warnings (run
  locally to verify before PR; this is also enforced by the `check` job in S-3).
- [ ] `version`, `name`, extras, entry point, and all `[tool.*]` sections are unchanged
  from pre-slice state.

---

### S-2: README Pre-Publish Edit

**Goal:** Bring README to the required pre-publish state: remove all holding statements,
update install section to canonical pip commands, remove diarize as an advertised
installable at 0.1.0, retain prominent ffmpeg system-dep notice.

**Depends On:** —

**Files:**
- `README.md` — modify

**Changes (keyed to architecture §Data Schemas — README Required State):**

1. **Remove the "not yet on PyPI" block** (current lines 33–40):
   - Delete the `> **Note:** electric-blue is not yet published to PyPI. Install from source:`
     callout and the editable install code block (`git clone`, `pip install -e .`, etc.).
   - Replace with the canonical pip install commands:
     ```bash
     pip install electric-blue               # base install (api backend)
     pip install "electric-blue[local]"      # + faster-whisper for local/GPU backend
     ```

2. **Fix `your-org` placeholder** (drift fix — current clone URL):
   - If any remaining reference to `your-org/electric-blue` exists after step 1, change to
     `dannySubsense/electric-blue`. (The git clone block is being removed in step 1;
     verify no other occurrences remain.)

3. **Remove diarize as an advertised installable** (current lines 48–63 area):
   - Remove `pip install electric-blue[diarize]` as a user-facing install command.
   - Remove `pip install -e ".[diarize]"` from any code block in this section.
   - The diarize backend description may remain as informational text with a note that it
     is deferred to 0.2.0, OR the install-section subsection may be removed entirely. The
     requirement is that 0.1.0 README does NOT present diarize as an installable or
     supported feature. Either approach is acceptable; the forge chooses.

4. **Retain ffmpeg system-dep block** (current lines 42–48):
   - Keep the `**System requirement:** ffmpeg must be on PATH` notice and the
     platform-specific install commands unchanged and prominently placed (above any diarize
     or dev-setup text).

**What is NOT changed:**
- Quickstart section, Configuration table, Deploy examples, License section.
- The Development setup section (`make dev`, `make gate`, `make smoke`) — this is not
  user-facing install content and is not in scope for the pre-publish cleanup.
- The ffmpeg system requirement notice must not be removed or buried.

**ACs satisfied:** US-7 (all 4 bullets).

**Done When:**
- [ ] README does NOT contain the phrase "not yet published to PyPI" or any equivalent
  holding statement.
- [ ] README install section presents `pip install electric-blue` and
  `pip install "electric-blue[local]"` as the canonical install commands.
- [ ] README does NOT contain `pip install electric-blue[diarize]` or `pip install -e
  ".[diarize]"` as user-facing commands.
- [ ] README does NOT present diarize as an installable or supported feature at 0.1.0
  (either removed from install section, or explicitly noted as deferred to 0.2.0).
- [ ] ffmpeg system dependency notice remains present and prominently placed (before
  diarize/dev-setup content if any such content remains).
- [ ] No occurrences of `your-org` remain in the file.
- [ ] `twine check --strict dist/*` exits 0 (the long description still renders; this is
  shared verification with S-1 if both are in one PR, or can be run independently on a
  local build after S-2 alone).

---

### S-3: release.yml Release Workflow

**Goal:** Create the new release workflow implementing the five-job gate chain:
`build → check → smoke-wheel → publish-testpypi → publish-pypi`, with an additional
`workflow_dispatch` trigger that provides a TestPyPI-only rehearsal path.

**Depends On:** — (S-1 and S-2 should be in the same PR or merged before the first
real tag push, but S-3 is independently syntactically and structurally verifiable.)

**Files:**
- `.github/workflows/release.yml` — create (new file)

**Detailed job specification:** Architecture §02 `release.yml — Job Contract Specifications`
defines every job's step sequence. Implement exactly as specified. Key points:

- **Triggers:**
  - `on: push: tags: ["v[0-9]+.[0-9]+.[0-9]+"]` — release trigger; runs full chain including
    `publish-pypi`.
  - `on: workflow_dispatch: {}` — rehearsal trigger; runs
    `build → check → smoke-wheel → publish-testpypi` only. `publish-pypi` is gated by
    `if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')` and is skipped.
- **Workflow-level permissions:** `contents: read` (minimal baseline)
- **Job: `build`** — version-check first (conditioned on `github.event_name == 'push'` so
  it skips on `workflow_dispatch`; uses `tomllib` stdlib, Python 3.12, strips `v` prefix from
  `GITHUB_REF_NAME`), then `python -m build`, then upload `dist/` artifact.
- **Job: `check`** — download artifact, run `twine check --strict dist/*`.
  (Use `--strict`; confirmed safe with SPDX + License-classifier combo.)
- **Job: `smoke-wheel`** — checkout (for tests dir), download artifact, setup Python 3.12,
  `apt-get update && apt-get install -y ffmpeg`, install `"${WHEEL}[local]"` via glob
  variable, run `pytest -m smoke`. Does NOT use `pip install -e .` or `make dev`.
- **Job: `publish-testpypi`** — `environment: testpypi`,
  `permissions: id-token: write / contents: read`, download artifact, upload via
  `pypa/gh-action-pypi-publish@release/v1` with
  `repository-url: https://upload.test.pypi.org/legacy/` (canonical URL — drift fix),
  then post-upload install check using BOTH
  `--index-url https://test.pypi.org/simple/` AND
  `--extra-index-url https://pypi.org/simple/` (drift fix — needed for watchdog/requests
  transitive deps absent on TestPyPI). Runs on both tag and `workflow_dispatch` triggers.
- **Job: `publish-pypi`** — `environment: pypi`,
  `permissions: id-token: write / contents: read`, download artifact, upload via
  `pypa/gh-action-pypi-publish@release/v1` with NO `repository-url` (defaults to real
  PyPI), `needs: [publish-testpypi]`,
  `if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')`.

**All action pins:** `actions/checkout@v4`, `actions/setup-python@v5`,
`actions/upload-artifact@v4`, `actions/download-artifact@v4`,
`pypa/gh-action-pypi-publish@release/v1`.

**Drift fixes applied in this slice:**
- Use `https://upload.test.pypi.org/legacy/` (not `https://test.pypi.org/legacy/`) for
  TestPyPI upload URL.
- Add `--extra-index-url https://pypi.org/simple/` to post-TestPyPI install check.

**What is NOT changed:**
- `.github/workflows/ci.yml` — untouched (locked constraint; ci.yml is branch-triggered,
  release.yml is tag-triggered; they are orthogonal and coexist).

**ACs satisfied:** US-1 (all 4), US-2 (all 4), US-3 (all 5), US-4 (all 3), US-9 (all 3).

**Done When:**
- [ ] `.github/workflows/release.yml` exists at that exact path.
- [ ] Workflow has both a `push: tags: v[0-9]+.[0-9]+.[0-9]+` trigger AND a `workflow_dispatch`
  trigger.
- [ ] Job graph matches `build → check → smoke-wheel → publish-testpypi → publish-pypi`
  enforced via `needs:` declarations.
- [ ] `build` job version-check step is conditioned on `github.event_name == 'push'` (skips
  on `workflow_dispatch` rehearsal runs).
- [ ] `build` job performs version-check before artifact production and exits non-zero if
  tag version != pyproject.toml version (on tag-triggered runs).
- [ ] `smoke-wheel` job runs `apt-get update` before `apt-get install -y ffmpeg`.
- [ ] `smoke-wheel` job installs from wheel glob variable (not from source or `-e .`).
- [ ] `publish-testpypi` uses `repository-url: https://upload.test.pypi.org/legacy/`.
- [ ] Post-TestPyPI install check includes both `--index-url` and `--extra-index-url`.
- [ ] Both publish jobs declare `permissions: id-token: write` and `environment:` matching
  their respective GitHub Environment names (`testpypi`, `pypi`).
- [ ] `publish-pypi` has `needs: [publish-testpypi]` (mandatory gate).
- [ ] `publish-pypi` has `if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')`
  so it is skipped on `workflow_dispatch` runs.
- [ ] A `workflow_dispatch` run executes `build → check → smoke-wheel → publish-testpypi`
  and stops; `publish-pypi` is skipped.
- [ ] No `PYPI_TOKEN`, `TEST_PYPI_TOKEN`, or equivalent API key secret is referenced
  anywhere in the file.
- [ ] YAML is syntactically valid (passes `yamllint` or equivalent; GitHub Actions
  workflow validation does not require a live run — reviewable statically).
- [ ] `ci.yml` is unchanged (diff shows no modifications to that file).

---

### S-4: CHANGELOG.md Initial Entry (Optional)

**Goal:** Provide a human-authored change record for the 0.1.0 release.

**Depends On:** S-1, S-2 (to know what is in scope for 0.1.0)

**Files:**
- `CHANGELOG.md` — create (new file)

**Scope:** A minimal `## [0.1.0] — 2026-??-??` entry listing the user-visible changes in
this release. No tooling automation; no towncrier or changie. Content is human-authored.
GitHub Releases may be used instead of or in addition to this file; either satisfies DDR-06
pre-publish checklist item 5.

**If skipped:** the GitHub Release note authored at the time of the HFS-1 tag push is an
acceptable substitute. This slice does not gate any other slice or HOP.

**Done When:**
- [ ] `CHANGELOG.md` exists with at minimum a `## [0.1.0]` section covering the shipped
  features (local extra, pip install surface, release workflow).
- OR this slice is explicitly skipped and a GitHub Release note is committed to be authored
  at tag push time.

---

## Human Operational Prerequisites

These steps require repo-owner access (GitHub and PyPI/TestPyPI accounts). They cannot be
automated or performed by the forge. They are NOT optional for the first publish — the
tag-triggered workflow will fail with a 403 auth error if any of them is incomplete.

HOPs can be performed in parallel with forge PR work (the workflow filename `release.yml`
is fixed and known from S-3). They do not require the PR to be merged first.

---

### HOP-1: Create GitHub Environments

**Who:** Danny (repo owner)
**Where:** `https://github.com/dannySubsense/electric-blue/settings/environments`
**When:** Before HFS-1 (tag push). Can be done any time after S-3 is drafted.

**Steps:**
1. Create environment named `testpypi` (exact spelling, all lowercase).
2. Create environment named `pypi` (exact spelling, all lowercase).
3. **Mandatory for 0.1.0:** Add a required reviewer on the `pypi` environment. This is the
   human gate between a green pipeline and an immutable PyPI artifact — the sole barrier
   preventing an unreviewed tag push from immediately publishing a permanent release to PyPI.
   The `testpypi` environment does NOT require a reviewer; it is the rehearsal target.

**Done When:**
- [ ] Environment `testpypi` exists in repo Settings.
- [ ] Environment `pypi` exists in repo Settings.
- [ ] Required reviewer is set on the `pypi` environment (mandatory, not optional).

---

### HOP-2: Configure TestPyPI Trusted Publisher

**Who:** Danny (TestPyPI account owner)
**Where:** `https://test.pypi.org/manage/account/publishing/`
**When:** Before HFS-1 (tag push). Can be done any time after S-3 is drafted.
**Depends On:** HOP-1 complete (environment names must be known and finalized).

**Steps:** Add a new pending publisher:
- PyPI project name: `electric-blue`
- Owner: `dannySubsense`
- Repository name: `electric-blue`
- Workflow filename: `release.yml`
- Environment name: `testpypi`

**Done When:**
- [ ] Pending publisher record exists on TestPyPI with the exact values above.
- [ ] All five fields match exactly (case-sensitive; a mismatch causes a 403 at publish
  time with a confusing auth error).

---

### HOP-3: Configure PyPI Trusted Publisher

**Who:** Danny (PyPI account owner)
**Where:** `https://pypi.org/manage/account/publishing/`
**When:** Before HFS-1 (tag push). Can be done any time after S-3 is drafted.
**Depends On:** HOP-1 complete (environment names must be known and finalized).

**Steps:** Add a new pending publisher:
- PyPI project name: `electric-blue`
- Owner: `dannySubsense`
- Repository name: `electric-blue`
- Workflow filename: `release.yml`
- Environment name: `pypi`

**Note:** A "pending publisher" on PyPI allows the first upload to create the project
automatically. No manual project creation is required beforehand.

**Done When:**
- [ ] Pending publisher record exists on PyPI with the exact values above.
- [ ] All five fields match exactly (case-sensitive).

---

## Human Final Step

### HFS-1: Push Tag v0.1.0 and Verify End-to-End

**Who:** Danny
**When:** After S-1, S-2, S-3 merged to `main`; S-4 complete (or explicitly skipped);
HOP-1, HOP-2, HOP-3 all confirmed complete.
**This is the live/immutable step. PyPI releases cannot be deleted.**

**Pre-flight checklist (human review before pushing tag):**
- [ ] S-1, S-2, S-3 are merged to `main` (and S-4 if used).
- [ ] HOP-1, HOP-2, HOP-3 are complete and verified.
- [ ] `pyproject.toml` `version` field is `"0.1.0"`.
- [ ] Local sanity: `python -m build && twine check --strict dist/*` passes.
- [ ] sdist content eyeball: `tar tzf dist/*.tar.gz` — confirm no stray secrets, `.env`, or
  unexpected paths are bundled. Backstops INV-7 (the only secret control is human review;
  there is no automated sdist scan — see Accepted Residuals).
- [ ] README does not contain the "not yet published" holding statement.
- [ ] README does not present diarize as an installable at 0.1.0.
- [ ] Smoke passes on current `main` (or was attested for the release PR — INV-4).
- [ ] (Optional) A `workflow_dispatch` rehearsal run has been executed against the release
  branch/main to confirm `publish-testpypi` succeeds before committing to a real tag push.

**Tag push:**
```bash
git tag v0.1.0
git push origin v0.1.0
```

**Observe workflow run at:** `https://github.com/dannySubsense/electric-blue/actions`

**Post-publish verification (US-5 ACs):**
```bash
python -m venv /tmp/eb-verify && source /tmp/eb-verify/bin/activate
pip install electric-blue
electric-blue --help   # must exit 0 with usage message
```

**Done When:**
- [ ] All five workflow jobs (`build`, `check`, `smoke-wheel`, `publish-testpypi`,
  `publish-pypi`) completed successfully in the GitHub Actions run.
- [ ] `pip install electric-blue` succeeds in a clean virtualenv.
- [ ] `electric-blue --help` exits 0.
- [ ] Package is visible at `https://pypi.org/project/electric-blue/`.

---

## PR Workflow

The three forge slices (S-1, S-2, S-3) and the optional S-4 may land in a single PR or
separate PRs. Regardless of batching, the PR must satisfy all merge-wall invariants before
merging to `main`:

- **INV-4:** `make gate` exits 0 AND `make smoke` exits 0, both attested (smoke run on
  branch or `workflow_dispatch` — CI does not auto-run smoke on PRs).
- **INV-5:** Frank SHIP verdict recorded for the branch SHA.
- **INV-6:** Changes via PR only; no direct commits to `main`.
- **INV-7:** No secrets, Tailscale IPs, or personal tokens appear in any new or modified
  file. `release.yml` must reference no API key secrets.

`ci.yml` will run on the PR branch push (branch trigger). `release.yml` will NOT run on
the PR (tag trigger only; `workflow_dispatch` is available but must be manually triggered).
There is no CI overlap (see Architecture §Integration Points).

---

## Accepted Residuals (0.1.0)

**No automated sdist secret/content scan (G-6):** The publish pipeline validates functionality
and metadata but performs no automated scan of sdist contents for secrets, credentials, or
sensitive file paths. The control against publishing a secret in the sdist is INV-7 human PR
review (mandated above). This is a consciously accepted residual for 0.1.0. An optional future
improvement — an sdist content check step before `publish-testpypi` — is deferred.

**Smoke-wheel runs on Python 3.12 only (G-8):** Classifiers advertise Python 3.10, 3.11, and
3.12, but `smoke-wheel` runs only on Python 3.12. Low risk for a pure-Python wheel. A
smoke-wheel python matrix is a documented optional future improvement, not added for 0.1.0.

---

## Deferred (Not This Sprint)

- `diarize` extra as advertised public surface — deferred to 0.2.0; gated on a passing
  `pytest -m diarize_smoke` on a host with real dependency installed.
- `ffmpeg` extra or `imageio-ffmpeg` bundling — document-only mitigation (locked D8).
- `hatch-vcs` dynamic versioning — deferred; static version is locked decision D5.
- CHANGELOG tooling automation (changie, towncrier) — deferred; manual entry is sufficient.
- GitHub Release object creation in `release.yml` — not in scope for this sprint.
- PyPI yank automation — deferred.
- Multi-platform wheel builds (cibuildwheel) — not in scope; pure-Python wheel is correct.
- `dev` extra as user-facing README content — explicitly excluded from public surface.
- Changes to `ci.yml` — locked out of scope; ci.yml is untouched.
- Automated sdist content scan for secrets — deferred; see Accepted Residuals above.
- Smoke-wheel Python matrix (3.10/3.11/3.12) — deferred; see Accepted Residuals above.

---

## Requirement Coverage Summary

| User Story | Covered by Slice(s) |
|-----------|---------------------|
| US-1 Release by tag push | S-3 (trigger + job order) |
| US-2 Build validation gate | S-3 (build, check, smoke-wheel jobs) |
| US-3 TestPyPI gate | S-3 (needs: chain; publish-testpypi → publish-pypi) |
| US-4 Tag/version consistency | S-3 (version-check step in build job; tag runs only) |
| US-5 Install via pip | S-1 (metadata), S-3 (publish), HFS-1 (verified) |
| US-6 Local extra installable | S-1 (extra unchanged; URL updated), S-2 (README advertises it) |
| US-7 ffmpeg docs + README cleanup | S-2 |
| US-8 Accurate PyPI metadata | S-1 |
| US-9 No long-lived credentials | S-3 (OIDC only; no secrets), HOP-2/3 (Trusted Publisher) |
