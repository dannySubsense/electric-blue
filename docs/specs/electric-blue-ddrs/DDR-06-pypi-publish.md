# DDR-06 — PyPI Publish

- **Status:** PROPOSED
- **Author:** reed
- **Date:** 2026-06-14
- **Sprint (on approval):** `pypi-publish`
- **Depends on:** DDR-01 (src layout, hatchling, entry point), DDR-05 (output schema + extras surface settled)
- **Blocks:** —
- **Supersedes:** —

---

## Context

`electric-blue` is intentionally sequenced last for PyPI publication. Publishing to PyPI
locks a **public CLI and API surface under semver**: once `pip install electric-blue` is
real, users will pin versions, script around the `electric-blue` entry point, and import
`electric_blue` in their own tooling. Breaking changes then carry a social cost that
internal refactors do not.

Two concrete prerequisites justify waiting:

1. **DDR-05 (WhisperX / diarization)** will add a `diarize` extra, speaker-label fields
   to the JSON output schema, and possibly additional CLI flags. Publishing before DDR-05
   merges would mean a 0.1.0 → 0.2.0 breaking bump almost immediately after launch.
2. The `api` backend surface (env vars, request shape, response fields) is still being
   characterized and pinned by DDR-02. Stability there is a prerequisite for calling the
   surface "public."

The README already says "not yet published to PyPI — install from source," which is the
correct holding position.

This DDR covers: packaging metadata finalization, versioning policy, release automation via
GitHub Actions with PyPI Trusted Publishing (OIDC), and pre-publish validation gates.

## Principle

A first publish should be boring. The infrastructure (Trusted Publishing, TestPyPI gate,
`twine check`, wheel-install smoke) is set up correctly once, then every subsequent release
is a tag push. No API tokens in the repo; no manual `twine upload` from a dev laptop.

---

## Decision

### 1. Packaging metadata finalization

`pyproject.toml` is structurally complete from DDR-01 (hatchling, src layout, extras,
entry point). What is missing for a compliant, discoverable PyPI listing:

**Classifiers** — add under `[project]`:
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

**Project URLs**:
```toml
[project.urls]
Homepage = "https://github.com/dannySubsense/electric-blue"
Repository = "https://github.com/dannySubsense/electric-blue"
Issues = "https://github.com/dannySubsense/electric-blue/issues"
```

**Keywords**:
```toml
keywords = ["transcription", "whisper", "speech-to-text", "ffmpeg", "drop-folder", "watchdog"]
```

**License field** — the current `license = { text = "MIT" }` form is valid but the
preferred modern form (PEP 639 / SPDX) is:
```toml
license = "MIT"
```
Hatchling supports both; the SPDX form is preferred for PyPI's license classifier lookup.
The `LICENSE` file should remain in the repo root; hatchling includes it automatically.

**Long description** — `readme = "README.md"` is already set; hatchling infers
`text/markdown` from the extension. The README note about "not yet on PyPI — install from
source" must be removed before the first publish (it will be wrong the moment it goes up).

**Extras surface** — the current extras are `local` and `dev`. DDR-05 is expected to add
`diarize`. Whether all three are committed public surface at first publish is flagged below
(D6). `dev` should be excluded from the public surface description in README (it is a
development convenience, not a user-facing extra).

### 2. Versioning policy

- **Scheme:** semantic versioning (`MAJOR.MINOR.PATCH`).
- **Pre-1.0 policy:** remain on `0.x` while the backend Protocol and output schema may
  still move. A `MINOR` bump signals new capability (new backend, new output field); a
  `PATCH` bump is bug-fix only. A breaking CLI/env-var/schema change requires a `MINOR`
  bump at minimum, with a changelog entry calling it out explicitly.
- **Version source:** see D5 (static vs hatch-vcs) — currently static `version = "0.1.0"`
  in `pyproject.toml`. The release workflow must enforce that the git tag matches the
  declared version.

### 3. Release workflow (`.github/workflows/release.yml`)

A separate workflow file, triggered only on version tags. It does not replace `ci.yml`;
CI continues to run on every push and PR.

**Trigger:**
```yaml
on:
  push:
    tags:
      - "v[0-9]+.[0-9]+.[0-9]+"   # e.g. v0.1.0 — see D4 for tag convention
```

**Job structure (sequential gates):**

```
build → check → smoke-wheel → publish-testpypi → publish-pypi
```

- **`build`**: `pip install build`, run `python -m build` (produces `dist/` with sdist +
  wheel). Upload `dist/` as a workflow artifact.

