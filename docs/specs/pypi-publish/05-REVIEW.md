# Spec Review: pypi-publish (DDR-06)

**Sprint:** pypi-publish
**DDR:** DDR-06-pypi-publish.md
**Documents reviewed:** 01-REQUIREMENTS.md, 02-ARCHITECTURE.md, 04-ROADMAP.md (+ source DDR-06)
**Reviewer:** spec-reviewer
**Date:** 2026-06-24
**Verdict (current, iteration 2):** **PASS** — all 9 prior gaps closed; no new blocking inconsistency.

> The PASS verdict below supersedes the iteration-1 PASS-WITH-GAPS. The full iteration-1
> review is retained for the audit trail; the authoritative re-verification is the
> **## Re-Review (Iteration 2)** section at the bottom.

> Note on 03-UI-SPEC.md: intentionally absent. This is a packaging/CI feature with no
> user-facing UI. Its absence is by design and is NOT counted as a gap.

---

## Summary

The spec set is coherent, well-sequenced, and implementable. The job chain
(`build → check → smoke-wheel → publish-testpypi → publish-pypi`), the OIDC/Trusted-Publishing
posture, the static-version + tag-enforcement mechanism, and the forge-slice vs human-operational
separation all hold consistently across 01/02/04 and match the locked decisions. Every user story
traces to an architecture component and at least one roadmap slice; there are no orphan slices.

The review found **no blocking (FAIL) issue** and **no fundamental inconsistency requiring HALT**.
It did find **4 MEDIUM** and **5 LOW** issues that should be resolved or consciously accepted before
human approval. The two highest-value findings are concrete and likely to bite an implementer:

1. The locked `--strict` twine-check mandate may **fail** because the spec requires *both* an SPDX
   `license = "MIT"` expression *and* the deprecated `License ::` trove classifier (G-1).
2. The documented TestPyPI-conflict recovery ("use a `dev` suffix tag") is **incompatible with the
   trigger regex**, which only matches `vX.Y.Z` — a `v0.1.0.dev1` tag will not start the workflow (G-2).

> All nine findings below were addressed in the iteration-2 fix round. See the bottom section.

---

## Traceability: Requirements → Architecture → Roadmap

| User Story | Architecture Coverage | Roadmap Slice | Status |
|------------|----------------------|---------------|--------|
| US-1 Release by tag push | `release.yml` trigger + `needs:` chain | S-3 | OK |
| US-2 Build validation gate | `build`, `check`, `smoke-wheel` jobs | S-3 | OK |
| US-3 TestPyPI gate | `publish-pypi: needs: [publish-testpypi]` | S-3 | OK (see G-2, G-5) |
| US-4 Tag/version consistency | version-check step in `build` | S-3 | OK |
| US-5 Install via pip | `[project.scripts]` + publish | S-1, S-3, HFS-1 | OK |
| US-6 Local extra installable | `[local]` extra; README advertises | S-1, S-2 | OK (see G-7) |
| US-7 ffmpeg docs + README cleanup | README edit | S-2 | OK |
| US-8 Accurate PyPI metadata | pyproject.toml additions + `twine check` | S-1 | OK (see G-1) |
| US-9 No long-lived credentials | OIDC; `id-token: write` on publish jobs only | S-3, HOP-2/3 | OK |

**AC-level coverage:** All 9 user stories' acceptance criteria map to a slice. No AC is orphaned.
No roadmap slice lacks a requirement/DDR home (S-4 CHANGELOG traces to DDR-06 §5 item 5; HOP-1/2/3
and HFS-1 trace to US-9/US-5 and the DDR operational checklist).

**AC count discrepancy (G-9):** 02-ARCHITECTURE §Overview and the orchestration brief both state
"35 acceptance criteria." The actual checkbox count in 01-REQUIREMENTS is **32**
(US-1:4, US-2:4, US-3:5, US-4:3, US-5:2, US-6:2, US-7:4, US-8:5, US-9:3). Coverage is complete
regardless; the stated total is just wrong. LOW.

---

## Drift Items — Carried into Roadmap?

