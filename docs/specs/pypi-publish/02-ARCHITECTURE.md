# Architecture: pypi-publish

**Sprint:** pypi-publish
**DDR:** DDR-06-pypi-publish.md
**Requirements:** 01-REQUIREMENTS.md
**Status:** DRAFT
**Date:** 2026-06-24
**Author:** reed (architect pass)

---

## Overview

Three deliverables satisfy all 32 acceptance criteria:

1. **`pyproject.toml`** — metadata additions (classifiers, URLs, keywords, SPDX license). No
   structural changes; existing extras, entry point, and hatchling config are correct.
2. **`.github/workflows/release.yml`** — new workflow; tag-triggered five-job gate chain with
   an additional `workflow_dispatch` trigger for TestPyPI-only rehearsal runs.
3. **`README.md`** — pre-publish edit (remove "not yet on PyPI" note, update install section,
   remove `diarize` from advertised public surface).

`ci.yml` is unchanged. It triggers on `push: branches: ["**"]` which matches only branch refs, not
tag refs — there is no conflict or overlap with the new `push: tags:` trigger in `release.yml`.

---

## Components

| Component | Type | Responsibility | Location |
|-----------|------|----------------|----------|
| `pyproject.toml` | config | Packaging metadata; wheel build config | `/pyproject.toml` |
| `release.yml` | CI workflow | Tag-triggered release pipeline: build, validate, smoke, publish | `.github/workflows/release.yml` |
| `README.md` | docs | PyPI long description (via `readme = "README.md"`); pre-publish cleanup | `/README.md` |
| TestPyPI Trusted Publisher | external config | OIDC publisher record; one-time human setup | TestPyPI web UI |
| PyPI Trusted Publisher | external config | OIDC publisher record; one-time human setup | PyPI web UI |
| `testpypi` GitHub Environment | external config | Scopes `id-token: write` to TestPyPI publish job | GitHub repo settings |
| `pypi` GitHub Environment | external config | Scopes `id-token: write` to PyPI publish job | GitHub repo settings |

---

## Data Schemas

### pyproject.toml — Exact Delta

The following fields are added or changed. Everything else (`build-system`, `[project]` base
fields, `[project.optional-dependencies]`, `[project.scripts]`, `[tool.*]`) is unchanged.

```toml
# [project] section — change license field
# BEFORE (current):  license = { text = "MIT" }
# AFTER (SPDX form required by PEP 639; hatchling supports both):
license = "MIT"

# [project] section — add classifiers (currently absent)
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

# [project] section — add keywords (currently absent)
keywords = ["transcription", "whisper", "speech-to-text", "ffmpeg", "drop-folder", "watchdog"]

# New section (currently absent):
[project.urls]
Homepage = "https://github.com/dannySubsense/electric-blue"
Repository = "https://github.com/dannySubsense/electric-blue"
Issues = "https://github.com/dannySubsense/electric-blue/issues"
```

The `diarize` extra (`whisperx>=3.8.6,<4.0`) stays in the file and ships in the wheel. It is NOT
advertised in README or PyPI long description at 0.1.0.  The `dev` extra is unchanged and is NOT
advertised as user-facing.

### README.md — Required State (Pre-Publish)

The README doubles as the PyPI long description (`readme = "README.md"` with hatchling inferring
`text/markdown`). The required state before pushing the release tag:

| Location in current README | Required change |
|---------------------------|-----------------|
| Lines 33–40: "Note: electric-blue is not yet published to PyPI. Install from source:" + editable install commands | Replace entirely with `pip install electric-blue` (base) and `pip install "electric-blue[local]"` (local extra) as canonical install commands |
| Lines 48–63: "### diarize backend" subsection with `pip install electric-blue[diarize]` | Remove `pip install electric-blue[diarize]` as an advertised user command. The diarize backend exists but is not public surface at 0.1.0; this section must not present it as a `pip install` option |
| ffmpeg system dependency block (lines 42–48) | Retain as-is; it must remain prominent (above diarize and dev-setup sections) |