- **`check`**: download `dist/`, run `twine check dist/*`. Verifies long description
  renders, metadata is valid. Fails fast before any upload.

- **`smoke-wheel`**: install from the built wheel (not `-e .`, not from source — from the
  actual artifact in `dist/`), then run `pytest -m smoke` against the installed package.
  Proves the wheel is functional, not just syntactically valid. Requires `ffmpeg` and
  `.[local,dev]`-equivalent deps.

- **`publish-testpypi`**: publish to TestPyPI using Trusted Publishing (see §4). Requires
  the TestPyPI project to have OIDC configured for this repo and workflow. After upload,
  run a `pip install --index-url https://test.pypi.org/simple/ electric-blue` install check
  as a sanity smoke. See D3 for whether this gate is mandatory.

- **`publish-pypi`**: publish to real PyPI using Trusted Publishing, gated on
  `publish-testpypi` success. This is the step that makes `pip install electric-blue` real.

### 4. PyPI Trusted Publishing (OIDC)

Trusted Publishing eliminates long-lived API tokens from GitHub secrets. The GitHub Actions
OIDC token is exchanged for a short-lived PyPI upload token at publish time.

**Setup (one-time, done by the repo owner in PyPI/TestPyPI web UI before first run):**
- Create the project on TestPyPI, then PyPI (or let the first upload create it).
- On each: go to *Publishing* → *Add a new publisher* → GitHub Actions → enter:
  - Owner: `dannySubsense`
  - Repository: `electric-blue`
  - Workflow: `release.yml`
  - Environment (optional but recommended): `pypi` / `testpypi`

**Workflow permissions** required on the publish jobs:
```yaml
permissions:
  id-token: write   # required for OIDC
  contents: read
```

**Publish step** (using the canonical action):
```yaml
- uses: pypa/gh-action-pypi-publish@release/v1
  with:
    repository-url: https://upload.pypi.org/legacy/  # omit for real PyPI (default)
```

See D2 for the final decision between Trusted Publishing and an API token in secrets.

### 5. Pre-publish checklist (enforced in workflow, documented in CONTRIBUTING.md)

The workflow enforces these mechanically; the checklist is for human review of a release PR:

1. **PyPI name availability confirmed** — see D1. Verify `https://pypi.org/project/electric-blue/` is unclaimed before configuring Trusted Publishing under that name.
2. `twine check dist/*` passes (enforced by `check` job).
3. Wheel-install smoke passes (enforced by `smoke-wheel` job).
4. README "not yet on PyPI" note removed.
5. `CHANGELOG.md` or GitHub Release notes written for the version.
6. `ffmpeg` system dependency is prominently documented as non-pip-installable (already in README; verify it survives the pre-publish README edit).
7. Version tag matches `version` in `pyproject.toml` (or hatch-vcs handles it — D5).
8. TestPyPI dry-run passed (enforced by job ordering — D3).

---

## Sequencing (within the sprint)

This sprint cannot start until DDR-05 is merged and the output schema is stable.

1. Confirm PyPI name availability — block everything else on D1 resolution.
2. Finalize `pyproject.toml` metadata (classifiers, URLs, keywords, license expression).
3. Remove README "not yet on PyPI" note; update install section to `pip install electric-blue`.
4. Add `CHANGELOG.md` (or adopt GitHub Releases as the changelog vehicle — minor scope).
5. Write `.github/workflows/release.yml` per §3.
6. Configure Trusted Publishing on TestPyPI and PyPI (requires repo owner access).
7. Create a release PR; Frank gate (lint-test, smoke via CI). Merge to `main`.
8. Tag `v0.1.0` (or decided version — D5, D7). Watch the release workflow run.
9. Verify `pip install electric-blue` from a clean venv.

## Risks

- **PyPI name conflict** — "electric-blue" on PyPI could be claimed or squatted. If the
  name is taken, the distribution name changes but the import package (`electric_blue`) and
  entry point (`electric-blue`) can remain the same. Fallback names must be decided before
  configuring Trusted Publishing. See D1.
- **Immutable releases** — PyPI releases cannot be deleted (only yanked). A botched 0.1.0
  with a bad wheel, broken metadata, or a public secret in the sdist is expensive to
  recover from. The `build → check → smoke-wheel → testpypi` chain exists to catch this
  before touching real PyPI.
- **ffmpeg not pip-installable** — users who `pip install electric-blue` and immediately
  try `electric-blue` without `ffmpeg` installed will get a runtime error, not an install
  error. The README and PyPI long description must be explicit about this. `imageio-ffmpeg`
  (in `dev` extras now) could be moved to base deps as a fallback, but it bundles a
  non-system ffmpeg binary and is not production-appropriate. Document the gap; do not
  paper over it with a bundled binary. See D8.
