# Requirements: pypi-publish

**Sprint:** pypi-publish
**DDR:** DDR-06-pypi-publish.md
**Status:** APPROVED — all intake decisions resolved (see Constraints)
**Date:** 2026-06-24

---

## Summary

Publish `electric-blue` to PyPI as version `0.1.0` with the `local` extra only. Delivery
includes: finalized `pyproject.toml` metadata, a pre-publish README edit, and a GitHub
Actions release workflow (`.github/workflows/release.yml`) that gates on TestPyPI before
touching real PyPI, uses Trusted Publishing (OIDC), and enforces tag/version consistency
automatically.

---

## User Stories

### US-1 — Release by tag push

As a maintainer,
I want to trigger a full release to PyPI by pushing a `v`-prefixed semver tag,
so that releasing requires exactly one action and involves no manual upload steps.

### US-2 — Build validation gate

As a maintainer,
I want the release workflow to build, metadata-check, and smoke-test the wheel before any
upload occurs,
so that a broken or malformed artifact never reaches TestPyPI or real PyPI.

### US-3 — TestPyPI gate before real PyPI

As a maintainer,
I want `publish-pypi` to be blocked on successful `publish-testpypi`,
so that a TestPyPI dry-run always precedes an immutable real-PyPI release.

### US-4 — Tag/version consistency

As a maintainer,
I want the workflow to fail if the pushed tag does not match the version declared in
`pyproject.toml`,
so that the published version is never ambiguous.

### US-5 — Install via pip

As an end user,
I want to install the package with `pip install electric-blue`,
so that I do not need to clone the repository.

### US-6 — Local extra installable via pip

As an end user,
I want to install the faster-whisper backend with `pip install "electric-blue[local]"`,
so that I can run local GPU/CPU transcription without sourcing the repo.

### US-7 — ffmpeg system dependency prominently documented

As an end user,
I want the PyPI page and README to clearly state that ffmpeg is a required system
dependency not installable via pip,
so that I know to install it separately before invoking the CLI.

### US-8 — Accurate PyPI metadata

As an end user,
I want the PyPI listing to carry correct classifiers, project URLs, keywords, and license,
so that I can find, evaluate, and trust the package on PyPI.

### US-9 — No long-lived credentials

As a maintainer,
I want the publish jobs to authenticate via GitHub Actions OIDC (Trusted Publishing)
without any API token stored in GitHub Secrets,
so that there is no long-lived credential to rotate or leak.

---

## Acceptance Criteria

### US-1 — Release by tag push

- [ ] Given a tag matching `v[0-9]+.[0-9]+.[0-9]+` is pushed to the repo, when GitHub
  receives the push event, then `.github/workflows/release.yml` starts automatically.
- [ ] Given a push to `main` with no tag, when CI runs, then `release.yml` does NOT
  trigger.
- [ ] Given a tag that does not match the pattern (e.g., `release-v0.1.0`, `0.1.0`), when
  pushed, then `release.yml` does NOT trigger.
- [ ] Given a successful end-to-end run, the workflow jobs execute in this order:
  `build → check → smoke-wheel → publish-testpypi → publish-pypi`.

### US-2 — Build validation gate

- [ ] Given a triggering tag, when the `build` job runs, then both a wheel (`*.whl`) and
  an sdist (`*.tar.gz`) are produced and uploaded as a GitHub Actions workflow artifact.
- [ ] Given the built artifact, when the `check` job runs `twine check dist/*`, then the
  job exits 0 only if all metadata is valid and the long description renders without error.
- [ ] Given the wheel artifact, when the `smoke-wheel` job installs from the wheel (not
  from `-e .` or source) and runs `pytest -m smoke`, then the job exits 0 only if all
  smoke tests pass.
- [ ] Given any of `build`, `check`, or `smoke-wheel` fails, then `publish-testpypi` and
  `publish-pypi` do NOT run.

### US-3 — TestPyPI gate before real PyPI

- [ ] Given `smoke-wheel` passes, when `publish-testpypi` runs, then the package is
  uploaded to TestPyPI using the `pypa/gh-action-pypi-publish@release/v1` action with
  `repository-url: https://upload.test.pypi.org/legacy/`.
- [ ] Given the TestPyPI upload succeeds, when the post-upload install check runs
  `pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ electric-blue`,
  then it completes without error.
- [ ] Given `publish-testpypi` fails (for any reason), then `publish-pypi` does NOT run.
- [ ] Given `publish-testpypi` succeeds, when `publish-pypi` runs, then the package is
  uploaded to real PyPI using Trusted Publishing.
- [ ] `release.yml` declares `needs: publish-testpypi` on the `publish-pypi` job.

### US-4 — Tag/version consistency