`twine check dist/*` will validate that the README renders without error after these edits.

### release.yml — Job Contract Specifications

The workflow file is a new file at `.github/workflows/release.yml`.

#### Trigger and Workflow-Level Permissions

```yaml
name: Release

on:
  push:
    tags:
      - "v[0-9]+.[0-9]+.[0-9]+"
  workflow_dispatch: {}

permissions:
  contents: read
```

Two triggers are defined:

- **`push: tags: v[0-9]+.[0-9]+.[0-9]+`** — the release trigger. Runs the full five-job chain
  including `publish-pypi`. Every real release starts here.
- **`workflow_dispatch`** — a TestPyPI-only rehearsal path. Runs
  `build → check → smoke-wheel → publish-testpypi` and STOPS. `publish-pypi` is gated by an
  `if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')` condition and is
  skipped on any `workflow_dispatch` run. Real PyPI is never touched in a rehearsal run.

Workflow-level `permissions: contents: read` sets a minimal baseline. Publish jobs override this
to add `id-token: write`; all other jobs inherit the read-only baseline (no OIDC token issued).

#### Job: `build`

**Purpose:** version-check (fail-fast before any artifact is produced), then build wheel + sdist.

```yaml
build:
  name: build
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4

    - uses: actions/setup-python@v5
      with:
        python-version: "3.12"

    - name: Verify tag matches declared version
      if: github.event_name == 'push'
      run: |
        TAG_VERSION="${GITHUB_REF_NAME#v}"
        PKG_VERSION=$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
        echo "Tag version:      $TAG_VERSION"
        echo "Declared version: $PKG_VERSION"
        if [ "$TAG_VERSION" != "$PKG_VERSION" ]; then
          echo "ERROR: tag $GITHUB_REF_NAME does not match pyproject.toml version $PKG_VERSION"
          exit 1
        fi

    - name: Build wheel and sdist
      run: |
        pip install build
        python -m build

    - uses: actions/upload-artifact@v4
      with:
        name: dist
        path: dist/
```

`GITHUB_REF_NAME` on a tag push is the tag name (e.g., `v0.1.0`). The `#v` shell parameter
expansion strips the leading `v`. `tomllib` is stdlib from Python 3.11+; Python 3.12 is used so
no backport is needed. The version-check step is conditioned on `github.event_name == 'push'`
so that `workflow_dispatch` rehearsal runs (where `GITHUB_REF_NAME` is a branch name, not a
tag) skip it and proceed directly to the build. On tag-triggered runs the check runs before
`python -m build` — no artifact is produced if the check fails (AC US-4).

**Outputs:** GitHub Actions artifact named `dist` containing `dist/*.whl` and `dist/*.tar.gz`.

#### Job: `check`

**Purpose:** validate wheel metadata and long description rendering.

```yaml
check:
  name: check
  needs: [build]
  runs-on: ubuntu-latest
  steps:
    - uses: actions/download-artifact@v4
      with:
        name: dist
        path: dist/

    - uses: actions/setup-python@v5
      with:
        python-version: "3.12"

    - name: Check metadata and long description
      run: |
        pip install twine
        twine check --strict dist/*
```

`twine check` validates that the long description (README.md content baked into sdist metadata)
renders without errors and that all required metadata fields are present and well-formed. Plain
`twine check` returns 0 on warnings; only `--strict` causes a non-zero exit on warnings (by
treating them as errors). `--strict` fails on README/long-description rendering warnings emitted
by `readme_renderer`, NOT on license or classifier metadata fields.

**Confirmed:** the SPDX `license = "MIT"` expression combined with the
`License :: OSI Approved :: MIT License` classifier passes `twine check --strict` under hatchling
(build 1.5.0, twine 6.2.0, setuptools 82; empirically validated 2026-06-24 — both artifacts
built, `twine check --strict` exited 0 with no warnings). The license/classifier combination is
not a `--strict` risk.

**Rationale for `--strict`:** catches README rendering failures (broken Markdown, RST directives,
etc.) that would display as broken long descriptions on the live PyPI page. Mandatory in S-3.