- **0.x semver false comfort** — `0.x` does not absolve us of changelog discipline. Any
  env-var rename or output field removal is a breaking change that needs a MINOR bump and
  an explicit note, even at 0.x.
- **Trusted Publishing OIDC misconfiguration** — if the environment name, workflow file
  name, or repo slug in the PyPI publisher config does not exactly match the workflow,
  publish will fail with a confusing auth error. Test against TestPyPI first (enforced by
  job ordering).

## Open questions / DECISIONS TO FLAG (resolve with Danny, do not block drafting)

- **D1 — PyPI name availability.** `pip install electric-blue` requires the name
  `electric-blue` to be unclaimed on PyPI. Check `https://pypi.org/project/electric-blue/`
  before any other step. If taken, the distribution name must change — the import package
  (`electric_blue`) and console entry point (`electric-blue`) can stay the same regardless.
  Proposed fallbacks in priority order: `electric-blue-transcribe`, `electric-blue-ts`.
  The distribution name is only the `pip install` handle; it does not appear in user code.
  **DECISION: confirm name or choose fallback.**

- **D2 — Trusted Publishing (OIDC) vs API token in GitHub Secrets.** OIDC is the modern
  best practice (no long-lived secret, no rotation burden, scoped to this workflow). API
  token is simpler to set up for a first publish and does not require PyPI web-UI
  configuration ahead of time. Lean: Trusted Publishing — the one-time setup cost is low
  and the security posture is materially better. **DECISION.**

- **D3 — TestPyPI gate mandatory vs optional.** Making `publish-pypi` depend on
  `publish-testpypi` adds safety but also adds latency and requires TestPyPI project
  configuration in addition to PyPI. For a first publish the gate is strongly recommended.
  Lean: mandatory gate for 0.1.0; re-evaluate for subsequent patch releases.
  **DECISION: mandatory or skip?**

- **D4 — Tag and release convention.** Options: `v0.1.0` (common, GitHub auto-generates
  releases), `0.1.0` (bare semver, no prefix). The release workflow regex above uses `v`
  prefix. GitHub's "Create Release" UI defaults to `v` prefix. Lean: `v0.1.0`.
  **DECISION: confirm tag format.**

- **D5 — Static version vs hatch-vcs.** Currently `version = "0.1.0"` is static in
  `pyproject.toml`. Static is simple: bump the file, commit, tag. hatch-vcs (`hatch-vcs`
  plugin, adds a build-time dependency) derives version from the git tag, eliminating the
  manual file bump — but means the version field in `pyproject.toml` changes to
  `dynamic = ["version"]` and `python -c "import electric_blue; print(electric_blue.__version__)"` works only after an install from a tagged commit or sdist. Lean: static for now; hatch-vcs is a future quality-of-life improvement.
  **DECISION.**

- **D6 — Committed public extras at first publish.** The current extras are `local` (faster-whisper) and `dev`. DDR-05 is expected to add `diarize`. Should 0.1.0 ship with `diarize` (implying DDR-05 is merged first — already the sequencing requirement) or without it (ship earlier, add `diarize` in 0.2.0)? The sequencing in this DDR assumes DDR-05 merges first and `diarize` ships in 0.1.0. If the timeline slips, 0.1.0 ships `local`-only and `diarize` lands in 0.2.0.
  **DECISION: ship with or without `diarize`? Timing relative to DDR-05?**

- **D7 — First published version number.** `0.1.0` is already in `pyproject.toml`. If
  DDR-05 merges before publish, `0.1.0` is reasonable (first public release includes
  diarization). If DDR-03 (Groq Batch) also merges first, same. Alternatively, publish
  `0.1.0` without waiting, then release `0.2.0` after DDR-03/05. The sequencing constraint
  is driven by surface stability, not feature completeness. **DECISION: publish version and
  timing.**

- **D8 — `imageio-ffmpeg` in `dev` extras vs document-only gap.** `imageio-ffmpeg` is
  currently in `dev` extras (used by tests). It provides a bundled ffmpeg binary. Promoting
  it to an optional user-facing extra (e.g. `pip install "electric-blue[ffmpeg]"`) would
  remove the manual system-dep step for users who want a self-contained install. Downsides:
  bundled binary, not production codec-complete, adds a heavyish dependency. Lean: document
  the system dep; do not create an `ffmpeg` extra. **DECISION: worth an `ffmpeg` extra or
  not?**
