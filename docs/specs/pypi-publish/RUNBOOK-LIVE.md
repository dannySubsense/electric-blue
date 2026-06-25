# RUNBOOK — Going LIVE on PyPI (DDR-06, electric-blue 0.1.0)

> 🛑 **LIVE TRACK KILLED 2026-06-25 (Danny's call). DO NOT run this runbook.** PyPI publication was
> agent-invented ceremony — `electric-blue` is a homelab leaf utility with no public audience, so a
> public `pip install` handle buys nothing (self-hosting installs from a git checkout). The merged
> DDR-06 code is harmless and stays (release.yml is tag/dispatch-only — merging published nothing).
> Revive **only** if Danny explicitly wants a genuinely public package. See LORE `31060675` and
> `project_status`. Everything below is retained for that hypothetical, not as a current instruction.

**Audience:** Danny (repo owner). **Status of code:** CODE-MERGED @ `main` `c184c7a`, NOT LIVE.
**What "live" means:** `pip install electric-blue` resolves from real PyPI.

> ⚠️ **PyPI is immutable.** A published `0.1.0` cannot be deleted — only *yanked* (hidden from new
> installs; anyone who already pinned it still gets it). A botched first publish is expensive. The
> whole chain below (rehearsal → TestPyPI → mandatory reviewer) exists so the irreversible step is
> the *last* and most-guarded one. Do not skip the rehearsal.

This runbook is the live counterpart to `04-ROADMAP.md` §HOP-1/2/3 + HFS-1. Follow it in order.
Phases 1–2 are reversible. The point of no return is approving the `pypi` reviewer gate in Phase 3.

The shipped workflow is `.github/workflows/release.yml`. Job chain:
`build → check → smoke-wheel → publish-testpypi → publish-pypi`. Two triggers:
- **`workflow_dispatch`** (manual) → runs through `publish-testpypi` and **stops** (`publish-pypi` is
  skipped). This is your **rehearsal / dry-run**. Cannot touch real PyPI.
- **`push` of a `vX.Y.Z` tag** → runs the full chain including `publish-pypi`.

---

## Phase 0 — Local pre-flight (do first, ~2 min)

Run from the repo root on a clean `main`:

```bash
git fetch && git switch main && git pull --ff-only
git rev-parse --short HEAD          # expect c184c7a (or later if main moved)
git status --short                  # expect empty (clean tree)
PATH="$PWD/.venv/bin:$PATH" make gate   # expect 195 passed / 2 deselected
grep -E '^version' pyproject.toml   # expect version = "0.1.0"
```

All four must be green before you touch any web UI. If `make gate` is red, **stop** — do not publish.

---

## Phase 1 — One-time account + Trusted Publishing setup (HOP-2, HOP-3, HOP-1)

These are reversible and can be done in any order, but do **all three** before the rehearsal.
Trusted Publishing means **no API token is ever stored** — PyPI trusts a short-lived OIDC token
minted by *this* repo's `release.yml`. The four identifiers below must match the workflow **exactly**
or you get a confusing `403` at publish time.

The identifiers (same for both PyPI and TestPyPI):

| Field | Value |
|---|---|
| PyPI Project Name | `electric-blue` |
| Owner | `dannySubsense` |
| Repository | `electric-blue` |
| Workflow filename | `release.yml` *(filename only, not a path)* |
| Environment name | `testpypi` (on TestPyPI) / `pypi` (on PyPI) |

### HOP-2 — TestPyPI Trusted Publisher
1. Create/log in to a **TestPyPI** account: https://test.pypi.org/ (separate from real PyPI).
2. Go to **Account → Publishing** → *Add a new pending publisher*
   (https://test.pypi.org/manage/account/publishing/).
3. Enter the table values above with environment **`testpypi`**. Save.
   - "Pending" is correct — the project doesn't exist on TestPyPI yet; the first successful upload
     creates it under this trust.

### HOP-3 — PyPI Trusted Publisher
1. Create/log in to a **real PyPI** account: https://pypi.org/.
2. **Account → Publishing** → *Add a new pending publisher*
   (https://pypi.org/manage/account/publishing/).
3. Enter the table values with environment **`pypi`**. Save.
   - ⚠️ This reserves the name `electric-blue` to your trust on first publish. (Name was confirmed
     AVAILABLE via PyPI JSON API dual-404; if the page reports it taken, **stop and escalate** — do
     not pick a fallback name without a decision, it changes the `pip install` handle.)

### HOP-1 — GitHub Environments
In the repo: **Settings → Environments** (https://github.com/dannySubsense/electric-blue/settings/environments).
1. **New environment** → name it exactly `testpypi`. No protection rules needed (rehearsal target).
2. **New environment** → name it exactly `pypi`. Then **add a protection rule:**
   **Required reviewers** → add yourself (`dannySubsense`).
   - 🔒 **This is mandatory, not optional.** This human approval is the *only* gate between a green
     pipeline and the immutable upload. Frank + the locked decision require it for the first publish.

> The environment names here MUST equal the `environment:` values in `release.yml`
> (`testpypi` on line 97, `pypi` on line 123) and the publisher configs above. Typos = `403`.

---

## Phase 2 — Rehearsal (TestPyPI dry-run, reversible)

Proves the OIDC trust, the build, the metadata, and the wheel-smoke all work **before** you risk real
PyPI. The `workflow_dispatch` run cannot reach real PyPI (`publish-pypi` is `if`-gated to tag pushes).

1. Trigger it: GitHub → **Actions → Release → Run workflow** → branch `main` → **Run workflow**.
   (Or `gh workflow run release.yml --ref main`.)
2. Watch the run. Expect: `build → check → smoke-wheel → publish-testpypi` all green, and
   **`publish-pypi` shown as Skipped**. The version-check step is also skipped (it's `push`-only) —
   that's correct for a dispatch run.
3. Confirm the package landed: https://test.pypi.org/project/electric-blue/ shows `0.1.0`. The
   in-workflow `Verify TestPyPI install` step also `pip install`s it (with `--extra-index-url` to
   pull real deps like `watchdog`/`requests` that aren't on TestPyPI).

If anything fails here, fix it and re-dispatch. **Nothing is on real PyPI yet.** Common failures:
`403` → identifier mismatch in Phase 1 (re-check owner/repo/workflow/environment, exact strings).

**The rehearsal leaves `0.1.0` on TestPyPI — that is expected, and you do nothing about it.** The
real tag run in Phase 3 re-runs `publish-testpypi` with the same filenames; the step is configured
with `skip-existing: true`, so it skips the already-uploaded file and proceeds. Do **not** delete
the TestPyPI release — deletion would not help anyway (PyPI/TestPyPI permanently reserve a filename
once uploaded, even after deletion), and it is unnecessary. There is no TestPyPI cleanup step.

---

## Phase 3 — The real publish (HFS-1) — ⚠️ point of no return is the reviewer approval

### Pre-flight checklist (all must be true)
- [ ] Phase 0 green; `main` clean at the SHA you intend to ship.
- [ ] HOP-1/2/3 complete; `pypi` environment has **you** as a required reviewer.
- [ ] Phase 2 rehearsal succeeded. (Leave the TestPyPI `0.1.0` upload in place — the real run skips it.)
- [ ] `pyproject.toml` `version` is `"0.1.0"`.
- [ ] **sdist eyeball (INV-7 backstop):** build locally and list the sdist contents — confirm no
      `.env`, no secrets, no stray paths are bundled:
      ```bash
      PATH="$PWD/.venv/bin:$PATH" python -m build
      tar tzf dist/electric_blue-0.1.0.tar.gz   # scan the file list
      rm -rf dist build src/*.egg-info *.egg-info
      ```
- [ ] README contains no "not yet published" note and does not advertise diarize (already merged —
      verify it survived: `grep -ic "deferred to 0.2.0" README.md` → 1).

### Push the tag
`origin` is SSH read-only-anon — the local SSH key (`majortom55`) cannot push. Use the same
masked inline-token HTTPS path this repo uses for every push:

Tag the **reviewed release commit** — the commit that passed the gate (currently `main` @
`c184c7a`), not just "whatever `main` is now." Confirm with `git rev-parse --short HEAD` on a
clean `main` before tagging.

```bash
git tag v0.1.0                       # tag the reviewed release commit (verify HEAD first)
GH_TOKEN=$(gh auth token)
git -c credential.helper= push \
  "https://x-access-token:${GH_TOKEN}@github.com/dannySubsense/electric-blue.git" v0.1.0 \
  2>&1 | sed "s/${GH_TOKEN}/***/g"
```

(`gh` is authed as `dannySubsense` with repo scope. The `sed` masks the token in any echoed URL.)

### Watch the run — and approve the gate
1. The tag push triggers `release.yml`. Now the **version-check step runs** (tag `v0.1.0` must equal
   `pyproject` `0.1.0`, else `build` fails with exit 1 — a deliberate fail-fast).
2. Chain runs `build → check → smoke-wheel → publish-testpypi` (the TestPyPI step skips the existing
   `0.1.0` from the rehearsal via `skip-existing` — nothing to clean up).
3. **`publish-pypi` PAUSES for required-reviewer approval** (the `pypi` environment gate). GitHub will
   show "Review pending." **This approval is the point of no return.** Open the run, read the job
   summary, and **only then click Approve.** Approving uploads to **real PyPI, irreversibly.**

---

## Phase 4 — Post-publish verification

```bash
python -m venv /tmp/eb-verify && source /tmp/eb-verify/bin/activate
pip install electric-blue
electric-blue --help        # expect exit 0 with usage
deactivate && rm -rf /tmp/eb-verify
```

- [ ] All five workflow jobs green (`publish-pypi` no longer skipped).
- [ ] `pip install electric-blue` succeeds in a clean venv.
- [ ] `electric-blue --help` exits 0.
- [ ] Visible at https://pypi.org/project/electric-blue/.
- [ ] (Optional) Write the GitHub Release notes for `v0.1.0` (the changelog vehicle — S-4 was
      deferred in favor of GitHub Releases).

Then update status memory / LORE: DDR-06 → **LIVE**.

---

## If something goes wrong

| Symptom | Cause | Action |
|---|---|---|
| `403` at a publish step | Trusted-Publisher identifier ≠ workflow (owner/repo/`release.yml`/env) | Fix the publisher config or GitHub env name to match exactly; re-run. Real PyPI untouched until the `pypi` gate. |
| `build` fails on "Verify tag matches" | tag `vX.Y.Z` ≠ `pyproject` version | Delete the tag, fix one side, re-tag. Nothing built/published. |
| `publish-testpypi` fails after a rehearsal | NOT a re-upload conflict — the step has `skip-existing: true`, so an already-uploaded `0.1.0` is skipped, not an error | A real failure here is OIDC (`403`, identifier mismatch) or network — fix that; re-uploading the same file is never the cause. |
| Bad `0.1.0` discovered AFTER real publish | PyPI is immutable | **Yank** `0.1.0` on PyPI (hides from new pins), bump to `0.1.1`, fix, re-tag. You cannot delete. This is why Phases 0–2 + the reviewer gate exist. |
| Secret found in the published sdist | no automated sdist scan (accepted residual G-6) | Yank immediately, rotate the secret, ship `0.1.1`. The `tar tzf` pre-flight is the control that should have caught it — do not skip it. |

---

## One-glance order

```
Phase 0  local: git clean + make gate + version 0.1.0
Phase 1  HOP-2 TestPyPI trusted publisher  (env testpypi)
         HOP-3 PyPI trusted publisher        (env pypi)
         HOP-1 GitHub Environments: testpypi (open) + pypi (REQUIRED REVIEWER = you)
Phase 2  Actions → Release → Run workflow (main)  → green through publish-testpypi, publish-pypi SKIPPED
         (rehearsal leaves 0.1.0 on TestPyPI — leave it; the real run skips it via skip-existing)
Phase 3  pre-flight checklist (incl. tar tzf eyeball)
         tag v0.1.0 on the reviewed commit + masked inline-token push
         watch → APPROVE the pypi reviewer gate  ← irreversible
Phase 4  pip install electric-blue in clean venv → verify → GitHub Release notes
```