#### Job: `smoke-wheel`

**Purpose:** install the built wheel (not source, not editable) and run `pytest -m smoke` against
the installed package.

```yaml
smoke-wheel:
  name: smoke-wheel
  needs: [check]
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4

    - uses: actions/download-artifact@v4
      with:
        name: dist
        path: dist/

    - uses: actions/setup-python@v5
      with:
        python-version: "3.12"

    - name: Install ffmpeg
      run: |
        sudo apt-get update
        sudo apt-get install -y ffmpeg

    - name: Install wheel with local extra and pytest
      run: |
        WHEEL=$(ls dist/*.whl)
        pip install "${WHEEL}[local]" pytest

    - name: Run smoke tests against installed wheel
      run: pytest -m smoke
```

**Checkout rationale:** `actions/checkout@v4` is needed to provide the `tests/` directory.
Pytest discovers tests from `testpaths = ["tests"]` in `pyproject.toml`. The checkout does NOT
create an editable install — `python -m build` and `pip install "${WHEEL}[local]"` are the only
install actions. `import electric_blue` during the test resolves to site-packages (the wheel),
not `src/`.

**INV-14 compatibility:** `test_install_editable.py` is not marked `@pytest.mark.smoke`. With
`pytest -m smoke`, pytest collects but does not execute it. The non-editable install does not
cause a collection-time error (the module-level `import electric_blue` succeeds; the assertion
that the path is under `src/` lives inside the test function body and is never executed). No
invariant is tripped.

**ffmpeg:** installed via `apt-get update && apt-get install -y ffmpeg` so it is on `PATH`.
`test_smoke.py`'s `_locate_ffmpeg()` finds it via `shutil.which("ffmpeg")` and the
`imageio_ffmpeg` fallback branch is never reached. `imageio-ffmpeg` is a `dev` extra and is not
installed in this job — this is correct and intentional.

**faster-whisper:** installed via the `[local]` extra on the wheel
(`faster-whisper>=1.2.0,<2.0`). The smoke test does `pytest.importorskip("faster_whisper")`
at the top — it will proceed since the package is installed.

**Python version coverage (accepted residual):** classifiers advertise Python 3.10, 3.11, and
3.12, but `smoke-wheel` runs only on Python 3.12. For a pure-Python wheel this is low risk;
install and import behavior is identical across CPython versions in this range. A smoke-wheel
python matrix (3.10/3.11/3.12) is a documented optional future improvement. Not added for 0.1.0.

#### Job: `publish-testpypi`

**Purpose:** upload to TestPyPI via Trusted Publishing; verify the package installs from
TestPyPI.

```yaml
publish-testpypi:
  name: publish-testpypi
  needs: [smoke-wheel]
  runs-on: ubuntu-latest
  environment: testpypi
  permissions:
    id-token: write
    contents: read
  steps:
    - uses: actions/download-artifact@v4
      with:
        name: dist
        path: dist/

    - name: Publish to TestPyPI
      uses: pypa/gh-action-pypi-publish@release/v1
      with:
        repository-url: https://upload.test.pypi.org/legacy/
        skip-existing: true

    - name: Verify TestPyPI install
      run: |
        pip install \
          --index-url https://test.pypi.org/simple/ \
          --extra-index-url https://pypi.org/simple/ \
          electric-blue
```

**environment: testpypi** must exactly match the Environment name configured in the PyPI
Trusted Publisher record (see Operational Prerequisites). GitHub Actions will request an OIDC
token scoped to this environment. The `testpypi` environment does not require a human reviewer;
it is the rehearsal target for both tag-triggered runs and `workflow_dispatch` rehearsal runs.

**Post-upload install check:** the AC text shows `--index-url https://test.pypi.org/simple/`
alone, but this will fail because `watchdog` and `requests` (runtime deps) are not mirrored on
TestPyPI. The correct command adds `--extra-index-url https://pypi.org/simple/` to resolve
dependencies from real PyPI while pulling `electric-blue` itself from TestPyPI. This is the
standard pattern for TestPyPI install verification. The AC intent (electric-blue resolves and
installs from TestPyPI) is fully satisfied.