The architecture flagged 5 DDR-vs-code drift items (the brief named 4; the 5th is the naming fix).
Each is confirmed carried into a slice and not contradicted elsewhere:

| Drift item | Carried into | Confirmed | Note |
|-----------|--------------|-----------|------|
| SPDX `license = "MIT"` | S-1 done-when | Yes | But see G-1 — interacts badly with the License classifier under `--strict` |
| README `your-org` → `dannySubsense` | S-2 step 2 + done-when | Yes | — |
| Canonical TestPyPI upload URL `https://upload.test.pypi.org/legacy/` | S-3 done-when | Yes | Contradicts stale AC text in 01 (G-3) |
| TestPyPI install-check needs `--extra-index-url` | S-3 done-when | Yes | Contradicts stale AC text in 01 (G-3) |
| `wheel-smoke` → `smoke-wheel` naming | Used consistently in 02/04 | Yes | — |

---

## Gaps

| # | Gap | Severity | Owns the fix |
|---|-----|----------|--------------|
| G-1 | Spec mandates BOTH SPDX `license = "MIT"` (US-8) AND the `License :: OSI Approved :: MIT License` trove classifier (US-8), while the roadmap mandates `twine check --strict`. Under current packaging/twine tooling, declaring a SPDX license expression *and* a `License ::` classifier emits a deprecation warning; `--strict` turns that warning into a non-zero exit, which would FAIL the `check` job and block every release. The two ACs are potentially mutually exclusive under the locked `--strict` choice. | **MEDIUM** | 01 (drop the `License ::` classifier from US-8 when SPDX is used) + 02/04 (align classifier list and confirm `--strict` posture against a real `python -m build && twine check --strict`) |
| G-2 | Documented TestPyPI version-conflict recovery (01 Edge Cases; 02 §Failure Modes option 1) is "push a `dev`-suffix tag (e.g. `v0.1.0.dev1`)". The trigger pattern `v[0-9]+.[0-9]+.[0-9]+` (anchored, literal dots) does **not** match `v0.1.0.dev1`, so that tag will never start `release.yml`. The recommended recovery path cannot execute. | **MEDIUM** | 02 + 01 (correct the recovery guidance; options: widen trigger, add `workflow_dispatch`, or rely solely on manual TestPyPI deletion) |
| G-3 | 01-REQUIREMENTS AC US-3 bullet 1 literally specifies `repository-url: https://test.pypi.org/legacy/` and bullet 2 specifies the bare `pip install --index-url https://test.pypi.org/simple/ electric-blue`. 02/04 deliberately override both (canonical `upload.test.pypi.org` URL; add `--extra-index-url`). The override is correct and acknowledged as a drift fix, but the requirements text was never reconciled — an implementer or QC reading the AC verbatim will see the shipped workflow as non-conformant, and 02 even states the bare install command "will fail." | **LOW** | 01 (update US-3 AC text to match the resolved architecture, or annotate the AC as superseded) |
| G-4 | `smoke-wheel` (and ci.yml per 02) runs `sudo apt-get install -y ffmpeg` with no preceding `apt-get update`. On GitHub-hosted runners this usually works off the preloaded cache but can intermittently fail when the index is stale. No failure handling specified. | **LOW** | 02/04 (add `apt-get update` or document reliance on the runner cache) |
| G-5 | There is no isolated TestPyPI rehearsal path and no `workflow_dispatch`. The only route to TestPyPI is a real `vX.Y.Z` tag that, on success, proceeds straight to immutable PyPI. The sole barrier between an unrehearsed first tag push and a permanent PyPI artifact is the `pypi`-environment required reviewer, which HOP-1 marks **"recommended,"** not mandatory. Given PyPI immutability (a core DDR risk), an optional gate is thin protection for the very first publish. | **MEDIUM** | 04 (HOP-1) / human decision — make the `pypi` required reviewer mandatory for 0.1.0, or add a dry-run mechanism |
| G-6 | Immutability defense (build→check→smoke-wheel→testpypi) validates functionality and metadata but performs **no sdist content scan for secrets/sensitive paths**, which 02 itself names the highest-impact, yank-proof failure (INV-7). The only control is human PR review (INV-7 in 04 §PR Workflow). Acceptable for 0.1.0 but should be an explicit, accepted residual rather than implied. | **MEDIUM** | 02/04 (state the residual explicitly; optionally add an sdist-content check before publish) |
| G-7 | US-6 AC2 ("local backend transcription completes without import errors") is a runtime-functional criterion. It is only indirectly covered: `smoke-wheel` installs `[local]` and runs `pytest -m smoke`, but the spec does not assert the smoke suite actually exercises a local-backend transcription, and HFS-1 post-publish verification only runs `--help`. Coverage depends on the assumed (DDR-01) smoke suite content. | **LOW** | 01/02 (confirm the smoke suite exercises the local path, or mark US-6 AC2 as covered-by-assumption) |
| G-8 | Classifiers advertise Python 3.10/3.11/3.12, but `smoke-wheel` runs only on 3.12. No test proves the wheel imports/installs on 3.10 or 3.11. Low risk for a pure-Python wheel, but the advertised support is unverified. | **LOW** | 02/04 (optional: matrix the smoke-wheel job, or accept as documented risk) |
| G-9 | "35 acceptance criteria" stated in 02 §Overview (and the brief) vs 32 actual checkboxes in 01. Cosmetic; coverage is complete. | **LOW** | 02 (correct the count) |