- [ ] Given a tag `vX.Y.Z` is pushed, when the release workflow starts, then it extracts
  `X.Y.Z` from the tag and compares it to the `version` field in `pyproject.toml`; if
  they differ, the workflow fails before any build step runs.
- [ ] Given tag `v0.1.0` and `version = "0.1.0"` in `pyproject.toml`, then the
  version-check step passes.
- [ ] Given tag `v0.1.1` and `version = "0.1.0"` in `pyproject.toml`, then the
  version-check step fails and no artifact is built.

### US-5 — Install via pip

- [ ] Given `v0.1.0` is published to real PyPI, when a user runs `pip install electric-blue`
  in a clean virtualenv, then it installs without error.
- [ ] Given the base install, when the user runs `electric-blue --help`, then the CLI
  entry point responds with a usage message and exits 0.

### US-6 — Local extra installable via pip

- [ ] Given a clean virtualenv, when the user runs
  `pip install "electric-blue[local]"`, then `faster-whisper>=1.2.0,<2.0` is installed as
  a dependency.
- [ ] Given the `local` extra is installed and `ffmpeg` is present on the system, when the
  user invokes the `local` backend, then transcription completes without import errors.
  *(Covered-by-assumption: the DDR-01 `pytest -m smoke` suite exercises the local-backend
  path; `smoke-wheel` installs `[local]` and runs this suite on the built wheel.)*

### US-7 — ffmpeg system dependency prominently documented

- [ ] Given the published PyPI long description (sourced from `README.md`), when viewed on
  pypi.org, then it contains a prominently placed notice that `ffmpeg` is a required system
  dependency that cannot be installed via pip.
- [ ] Given the `README.md` before the first publish, when reviewed, then it does NOT
  contain the phrase "not yet published to PyPI" or any equivalent holding statement.
- [ ] Given the `README.md` before the first publish, when reviewed, then it does NOT
  present `diarize` as an installable or supported feature at 0.1.0.
- [ ] Given the `README.md` before the first publish, when reviewed, then the install
  section references `pip install electric-blue` and `pip install "electric-blue[local]"`
  as the canonical install commands.

### US-8 — Accurate PyPI metadata

- [ ] Given `pyproject.toml`, when `twine check dist/*` runs, then it exits 0 with no
  warnings about metadata or description rendering.
- [ ] `pyproject.toml` contains a `classifiers` list that includes at minimum:
  `"Development Status :: 4 - Beta"`, `"Environment :: Console"`,
  `"License :: OSI Approved :: MIT License"`, `"Programming Language :: Python :: 3"`,
  `"Programming Language :: Python :: 3.10"`, `"Programming Language :: Python :: 3.11"`,
  `"Programming Language :: Python :: 3.12"`, and
  `"Topic :: Multimedia :: Sound/Audio :: Speech"`.
- [ ] `pyproject.toml` contains a `[project.urls]` section with `Homepage`, `Repository`,
  and `Issues` keys all pointing to `https://github.com/dannySubsense/electric-blue` (with
  `Issues` appending `/issues`).
- [ ] `pyproject.toml` contains a `keywords` list that includes `"transcription"`,
  `"whisper"`, `"speech-to-text"`, `"ffmpeg"`, `"drop-folder"`, `"watchdog"`.
- [ ] `pyproject.toml` uses the SPDX form `license = "MIT"` (not `license = { text = "MIT" }`).

### US-9 — No long-lived credentials

- [ ] The publish jobs in `release.yml` declare:
  ```yaml
  permissions:
    id-token: write
    contents: read
  ```
- [ ] No GitHub Actions secret named `PYPI_TOKEN`, `TEST_PYPI_TOKEN`, or equivalent
  API-key secret exists or is referenced in `release.yml`.
- [ ] Both `publish-testpypi` and `publish-pypi` jobs use
  `pypa/gh-action-pypi-publish@release/v1` as the upload step.

---

## Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| Tag `v0.1.1` pushed; `pyproject.toml` still says `0.1.0` | Workflow fails at version-check step; no artifact built; no upload |
| TestPyPI already has a `0.1.0` upload from a prior dry-run | `publish-testpypi` fails (version conflict); `publish-pypi` does not run; maintainer must manually delete the conflicting release on TestPyPI, then re-run the release workflow |
| `twine check` detects malformed long description (e.g., broken Markdown) | `check` job fails; `smoke-wheel`, `publish-testpypi`, `publish-pypi` do not run |
| User installs `electric-blue` (base, no extras) without `ffmpeg` present | Install succeeds; CLI invocation that requires ffmpeg fails at runtime with a clear error — not an install error. This is expected and documented. |
| User installs `pip install "electric-blue[diarize]"` after 0.1.0 | The extra is present in the wheel and installs silently. This is acceptable; `diarize` is not advertised as supported at 0.1.0, not blocked. |
| OIDC publisher misconfigured on PyPI side (wrong repo slug, environment, or workflow name) | `publish-testpypi` or `publish-pypi` fails with an auth/403 error; the other publish job does not run |
| Tag pushed before Trusted Publishing is configured on TestPyPI/PyPI web UI | Same as OIDC misconfiguration — publish jobs fail with auth error |
| `pytest -m smoke` fails on the installed wheel | `smoke-wheel` job fails; no upload occurs |
| Non-version tag pushed (e.g., `docs-fix`) | `release.yml` does not trigger (pattern does not match) |