**TestPyPI re-uploads (idempotent via `skip-existing`):** the step sets `skip-existing: true`.
This is load-bearing for the dual-trigger design: a `workflow_dispatch` rehearsal uploads
`0.1.0` to TestPyPI, and the later real tag run re-runs `publish-testpypi` with byte-identical
filenames. Warehouse (PyPI/TestPyPI) permanently reserves a filename once uploaded — deleting the
release does NOT free it — so without `skip-existing` the real run would 400 and block
`publish-pypi`. With `skip-existing: true`, the already-present file is skipped (not an error),
the job succeeds, and the release proceeds to the `pypi` gate. The real-PyPI step does NOT set
`skip-existing` (a genuine collision there must fail loud).

#### Job: `publish-pypi`

**Purpose:** upload to real PyPI via Trusted Publishing. This is the immutable step.

```yaml
publish-pypi:
  name: publish-pypi
  needs: [publish-testpypi]
  runs-on: ubuntu-latest
  environment: pypi
  if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')
  permissions:
    id-token: write
    contents: read
  steps:
    - uses: actions/download-artifact@v4
      with:
        name: dist
        path: dist/

    - name: Publish to PyPI
      uses: pypa/gh-action-pypi-publish@release/v1
```

No `repository-url` is set; the action defaults to `https://upload.pypi.org/legacy/`.
`needs: [publish-testpypi]` is the mandatory gate (AC US-3, constraint D3).

The `if:` condition ensures this job runs ONLY on tag-triggered pushes. On `workflow_dispatch`
runs the job is skipped after `publish-testpypi` succeeds — real PyPI is never touched in a
rehearsal run.

---

## Job Graph

```
Tag-triggered (push: tags: vX.Y.Z) — full chain:
  build → check → smoke-wheel → publish-testpypi → publish-pypi

workflow_dispatch (TestPyPI rehearsal only):
  build → check → smoke-wheel → publish-testpypi  [publish-pypi: skipped by if: condition]
```

Artifact (`dist/`) flow:

```
build ──upload──► [GitHub artifact: dist]
                        │
         ┌──────────────┼────────────────────┬──────────────────┐
         ▼              ▼                    ▼                  ▼
       check      smoke-wheel      publish-testpypi       publish-pypi
    (download)    (download)          (download)         (tag runs only)
                                                          (download)
```

All four downstream jobs independently download the `dist` artifact; the `needs:` chain
enforces the sequential gate, not the artifact dependency.

---

## Patterns

| Pattern | Applied to | Rationale |
|---------|-----------|-----------|
| Sequential `needs:` chain | All five jobs | Each job is both a gate and a prerequisite; implicit artifact-fan-out + explicit gate achieves both |
| Workflow-level minimal permissions + per-job override | `id-token: write` only on publish jobs | OIDC token is never issued to build/check/smoke jobs; reduces blast radius if a job is compromised |
| GitHub Environments for publish jobs | `testpypi`, `pypi` | Required by Trusted Publishing OIDC (environment claim in token must match publisher config); also enables required-reviewer gate on `pypi` environment |
| `if: github.event_name == 'push' && startsWith(...)` on `publish-pypi` | `publish-pypi` job | Ensures real PyPI is never touched on `workflow_dispatch` rehearsal runs |
| `if: github.event_name == 'push'` on version-check step | `build` job, version-check step | Skips tag-vs-version check on rehearsal runs where `GITHUB_REF_NAME` is a branch name |
| Version-check as first step in `build` | `build` job | Fail before any artifact is produced; no dist/ in the runner workspace if tag is wrong |
| Wheel install via glob variable | `smoke-wheel` | `ls dist/*.whl` resolves the exact filename without hardcoding version in the workflow |
| `--extra-index-url https://pypi.org/simple/` | TestPyPI install check | Prevents false-negative install failure caused by missing transitive deps on TestPyPI |
| Static `version` in pyproject.toml | pyproject.toml | Locked decision D5; simpler than hatch-vcs for 0.x; the workflow enforces tag==version |