A secondary technical inaccuracy (not a standalone gap): 02 §`check` claims plain `twine check`
"exits non-zero on any warning when called without `--strict`." That is incorrect — plain
`twine check` returns 0 on warnings; only `--strict` fails on them. The net resolution (use
`--strict`) is right, so outcome is unaffected, but the rationale text is wrong and feeds the
false comfort behind G-1.

---

## Identified Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `--strict` check fails on SPDX-license + License-classifier combo, blocking all releases | M | H (blocks publish entirely) | Resolve G-1 before HFS-1; validate locally with `python -m build && twine check --strict dist/*` |
| Unrehearsed first tag reaches immutable PyPI (no isolated dry-run; reviewer optional) | M | H (immutable) | Make `pypi` required reviewer mandatory for 0.1.0 (G-5); the in-line chain still catches bad artifacts |
| Secret/sensitive path baked into sdist, published, then only yankable | L | H (yank is soft; record persists) | INV-7 PR review; consider sdist content scan (G-6) |
| TestPyPI conflict on a real release blocks the legit publish; documented recovery is non-functional | M | M | Fix G-2 recovery guidance; or delete TestPyPI release manually before re-pushing the same `vX.Y.Z` |
| PyPI name `electric-blue` claimed between D1 check and publish | L | M | D1 resolved (dual-404); claim window small; name is a pending-publisher reservation on first config |
| `apt-get install ffmpeg` flake without `update` | L | M (blocks smoke gate, not prod) | G-4 |

---

## Assumptions

| Assumption | Impact if Wrong |
|-----------|-----------------|
| `pytest -m smoke` suite exists and passes on a clean wheel install (from DDR-01) | `smoke-wheel` gate fails; no release; this DDR adds no smoke tests |
| `tests/test_install_editable.py` is not `@pytest.mark.smoke` and its `src/` path assertion lives in the function body (so `-m smoke` collects-but-skips it without a collection error) | If module-level code asserts the path, `smoke-wheel` collection breaks on the non-editable install (INV-14 concern) |
| `LICENSE` file exists in repo root; hatchling bundles it automatically | sdist/wheel missing license; `twine check` / metadata incomplete |
| `requires-python` in pyproject.toml is present and consistent with the 3.10–3.12 classifiers | Install on unsupported interpreters; classifier/runtime mismatch |
| Runner has (or can `apt-get`) ffmpeg; `imageio-ffmpeg` fallback branch never reached in smoke | smoke test ffmpeg lookup fails |
| Danny completes HOP-1/2/3 before HFS-1; env names match publisher records exactly | Publish jobs 403 on OIDC claim mismatch |
| Current packaging tooling tolerates SPDX expression + License classifier under `--strict` | See G-1 — may not hold |