---

## Out of Scope

- NOT: `diarize` extra advertised or committed as supported public surface at 0.1.0. The
  extra remains in `pyproject.toml` and the wheel but is deferred to 0.2.0, gated on a
  passing `pytest -m diarize_smoke` on a host with the real dependency. (Locked decision.)
- NOT: `ffmpeg` optional extra or bundling via `imageio-ffmpeg`. System dependency;
  document-only mitigation. (Locked decision D8.)
- NOT: `hatch-vcs` or any dynamic version derivation. Static `version` in `pyproject.toml`
  only. (Locked decision D5.)
- NOT: CHANGELOG tooling automation (changie, towncrier, etc.). A manually authored
  `CHANGELOG.md` or GitHub Release note is sufficient for 0.1.0.
- NOT: GitHub Release creation automation. `release.yml` publishes to PyPI; it does not
  create a GitHub Release object.
- NOT: Multi-platform or multi-arch wheel building (cibuildwheel, fat wheels). A single
  pure-Python wheel is sufficient.
- NOT: `dev` extra described as a user-facing extra in README or PyPI description.
- NOT: changes to `ci.yml`. The existing CI workflow continues unchanged; `release.yml` is
  an additive, separate workflow file.
- NOT: README updates to the `api` or `groq-batch` backend install paths. Those backends
  are installable from source; no pip-installable extras for them ship at 0.1.0.
- Deferred: PyPI yank automation.
- Deferred: `diarize` extra as public surface (0.2.0, after live `diarize_smoke` passes).

---

## Constraints

### Hard requirements

- **Must:** `pyproject.toml` `name = "electric-blue"`. Name is confirmed available on PyPI
  (D1 resolved: dual-404 on PyPI JSON API). No fallback name.
- **Must:** Both `publish-testpypi` and `publish-pypi` authenticate exclusively via GitHub
  Actions OIDC (Trusted Publishing). No API token in GitHub Secrets. (D2.)
- **Must:** `publish-pypi` job declares `needs: publish-testpypi`. The TestPyPI gate is
  mandatory for 0.1.0 and cannot be bypassed. (D3.)
- **Must:** Workflow trigger pattern is `v[0-9]+.[0-9]+.[0-9]+` (e.g., `v0.1.0`). (D4.)
- **Must:** `version` in `pyproject.toml` remains static (not `dynamic`). Release workflow
  must enforce that the stripped tag equals the declared version and fail fast if not. (D5.)
- **Must:** First published version is `0.1.0`, advertising only the `local` extra.
  (D6/D7.)
- **Must:** README must not contain "not yet published to PyPI" wording after the
  pre-publish edit.
- **Must:** README and PyPI long description must NOT present `diarize` as an installable
  or supported feature at 0.1.0. (Frank constraint, this session.)
- **Must:** `ffmpeg` system dependency documented prominently in README (which becomes the
  PyPI long description). (D8 + DDR-06 §5 item 6.)
- **Must:** `release.yml` is a separate file from `ci.yml`; both coexist and serve
  different trigger conditions.
- **Must:** The workflow's `smoke-wheel` job installs from the built wheel artifact, not
  from `-e .` or source checkout.

### Assumptions

- **Assumes:** The repo owner (Danny) will configure Trusted Publishing on both TestPyPI
  and PyPI web UIs (Owner: `dannySubsense`, Repository: `electric-blue`, Workflow:
  `release.yml`) before pushing the first release tag. This is a one-time manual step
  outside the workflow.
- **Assumes:** The `pytest -m smoke` test suite exists and is passing on a clean wheel
  install (established by DDR-01 / existing CI). This DDR does not introduce smoke tests.
- **Assumes:** The `smoke-wheel` GitHub Actions runner has `ffmpeg` available (e.g., via
  an `apt-get install ffmpeg` step). The job must provision it explicitly.
- **Assumes:** `LICENSE` file exists in the repo root; hatchling includes it automatically
  in the sdist.
- **Assumes:** `README.md` is valid Markdown that renders correctly on PyPI; `twine check`
  will catch any rendering failures.
