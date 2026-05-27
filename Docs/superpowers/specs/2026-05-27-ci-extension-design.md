# CI Extension: Frontend Checks, Migration Validation, Dependency Audit

**Date:** 2026-05-27  
**Issue:** #88 — Extend CI: frontend type check, build, migration validation, dependency audit

## Overview

The existing CI pipeline (`.github/workflows/ci.yml`) only runs backend pytest on pull requests. No frontend validation exists, meaning TypeScript errors, broken builds, and lint violations slip through undetected — a significant risk given that 30% of commits originate from the autonomous Dark Factory agent. This spec defines how to extend CI with parallel frontend validation and additional backend checks (migration sync verification and Python security auditing), all as required PR status checks.

## Requirements

1. A new parallel `frontend` CI job runs on every PR to `main`, executing: TypeScript type check, production build, ESLint (advisory), and npm audit at `--audit-level=high`.
2. The existing `test` job gains two new steps after pytest: `alembic check` (migration/model sync) and `pip-audit` (Python dependency vulnerability scan).
3. ESLint runs in advisory mode on day one (non-blocking) due to ~76 existing `no-explicit-any` violations. The `@ts-ignore` in `Settings.tsx:96` is fixed as part of this implementation.
4. Both jobs (`test` and `frontend`) are listed as required status checks in GitHub branch protection, so all checks must pass before a PR can merge.
5. Node.js 20 LTS is used in the frontend job, matching the runtime version available in this environment (Node 22 is also acceptable; 20 is the stable LTS choice).
6. `pip-audit` is installed ephemerally in CI (`pip install pip-audit`) — it does not go into `backend/requirements.txt`.
7. `alembic check` runs in the `backend/` working directory with `DATABASE_URL` set to the test PostgreSQL instance (reusing the existing `postgres` service already in the `test` job).

## Architecture

### Job Layout

```
PR → main
  ├── job: test (existing, extended)
  │     services: postgres:15-alpine
  │     steps:
  │       1. actions/checkout@v4
  │       2. setup-python@v5 (Python 3.12, pip cache)
  │       3. pip install -r backend/requirements.txt
  │       4. python -m pytest                        ← existing
  │       5. upload coverage artifact                ← existing
  │       6. pip install pip-audit
  │       7. pip-audit --severity high               ← NEW
  │       8. python -m alembic check                 ← NEW (env: DATABASE_URL)
  │
  └── job: frontend (new, parallel)
        steps:
          1. actions/checkout@v4
          2. setup-node@v4 (Node 20, npm cache, frontend/)
          3. npm ci (working-directory: frontend)
          4. npx tsc --noEmit                        ← NEW
          5. npm run build                           ← NEW
          6. npm run lint || true  (advisory)        ← NEW
          7. npm audit --audit-level=high            ← NEW
```

Both jobs run in parallel — the backend job is slower (DB spin-up + pytest), so the frontend job is expected to complete first. Total CI wall-clock time is bounded by the slower `test` job, not additive.

### Environment Variables for `alembic check`

The `alembic check` step needs `DATABASE_URL` (read by `app.core.config.Settings`). The existing step uses `TEST_DATABASE_URL` for pytest (which the test fixtures consume directly). The alembic step gets `DATABASE_URL` set explicitly in its `env:` block:

```yaml
- name: Check migration sync
  working-directory: backend
  env:
    DATABASE_URL: postgresql://test:test@localhost:5432/markethawk_test
  run: python -m alembic upgrade head && python -m alembic check
```

`alembic upgrade head` runs first to apply all migrations to the test DB before `alembic check` verifies that no model changes are missing a migration.

### Lint Advisory Mode

`npm run lint` is `eslint . --report-unused-disable-directives --max-warnings 0`. With the `|| true` suffix, a non-zero exit is allowed — violations appear in the job log but don't block the PR. The plan to harden:

- **Sprint 1 (now):** Fix the `@ts-ignore` in `Settings.tsx:96` (add a description: `// @ts-ignore: <reason>` or remove it). Run lint advisory.
- **Future sprints:** Progressively retype the 76 `any` annotations across 27 files. Once count reaches 0, remove `|| true` to enforce zero warnings.

### `pip-audit` Scope

`pip-audit --severity high` scans installed packages for CVEs at high or critical severity. Informational and medium vulnerabilities are reported but do not fail the build. This threshold matches the `npm audit --audit-level=high` baseline.

## Alternatives Considered

### A: Add all checks to the existing `test` job (monolithic)

Add frontend Node.js setup + all npm steps inline in the existing job, after pytest. Simpler workflow file, but:
- Serialises frontend checks behind Python + DB setup (slower)
- Mixes concerns: a frontend lint failure shows as a failing `test` job, making triage harder
- **Rejected** in favour of parallel jobs.

### B: Third-party security scanners (Snyk, Dependabot)

Snyk and Dependabot provide richer vulnerability databases than `pip-audit` / `npm audit`. However:
- Both require configuration and secrets (Snyk API key, Dependabot config file)
- `pip-audit` and `npm audit` are zero-config and sufficient for a first pass
- Dependabot PRs can be enabled separately without blocking CI
- **Deferred** — can be layered on top later without changing this spec.

### C: Make lint blocking from day one

Enforce `--max-warnings 0` immediately and fix all 76 `any` annotations as part of this issue. The typing backlog is a multi-sprint effort (27 files), and blocking all PRs until it's done creates unnecessary friction.
- **Rejected** — advisory mode with a hardening roadmap is the pragmatic path.

## Open Questions (non-blocking)

- Should Dependabot be enabled for automated dependency bump PRs (separate from this spec)?
- Should `npm audit` failures at `--audit-level=high` be made advisory too if transitive deps introduce unavoidable CVEs? (Evaluate on first hit.)
- Should `alembic check` failure send a Slack notification or just show as a red CI check?

## Assumptions

- **[Assumed]** GitHub branch protection for `main` is not yet configured. The spec assumes it will be set up as part of this work to make both jobs required. If branch protection already exists, it needs to be updated to add the new check names.
- **[Assumed]** Node 20 LTS is the target. The environment runs Node 22; either works with `actions/setup-node@v4`.
- **[Assumed]** `pip-audit` at `--severity high` will pass on the current `backend/requirements.txt`. If it flags known CVEs with no upstream fix, a `pip-audit --ignore-vuln <id>` whitelist entry is acceptable with a comment.
- **[Assumed]** The `alembic upgrade head` + `alembic check` sequence is idempotent and safe in the test DB context. Migrations are applied fresh each CI run since the postgres service is ephemeral.