---

## Open Questions

| Question | Status | Needs |
|----------|--------|-------|
| Keep the `License ::` trove classifier alongside SPDX `license = "MIT"`, or drop it to survive `--strict`? (G-1) | Open | Human + local `twine check --strict` confirmation |
| Make the `pypi`-environment required reviewer mandatory (not "recommended") for the first publish? (G-5) | Open | Human decision |
| How is a TestPyPI-only dry-run performed given the trigger excludes `dev`-suffix tags and there's no `workflow_dispatch`? (G-2) | Open | Human decision (widen trigger / add dispatch / manual-delete-only) |
| Reconcile stale US-3 AC text (URL + `--extra-index-url`) with the resolved architecture. (G-3) | Open | 01 edit or annotation |

> Per locked decisions, the following are NOT reopened: 0.1.0 ships `local`-only with `diarize`
> deferred and excluded from advertised surface; D1 name resolved AVAILABLE; D2 OIDC/no-token;
> D3 mandatory TestPyPI gate; D4 `v0.1.0`; D5 static version + tag==version; D8 no ffmpeg extra;
> SPDX license form. The docs are internally consistent with all of these (G-1 is a tooling
> interaction with the SPDX choice, not a challenge to the decision).

---

## Approval Checklist

### Requirements (01)
- [ ] Reviewed by human
- [ ] Acceptance criteria are testable
- [ ] US-3 AC text reconciled with resolved architecture (G-3) or accepted as superseded
- [ ] Out of scope (diarize deferral, no ffmpeg extra, static version) is acceptable

### Architecture (02)
- [ ] Reviewed by human
- [ ] G-1 resolved: confirmed `twine check --strict` passes with the chosen license/classifier combination
- [ ] G-2 resolved: TestPyPI-conflict recovery guidance is executable under the trigger pattern
- [ ] AC count corrected (G-9); `twine check` rationale text corrected
- [ ] Job contracts and OIDC claim table are correct

### Roadmap (04)
- [ ] Reviewed by human
- [ ] Forge slices (S-1/S-2/S-3) vs HOP-1/2/3 vs HFS-1 ordering confirmed
- [ ] G-5 decided: `pypi` required reviewer mandatory-or-accepted-optional for 0.1.0
- [ ] G-4 addressed (apt-get update or accepted)
- [ ] Slices are appropriately sized; no circular dependencies (confirmed)

### Overall
- [ ] G-1 and G-2 (MEDIUM, concrete blockers/contradictions) resolved or consciously accepted
- [ ] G-5 and G-6 (MEDIUM, immutability posture) resolved or accepted as residual
- [ ] All open questions resolved
- [ ] Ready for implementation

---

## Re-Review (Iteration 2)

**Date:** 2026-06-24
**Scope:** Confirm the iteration-1 gap list (4 MEDIUM, 5 LOW) is closed and that the parallel
edits to 01 (one agent) and 02/04 (another agent) introduced no new contradiction. Special
attention to G-2 cross-doc consistency and the `workflow_dispatch` job-graph logic.

**Verdict: PASS.** All 9 gaps closed. No new blocking inconsistency. One minor operational
residual newly surfaced (R-1 below), already covered by the documented recovery path.

### Per-gap status