### Anti-Patterns (Explicitly Rejected)

- **API token in GitHub Secrets:** rejected per locked decision D2 / INV-7. No `PYPI_TOKEN` or
  `TEST_PYPI_TOKEN` secret is created or referenced.
- **`pip install -e .` in smoke-wheel:** rejected by requirements constraint. The smoke test must
  prove the wheel works as a distribution artifact, not just the source tree.
- **`hatch-vcs` dynamic version:** rejected per locked decision D5. Static version + workflow
  enforcement is the approved mechanism.
- **Parallel publish jobs:** `publish-pypi` must always `needs: publish-testpypi`. Never run both
  publish jobs concurrently or conditioned independently.
- **`dev`-suffix tag for TestPyPI dry runs:** the trigger regex `v[0-9]+.[0-9]+.[0-9]+` does not
  match `v0.1.0.dev1`; such a tag will never start the workflow. Use `workflow_dispatch` instead.

---

## Dependencies

All are already present in the repo or available in GitHub-hosted runners:

| Tool | Version / Source | Used by | Notes |
|------|-----------------|---------|-------|
| `build` | `>=1.0` (pip install in job) | `build` job | Pure-Python build frontend; produces wheel + sdist |
| `twine` | `>=4.0` (pip install in job) | `check` job | Metadata validation |
| `pytest` | (pip install in job) | `smoke-wheel` job | Test runner; not in wheel extras |
| `pypa/gh-action-pypi-publish` | `@release/v1` (pinned to release branch) | Both publish jobs | Official PyPA upload action with OIDC support |
| `actions/checkout` | `@v4` | `build`, `smoke-wheel` | Source checkout |
| `actions/setup-python` | `@v5` | `build`, `check`, `smoke-wheel` | Python runtime |
| `actions/upload-artifact` | `@v4` | `build` | Dist artifact upload |
| `actions/download-artifact` | `@v4` | `check`, `smoke-wheel`, `publish-testpypi`, `publish-pypi` | Dist artifact download |
| `ffmpeg` | system (`apt-get`) | `smoke-wheel` | Required by smoke test; already present in ci.yml's smoke job |

No new Python runtime dependencies are introduced.

---

## Integration Points

### With `ci.yml` (existing)

`ci.yml` triggers on `push: branches: ["**"]` and `pull_request`. In GitHub Actions, the
`branches` filter under `push` matches only branch refs (`refs/heads/*`), not tag refs
(`refs/tags/*`). A tag push does NOT trigger `ci.yml`. The two workflows are orthogonal:

| Event | `ci.yml` | `release.yml` |
|-------|---------|---------------|
| Push to branch | runs | does not run |
| Pull request | runs | does not run |
| Push of `v[0-9]+.[0-9]+.[0-9]+` tag | does not run | runs (full chain) |
| `workflow_dispatch` | does not run | runs (TestPyPI rehearsal only) |

No modification to `ci.yml` is required or permitted.

### With `Makefile` (existing)

`smoke-wheel` does NOT use `make smoke`. It invokes `pytest -m smoke` directly. This is
intentional: `make smoke` assumes an editable install (`make dev`) as its typical preamble; the
smoke-wheel job must install from the wheel artifact, not from source. The pytest command is
equivalent (`make smoke` is just `pytest -m smoke`).

### With `tests/test_install_editable.py` (existing)

This test asserts `electric_blue.__file__` is under `<repo>/src/` — it passes only on an
editable install. It is not `@pytest.mark.smoke`-marked. `pytest -m smoke` collects but does
not execute it. No INV-14 conflict. The `smoke-wheel` job's non-editable install does not
trigger this test.

### With PyPI / TestPyPI (external)

The Trusted Publishing OIDC exchange requires that the OIDC token claim set exactly matches the
publisher record configured in the PyPI web UI. The critical fields are:

