# CI Dependency Audit Repair — Design Spec

**Issue:** #848
**Revised:** 2026-09-16 (operator amendment after plan-gate review: OD1)

**Date:** 2026-09-16
**Status:** Ready for implementation
**Labels:** bug, size: S, infrastructure, direct-to-pr, ready-for-agent

## Overview / Problem Statement

Every open PR (all eleven open Dependabot PRs, e.g. #840) has been failing the
same three CI jobs since 2026-08, blocking all merges and keeping the two
"main is red" tickets (#810, #836) open. None of the three failures are caused
by product code — they are dependency/tooling drift:

1. **`test` job, "Dependency audit" step** — `pip-audit -r backend/requirements.txt`
   fails on `pyasn1==0.4.8` (PYSEC-2026-3455/3456/3457; fix `0.6.4`). The "Run
   tests" step never executes because the audit step fails first.
2. **`frontend` job, "Dependency audit" step** — `npm audit --audit-level=high`
   reports 10 advisories (8 high) across `axios`, `brace-expansion` (transitive
   via `eslint`), `browserslist`, and `react-router-dom`.
3. **`adapter-validate` job, "Schema-validate .factory/adapter.yaml" step** —
   `ModuleNotFoundError: No module named 'aiohttp'`. The step only installs
   `pyyaml`, but `factory_core.adapter` in `omniscient/dark-factory@main` now
   imports something that needs `aiohttp`. The two subsequent steps
   (mirror-drift assert, hooks parse) never run, so their state on today's
   factory is unknown.

## Requirements (from Q&A)

- Fix all three diagnosed failure points so the corresponding CI jobs pass.
- No product-code (application logic) changes are in scope — this is a
  dependency-pin, lockfile, and CI-workflow change only.
- `pip-audit -r backend/requirements.txt` and `npm audit --audit-level=high`
  must exit 0 on the branch.
- The PR body must list every advisory ID addressed and the version that
  resolves it (including any that are suppressed rather than fixed — see
  react-router-dom below).
- Auth/JWT tests must be run after the `python-jose` bump, since it is the
  JWT library backing `backend/app/routers/auth.py` and the cookie-based auth
  flow.
- If a fix requires crossing a major version boundary for any npm package,
  do not perform that bump in this PR. Ship every other fix and handle the
  blocked package per the fallback below — do not hold the entire PR.
- Scope boundary (Q1): fix only the three diagnosed failures plus what they
  mechanically require (see "In scope" below). Any other CI check discovered
  red for an unrelated reason is out of scope — call it out explicitly in the
  PR body and file a follow-up issue; do not attempt a fix unless it is the
  same class of trivial tooling drift (e.g. another missing `pip install` in
  a workflow step) confined to workflow/lockfile files.
- `docker-backend`/`docker-frontend` (`.github/workflows/docker-build.yml`)
  and the two CodeQL/`Analyze` checks (`.github/workflows/codeql.yml`) are
  separate workflow files from `ci.yml` — touching either is a signal the
  change has left this ticket's boundary.

## Architecture / Approach

### 1. `pip-audit` / pyasn1 (backend)

`python-jose[cryptography]==3.4.0` (`backend/requirements.txt:65`) hard-pins
`pyasn1<0.5.0`, which is why `pyasn1` sits at the vulnerable `0.4.8`. Per the
issue's operator comment (verified on PyPI), `python-jose` `3.5.0` relaxes its
`pyasn1` constraint to `>=0.5.0`. Fix:

- Bump `python-jose[cryptography]` to `==3.5.0` (or `>=3.5.0`) in
  `backend/requirements.txt`.
- Constrain/pin `pyasn1>=0.6.4` in the same file.
- Run the backend auth/JWT test suite after the bump (JWT encode/decode,
  login/refresh cookie flow) to confirm no behavioral regression.
- Update the dated comment block at `backend/requirements.txt:56-64` — it
  currently documents the `pyasn1<0.5.0` constraint and the accepted
  `CVE-2026-30922` ReDoS as a fact of the pin; once the bump lands, this is no
  longer accurate and must be corrected (or removed if no longer relevant).
- Remove the now-obsolete `--ignore-vuln CVE-2026-30922` from the `pip-audit`
  invocation in `.github/workflows/ci.yml` (~line 47-62), since the underlying
  `pyasn1` vulnerability is fixed rather than ignored once `pyasn1>=0.6.4`
  lands.
- Remove the matching `CVE-2026-30922` entry from `.trivyignore` (this
  advisory also feeds the `sast` job's Trivy scan).
- Leave the `PYSEC-2022-42969` / `PYSEC-2026-1325` ignores (ecdsa Minerva
  timing side-channel, pulled in transitively) untouched — unrelated to this
  issue, no upstream fix exists.
- If PyPI in fact has no `python-jose` release admitting `pyasn1>=0.6.4` by
  implementation time (contradicting the operator's verification), fall back
  to the issue's documented alternative: add
  `--ignore-vuln PYSEC-2026-3455 --ignore-vuln PYSEC-2026-3456
  --ignore-vuln PYSEC-2026-3457` to the `pip-audit` step with a dated
  justification comment, plus a follow-up ticket to replace `python-jose`.
  Prefer the bump; only use this fallback if the bump is genuinely
  unavailable.

### 2. `npm audit` (frontend)

Resolve each flagged package to its fix version, preferring lockfile-only
changes where the `package.json` range already admits the fix (`npm audit
fix` or an explicit `npm install <pkg>@<fix-version>` that stays within the
declared semver range):

- `axios` (`^1.17.0`, nine GHSA entries) — bump to the fix version within
  `^1.x`.
- `brace-expansion` (transitive via `eslint`, `^9.39.4`) — resolve via
  `npm audit fix` / lockfile update; no direct `package.json` edit expected
  unless the fix requires bumping `eslint` itself.
- `browserslist` (transitive, `^4.24.0` observed in the lockfile) — resolve
  via lockfile update.
- `react-router-dom` (`^7.17.0`, GHSA-h8fp-f39c-q6mh + an SSR hydration
  `deserializeErrors` advisory):
  - If a `7.x` release resolves both advisories, bump within range
    (lockfile-only where possible).
  - If the fix requires crossing the v7→v8 major boundary (Q2), **do not**
    perform that bump in this PR. Instead:
    1. Ship every other fix in this PR.
    2. Add a narrowly-scoped, dated, justification-commented suppression for
       only the react-router-dom advisory IDs in the `frontend` job's
       "Dependency audit" step (`.github/workflows/ci.yml:104-106`), mirroring
       the `--ignore-vuln` precedent and comment style already used for the
       backend `pip-audit` step and `.trivyignore`. `npm audit` has no native
       per-advisory ignore flag, so implement this as `npm audit --json`
       piped through a small allowlist filter (or an `overrides` entry, if
       the fix version turns out to be reachable transitively without a
       direct major bump) — a workflow/lockfile-only change.
    3. The suppression must name each GHSA ID with a one-line reachability
       argument. Note: this app is a Vite SPA using `BrowserRouter` (see
       `frontend/src/App.tsx:2`) with no server-side rendering, so the SSR
       hydration `deserializeErrors` advisory is plausibly unreachable here —
       verify and state this explicitly in the comment.
    4. File a follow-up issue for the v7→v8 migration and reference it in the
       suppression comment.
    5. State plainly in the PR body that this one advisory is suppressed
       (not fixed), so "all ten checks green" is not misread as "zero
       outstanding advisories."

### 3. `adapter-validate` / aiohttp

`.github/workflows/ci.yml`'s `adapter-validate` job (~line 175-176) currently
runs only `pip install pyyaml` before invoking `factory_core.adapter`, which
now transitively needs `aiohttp` on `omniscient/dark-factory@main`. Fix:

- Change the install step to `pip install pyyaml aiohttp` (matching what the
  factory image itself installs, per the issue).
- If `_dark-factory` (the cloned `omniscient/dark-factory` checkout at that
  step) ships its own `requirements.txt`, prefer installing that directly
  (`pip install -r _dark-factory/requirements.txt` or equivalent) so the CI
  step doesn't drift out of sync with the factory's own dependency list again;
  otherwise, the explicit `pip install pyyaml aiohttp` is sufficient.
- After the fix, confirm the two steps that were previously skipped
  (mirror-drift assert, hooks parse) actually pass — their status was unknown
  before this fix because the job died before reaching them.

## Operator decisions

- **OD1 — mirror-drift assert (2026-09-16, plan gate).** The `adapter-validate` job's "Assert
  mirrored values equal factory defaults" step fails on `safety` because #808 added local
  hardening entries to `.factory/adapter.yaml` that the factory defaults do not carry; the job never
  reached that step before this ticket's `aiohttp` fix. Because "Factory adapter validation" is a
  **required** status check on `main`, leaving it red would keep every PR unmergeable and defeat
  this ticket, so the Q1 scope boundary is extended to that one workflow step: the assert becomes
  superset-tolerant for list-valued `safety` keys (local additions allowed; removals, missing keys
  and all other mirrored blocks still must match exactly). `.factory/adapter.yaml` itself is not
  edited (B1 of epic #792, #844, owns it) and nothing in `omniscient/dark-factory` changes. Whether
  to upstream #808's additions is filed as a follow-up (plan Task 7.4).

## Alternatives Considered

1. **Ignore/suppress all three failures instead of fixing them.** Rejected —
   the whole point of the ticket is to unblock real security-relevant
   dependency updates; blanket-ignoring would leave the repo on genuinely
   vulnerable versions and doesn't address the `aiohttp` import error at all
   (that one has no "ignore" lever — the job hard-crashes).
2. **Hold the entire PR until react-router-dom's major-version migration is
   separately planned and approved.** Rejected per Q2 — this inverts the
   cost-benefit of a `size: S`, `direct-to-pr` ticket whose purpose is
   unblocking 11 stuck Dependabot PRs now; a scoped, documented suppression
   for the one blocked advisory (with a follow-up issue) ships the other four
   fixes immediately instead.
3. **Expand scope to fix every currently-red CI check** (docker-backend,
   docker-frontend, CodeQL, Analyze), even ones not diagnosed in the issue.
   Rejected per Q1 — those live in separate workflow files, are undiagnosed,
   and fixing them could require product-code judgment calls; out-of-scope
   discoveries get called out and filed as follow-ups instead.

## Open Questions (non-blocking)

- Whether `omniscient/dark-factory@main`'s `factory_core.adapter` needs only
  `aiohttp` or additional transitive packages beyond what `pip install pyyaml
  aiohttp` provides — only confirmable by actually running the adapter-validate
  step against the current `main` of that repo. If a further
  `ModuleNotFoundError` surfaces after adding `aiohttp`, install the additional
  package(s) needed; this stays within the same "tooling drift" fix.
- Whether the mirror-drift assert and hooks-parse steps (previously never
  reached) pass once the job runs to completion — unknown until verified live.

## Assumptions (flagged)

- **[ASSUMPTION]** `python-jose==3.5.0` on PyPI declares `requires_dist:
  pyasn1>=0.5.0` and is otherwise a drop-in replacement for `3.4.0` for this
  codebase's usage (JWT encode/decode, no removed/renamed APIs touched by
  `backend/app/routers/auth.py`). This was verified by the issue's operator
  comment but must be re-verified against the live PyPI registry at
  implementation time, since registry state can change.
- **[ASSUMPTION]** The `axios`, `brace-expansion`, and `browserslist`
  advisories are all resolvable via lockfile-only bumps within their existing
  `package.json` semver ranges (no major-version crossing needed for any of
  them) — this could not be verified against the live npm registry during
  refinement (no network access in this phase) and must be checked at
  implementation time. Only `react-router-dom` was flagged in Q&A as at risk
  of requiring a major bump.
- **[ASSUMPTION]** No test or code in this repository depends on the specific
  `ecdsa==0.19.2` / `pyasn1<0.5.0` pin behavior beyond satisfying
  `python-jose`'s own constraint — i.e., bumping these versions will not
  break any test that pins exact JWT token byte output or similar.