| # | Sev | Status | Evidence |
|---|-----|--------|----------|
| G-1 | MED | **CLOSED** | 02 §check (02:200-211) corrected: plain `twine check` returns 0 on warnings, only `--strict` fails on `readme_renderer` rendering warnings — NOT on license/classifier. Empirical confirmation added (hatchling 1.5.0 / twine 6.2.0, `--strict` exit 0). SPDX `license="MIT"` + `License ::` classifier KEPT in both 01 US-8 (01:168,175) and 02 (02:53,63). No doc implies the combo is a check risk. |
| G-2 | MED | **CLOSED** | `workflow_dispatch: {}` trigger added (02:111, 04:218). `publish-pypi` if-gated `github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')` (02:336). dev-suffix recovery REMOVED from 01 Edge Cases (01:197 now "manually delete… then re-run the release workflow") and from 02 (02:549-550 explicit "does NOT match the trigger regex… Do not use"). Recovery consistent + executable across 01/02/04. See sub-checks below. |
| G-3 | LOW | **CLOSED** | 01 US-3 now uses canonical `https://upload.test.pypi.org/legacy/` (01:111) and `--extra-index-url https://pypi.org/simple/` (01:113). Matches 02:301,307. No 01↔02 contradiction. |
| G-4 | LOW | **CLOSED** | `sudo apt-get update` precedes install in 02 (02:240-241) and S-3 done-when requires it (04:268). |
| G-5 | MED | **CLOSED** | `pypi` reviewer MANDATORY in HOP-1 (04:332-334) with done-when enforcing it (04:340); `testpypi` needs none. Mirrored in 02:494. |
| G-6 | MED | **CLOSED** | Explicit "Accepted Residuals" section in 02 (02:569-585) and 04 (04:451-461); INV-7 PR review named as the control. |
| G-7 | LOW | **CLOSED** | 01 US-6 AC2 annotated covered-by-assumption (01:144-145). |
| G-8 | LOW | **CLOSED** | 3.12-only smoke documented as accepted residual (02:582-585, 04:459-461). |
| G-9 | LOW | **CLOSED** | "32 acceptance criteria" (02:14). Recount confirms 32 (4+4+5+3+2+2+4+5+3). |

### G-2 targeted sub-checks (workflow_dispatch job-graph)

- **(a) dispatch cannot reach real PyPI:** on `workflow_dispatch`, `github.event_name` is
  `workflow_dispatch`, so the `publish-pypi` `if:` is false → job skipped. Confirmed (02:336,
  353-355; job-graph diagram 02:365-366; done-when 04:277-278). Real PyPI is unreachable on a
  rehearsal run.
- **(b) recovery consistent + executable in 01 and 02/04:** 01:197, 02:545-550, and the HFS-1
  optional rehearsal note (04:405-406) agree — delete the TestPyPI release, then re-trigger via
  `workflow_dispatch` or re-push the same `vX.Y.Z`. No residual `dev`-suffix advice anywhere.
- **(c) version-check survives a non-tag dispatch run:** the version-check step is gated
  `if: github.event_name == 'push'` (02:145, pattern 02:394, done-when 04:264), so on a
  `workflow_dispatch` run (branch ref, not tag) it is skipped and the build proceeds. No break.

### New / residual findings

- **R-1 (LOW, residual — newly surfaced by the G-2 fix, non-blocking):** because `version` is
  static `0.1.0`, a `workflow_dispatch` rehearsal uploads `0.1.0` to TestPyPI and occupies that
  version slot. The subsequent real `v0.1.0` tag run will then hit the documented TestPyPI
  conflict (02:540-550) and require the manual-delete recovery before `publish-testpypi`
  succeeds. This is inherent to rehearsing an immutable-versioned package, not a contradiction,
  and is already covered by the G-2 recovery path and the HFS-1 optional-rehearsal note. No
  action required for 0.1.0; worth a one-line operator note if a future version automates
  rehearsal.
- No other new inconsistency. Cross-doc terms ("five-job chain", `smoke-wheel` naming, OIDC
  claim table, slice→US coverage) remain aligned across 01/02/04. Locked decisions untouched.

### Minor pre-existing wording (not introduced this round, not blocking)

- 01 US-2 AC2 and US-8 AC1 name plain `twine check dist/*` while 02/04 implement `--strict`.
  The AC intent ("exits 0 … with no warnings") is exactly what `--strict` enforces, so outcome
  is consistent; the literal command string in 01 is just less specific. Optional tidy, not a gap.

**Bottom line:** the spec set is internally consistent and implementation-ready. Remaining
open-question checkboxes in the iteration-1 Approval Checklist are now satisfied by the fixes
(G-1 empirically confirmed, G-2 via workflow_dispatch, G-3 reconciled, G-5 mandatory). Human
approval can proceed.