| Claim | Required value |
|-------|---------------|
| Repository owner | `dannySubsense` |
| Repository name | `electric-blue` |
| Workflow filename | `release.yml` |
| Environment (testpypi publisher) | `testpypi` |
| Environment (pypi publisher) | `pypi` |

A mismatch on any field causes a 403 auth error at the publish step. TestPyPI is validated first
(by job ordering) so a misconfiguration is caught before touching real PyPI.

---

## Operational Prerequisites (One-Time Human Steps)

These steps are outside the workflow. They must be completed by the repo owner before pushing
the first release tag. The workflow cannot automate them.

### Step 1 — Create GitHub Environments

In the repo settings (`Settings → Environments`):
1. Create environment named `testpypi` (exact spelling, lowercase).
2. Create environment named `pypi` (exact spelling, lowercase).
3. **Mandatory for 0.1.0:** Add a required reviewer on the `pypi` environment. This is the human
   gate between a green pipeline and an immutable PyPI artifact. The `testpypi` environment does
   not require a reviewer (it is the rehearsal target).

### Step 2 — Configure TestPyPI Trusted Publisher

At `https://test.pypi.org/manage/account/publishing/`:
- Add a new pending publisher with:
  - PyPI project name: `electric-blue`
  - Owner: `dannySubsense`
  - Repository name: `electric-blue`
  - Workflow filename: `release.yml`
  - Environment name: `testpypi`

### Step 3 — Configure PyPI Trusted Publisher

At `https://pypi.org/manage/account/publishing/` (or from the project page after first upload):
- Add a new pending publisher with:
  - PyPI project name: `electric-blue`
  - Owner: `dannySubsense`
  - Repository name: `electric-blue`
  - Workflow filename: `release.yml`
  - Environment name: `pypi`

> Note: a "pending publisher" allows the first upload to create the project automatically. No
> manual project creation on PyPI is required.

### Step 4 — Pre-Publish README and pyproject.toml Edits

Before pushing the release tag, apply the pyproject.toml metadata additions and README cleanup
described in the Data Schemas section above. Run `twine check --strict dist/*` locally after a
test build (`python -m build`) to verify rendering.

---

## Failure Modes and Rollback

### Pre-Publish Failures (safe — nothing uploaded)

| Failure | Where caught | Recovery |
|---------|-------------|---------|
| Tag `v0.1.1` pushed but `version = "0.1.0"` | `build` job, version-check step | Fix pyproject.toml or push correct tag; no artifact produced |
| `twine check` finds broken long description | `check` job | Fix README (broken Markdown, RST directives, etc.), rebuild, re-push tag |
| `pytest -m smoke` fails on wheel | `smoke-wheel` job | Debug locally; no upload occurred; re-push tag after fix |
| OIDC misconfiguration — wrong env name, wrong workflow name | `publish-testpypi` job | Fix publisher config in PyPI/TestPyPI web UI or fix environment name; no real-PyPI upload occurred |

### TestPyPI re-upload after a rehearsal — handled automatically

If `0.1.0` was already uploaded to TestPyPI (the expected case: a `workflow_dispatch` rehearsal
preceded the real tag run), `publish-testpypi` does NOT fail. The step sets `skip-existing: true`,
so the already-present file is skipped and the job succeeds; the release proceeds to `publish-pypi`.

No manual deletion is required (and deletion would not help anyway — Warehouse permanently
reserves a filename once uploaded, even after the release is deleted; `skip-existing` is the
correct mechanism). The dual-trigger rehearse-then-release flow works without operator intervention
on the TestPyPI step.

> **Note:** a `dev`-suffix tag (e.g., `v0.1.0.dev1`) does NOT match the trigger regex
> `v[0-9]+.[0-9]+.[0-9]+` and will never start `release.yml` — do not attempt that as a workaround;
> it is unnecessary now that the TestPyPI step is idempotent.

### Post-PyPI-Publish (immutable — yank only)

PyPI releases cannot be deleted. If a broken `0.1.0` reaches real PyPI:

