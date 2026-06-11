# Ruff CI Enforcement + Lint Cleanup

> Tracking issue: [#285](https://github.com/omniscient/markethawk/issues/285)

## Overview

ruff is the documented linting tool for `backend/`, configured in `backend/pyproject.toml`
with rules `E, W, F, I`. It runs in pre-commit hooks, but the dark-factory bypasses
pre-commit for ~66% of commits. As a result `main` currently has 65 auto-fixable ruff
violations while CI shows green — a false quality signal. This issue adds a blocking ruff
check to CI and one-shot-cleans the existing violations.

## Requirements

1. `ruff check backend/` exits 0 on `main` after the PR merges.
2. Any PR introducing a ruff violation must fail the `test` CI job before merging.
3. `ruff format --check` is **not** included in this change — formatting drift is a separate
   concern and `main` formatting status is unverified; scope this to lint only.
4. The implement agent must verify the `.github/workflows/ci.yml` change actually landed on
   the remote branch after push (the factory GH_TOKEN may silently drop workflow-file changes
   if it lacks `workflow` scope). If the file is absent on the remote, the PR body must flag
   this loudly and request manual application by a human with a `workflow`-scoped token.

## Architecture / Approach

### Step 1 — One-shot lint fix

Run `ruff check --fix .` inside `backend/` and commit the result:

```bash
cd backend && ruff check --fix . && cd ..
git add backend/
git commit -m "fix(#285): apply ruff --fix, clear 65 auto-fixable lint errors"
```

No manual review needed — all 65 violations are auto-fixable (per issue body, verified
2026-06-09).

### Step 2 — CI enforcement

Add a `Lint (ruff)` step to the existing `test` job in `.github/workflows/ci.yml`, positioned
**after "Install dependencies" and before "Run tests"** so lint failures fast-fail cheaply:

```yaml
      - name: Lint (ruff)
        working-directory: backend
        run: ruff check .
```

`ruff` is already a transitive dependency via the dev toolchain; verify it is present in
`backend/requirements.txt` or add it explicitly. No additional install step is needed if ruff
is already in the requirements file.

### Step 3 — GH_TOKEN workflow scope verification

After `git push`, the implement agent must verify the workflow file landed:

```bash
git fetch origin
git log origin/<branch> -- .github/workflows/ci.yml | head -1
```

- **If the commit is present**: proceed normally.
- **If absent**: the factory GH_TOKEN lacked `workflow` scope and GitHub silently stripped the
  change. In this case:
  - Open the PR with the lint-fix commit only (Step 1).
  - Include a prominent warning in the PR body:

    > ⚠️ **Manual action required**: The `.github/workflows/ci.yml` change could not be pushed
    > (factory token lacks `workflow` scope). To complete acceptance criterion #2, apply the
    > following change manually and push with a `workflow`-scoped token:
    > ```yaml
    >       - name: Lint (ruff)
    >         working-directory: backend
    >         run: ruff check .
    > ```
    > Position it after "Install dependencies" and before "Run tests" in the `test` job.

## Alternatives Considered

### Include `ruff format --check` in CI
Rejected. The acceptance criteria scope to lint only (`ruff check backend/` exits 0). The
issue body marks `ruff format --check` as optional ("if desired"). Formatting status on `main`
is unverified — adding it risks a second unverifiable failure mode. A follow-up ticket can
address formatting drift independently.

### Separate PRs for lint fix and CI step
Rejected. The lint fix is meaningless without the CI gate (dark-factory will re-introduce
violations). Both changes belong in one PR. If the CI step cannot be pushed (workflow scope),
that is surfaced explicitly in the PR body rather than silently dropped.

## Assumptions

- ruff is already available in the CI environment via `pip install -r backend/requirements.txt`.
  If not, a `pip install ruff` step is needed; the implement agent should check.
- All 65 current violations are genuinely auto-fixable (stated in issue body, verified
  2026-06-09 — implement agent should confirm `ruff check --fix .` exits 0 with no residual
  errors before committing).
- The `test` job is the correct home for the ruff step (backend CI job). The `frontend` and
  `migration-check` jobs are unaffected.

## Open Questions

- Whether the factory GH_TOKEN has been granted `workflow` scope since the issue was filed
  (2026-06-09). If it has, Step 3 verification will confirm and no manual action is needed.