1. **Yank the release:** `pip install electric-blue` will not install a yanked version by
   default. Users who already pinned `electric-blue==0.1.0` still get it (yank is soft). This
   is the standard "oops" mitigation.
   - Via PyPI web UI: project page → Manage → Yank release.
2. **Publish a fix as `0.1.1`:** the only way to replace the artifact in pip's default behavior.
   A yanked release is not deleted; it persists as a record.

The `build → check → smoke-wheel → publish-testpypi` chain is the defense layer that makes this
scenario unlikely. A bad secret or sensitive path in the sdist is the highest-impact failure mode
(INV-7) and is not recoverable via yank alone.

---

## Accepted Residuals (0.1.0)

The following are consciously accepted limitations for the 0.1.0 release. Each is documented
here as a known gap, not an oversight.

**No automated sdist secret/content scan (G-6):** The publish pipeline
(`build → check → smoke-wheel → publish-testpypi`) validates functionality and metadata but
performs no automated scan of the sdist contents for secrets, credentials, or sensitive file
paths. The control against publishing a secret in the sdist is INV-7 human PR review (already
mandated in the roadmap PR Workflow section). This is a consciously accepted residual for 0.1.0.
An optional future improvement — an sdist content scan step before `publish-testpypi` — is
deferred.

**Smoke-wheel runs on Python 3.12 only (G-8):** Classifiers advertise support for Python 3.10,
3.11, and 3.12, but `smoke-wheel` runs only on Python 3.12. For a pure-Python wheel this is low
risk. A smoke-wheel python matrix is a documented optional future improvement, not added for
0.1.0.

---

## Drift Flags (DDR vs Current Code)

The following items differ between DDR-06 snippets and the current repo state. The architecture
design above resolves each:

| Item | DDR §/snippet | Current code | Resolution in this design |
|------|--------------|-------------|--------------------------|
| License field | `license = "MIT"` (SPDX form) | `license = { text = "MIT" }` | Change to SPDX form per DDR and AC US-8 |
| GitHub org in URLs | `dannySubsense` | README uses `your-org` placeholder | Use `dannySubsense` per DDR §1; README update covers this |
| TestPyPI upload URL | DDR shows `https://upload.pypi.org/legacy/` for real PyPI (doc error); AC text shows `https://test.pypi.org/legacy/` for TestPyPI | N/A | Use canonical `https://upload.test.pypi.org/legacy/` per pypa/gh-action-pypi-publish docs |
| Post-TestPyPI install check | AC: `pip install --index-url https://test.pypi.org/simple/` (bare, no extra-index) | N/A | Add `--extra-index-url https://pypi.org/simple/` to resolve `watchdog`/`requests` deps absent on TestPyPI |
| `wheel-smoke` naming | DDR §5 checklist uses "wheel-smoke"; requirements and AC use "smoke-wheel" | N/A | Use `smoke-wheel` throughout (matches AC and requirements) |

---

## Requirement Coverage Matrix

| AC cluster | Covered by |
|-----------|-----------|
| US-1 (tag trigger, job order) | `release.yml` trigger + sequential `needs:` chain |
| US-2 (build + check + smoke-wheel gate) | `build`, `check`, `smoke-wheel` jobs |
| US-3 (TestPyPI gate) | `publish-pypi: needs: [publish-testpypi]` |
| US-4 (tag == version) | version-check step in `build` job (first step, before build; tag runs only) |
| US-5 (pip install, CLI entry point) | pyproject.toml `[project.scripts]` unchanged; publish puts package on PyPI |
| US-6 (local extra) | `[project.optional-dependencies].local` unchanged; advertised in updated README |
| US-7 (ffmpeg docs + README cleanup) | README edit: remove "not yet on PyPI", remove diarize from public surface, retain ffmpeg notice |
| US-8 (metadata: classifiers, URLs, keywords, license) | pyproject.toml additions; `check` job validates via `twine check --strict` |
| US-9 (no long-lived credentials) | Trusted Publishing OIDC; `id-token: write` on publish jobs only; no `PYPI_TOKEN` secret |
