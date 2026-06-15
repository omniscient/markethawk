# CI Security Hardening — F-CI-01 Design

**Date:** 2026-06-15  
**Issue:** #378  
**Status:** Spec

## Overview

The Defensive Security Review (2026-06-12) identified finding F-CI-01: CI/CD pipelines surface vulnerabilities but do not block on them, the PR-gating workflow carries an overly-broad token, and deployment accepts unvalidated shell input. Observed live on PR #366 publish run `27417003540`: all three Trivy scan jobs failed yet the images published. A compromised CI step also acquires write-capable token scope.

This spec covers the four remediation items from F-CI-01:

1. **Trivy blocking gate** — exit-code 1 on HIGH/CRITICAL CVEs (`ci-publish.yml`)
2. **Least-privilege token** — `permissions: contents: read` on `ci.yml`
3. **SAST coverage** — CodeQL workflow (Python + JS) + Semgrep step in `ci.yml`
4. **Injection hardening** — validate `inputs.image_tag` in `deploy.yml` before SSH

## Current State

The `ci-publish.yml` Trivy fix and workflow-level permissions block have already been applied on this branch (see lines 8–12 and 127–135). Items 1 remains complete. This spec governs items 2–4.

## Requirements

- **R1** `ci.yml` must declare `permissions: contents: read` at the workflow level, eliminating the repo-default write token inherited by the test, frontend, migration-check, and factory-tests jobs.
- **R2** A new `.github/workflows/codeql.yml` workflow must run CodeQL analysis on `push` to `main` and on all pull requests targeting `main`, covering both `python` and `javascript` language matrices.
- **R3** The `codeql.yml` workflow must upload SARIF results to the GitHub Security tab (requires `security-events: write`).
- **R4** A `semgrep` step must be added to the `test` job in `ci.yml` (after the existing `ruff` lint step), using `semgrep --config=auto --error` to provide a fast, blocking SAST gate on every PR.
- **R5** `deploy.yml` must validate `inputs.image_tag` via an explicit env-var (not direct template expansion in the shell) against `^[a-z0-9._-]+$` in a validation step placed before the SSH action. The job must fail before any remote command is constructed if the tag is invalid.
- **R6** The SSH deploy step must pass `image_tag` to the remote script through an explicit `env:` variable (not `${{ inputs.image_tag }}` re-expansion inside the `script:` block).

## Architecture / Approach

### R1 — `ci.yml` permissions

Add a top-level `permissions:` block immediately after the `on:` trigger:

```yaml
permissions:
  contents: read
```

All four jobs (`test`, `frontend`, `migration-check`, `factory-tests`) are read-only: they checkout code, install deps, and run tests. None needs a write-capable token.

### R2–R3 — CodeQL workflow

Create `.github/workflows/codeql.yml` as a standalone workflow (not inline in `ci.yml`). CodeQL analysis is heavy enough (~5–10 min per language) that it belongs in its own workflow with its own permissions scope. The repo is public, so CodeQL runs free without a GHAS license — confirmed by the existing `upload-sarif` usage in `ci-publish.yml`.

```yaml
name: CodeQL

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read
  security-events: write

jobs:
  analyze:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        language: [python, javascript]
    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/init@v3
        with:
          languages: ${{ matrix.language }}
      - uses: github/codeql-action/autobuild@v3
      - uses: github/codeql-action/analyze@v3
```

The `javascript` language matrix covers the React/TypeScript frontend (CodeQL understands TypeScript natively under the `javascript` slug).

### R4 — Semgrep in `ci.yml`

Add a `semgrep` step to the `test` job (not as a separate job — co-locating with ruff gives fast, blocking feedback in the same job that already gates PRs). The step runs after the existing `Lint (ruff)` step:

```yaml
- name: SAST (semgrep)
  run: |
    pip install semgrep
    semgrep --config=auto --error backend/
```

`--error` causes semgrep to exit non-zero on any finding, making it a hard PR gate. The `auto` config pulls semgrep's curated Python ruleset. Scope is `backend/` only (Python); the frontend is covered by CodeQL's `javascript` matrix.

Bandit is not included — semgrep's Python security rulesets (`p/python` within `auto`) subsume bandit's checks with better configurability.

### R5–R6 — `deploy.yml` input validation

Add a `Validate image_tag` step before the `Deploy via SSH` step. The tag must be passed via `env:` — not interpolated inline via `${{ inputs.image_tag }}` inside the `run:` shell — so GitHub's template engine expands into an env var, not into the shell command string itself:

```yaml
- name: Validate image_tag
  env:
    IMAGE_TAG: ${{ inputs.image_tag }}
  run: |
    if ! [[ "$IMAGE_TAG" =~ ^[a-z0-9._-]+$ ]]; then
      echo "::error::image_tag '$IMAGE_TAG' contains invalid characters (allowed: a-z 0-9 . _ -)"
      exit 1
    fi
```

The SSH `Deploy via SSH` step's `script:` block currently uses `${{ inputs.image_tag }}` inline. Replace with a no-expansion form: set `export IMAGE_TAG` from the same `env:` variable, or pass it through the SSH action's `envs:` field:

```yaml
- name: Deploy via SSH
  uses: appleboy/ssh-action@v1
  env:
    IMAGE_TAG: ${{ inputs.image_tag }}
  with:
    host: ${{ secrets.DEPLOY_HOST }}
    username: ${{ secrets.DEPLOY_USER }}
    key: ${{ secrets.DEPLOY_SSH_KEY }}
    envs: IMAGE_TAG
    script: |
      set -e
      # IMAGE_TAG is passed via envs:, not via ${{ }} expansion
      docker compose pull backend celery-worker ...
```

The `envs:` field of `appleboy/ssh-action` forwards named env vars to the remote shell without shell-quoting issues.

## Alternatives Considered

### SAST: Semgrep only (no CodeQL)
Semgrep OSS with `--config=auto` would cover the PR gate without a separate workflow. Rejected: CodeQL provides deeper dataflow analysis (taint tracking, interprocedural queries) that rule-based tools miss. Since the repo is public and CodeQL is free, the cost is only CI time (~10 min), not license overhead.

### SAST: CodeQL only (no Semgrep)
CodeQL in a standalone workflow is not a PR-blocking gate unless configured as a required status check in branch protection. Adding Semgrep to `ci.yml` gives an immediate, unconditional blocking gate without relying on branch protection settings.

### deploy.yml: validate inside SSH script
Checking the regex inside the `script:` block is structurally too late — `${{ inputs.image_tag }}` is expanded by GitHub's template engine before the SSH action fires, so the injection payload is already baked into the remote command string. A pre-SSH validation step aborts the job before any remote execution.

### ci.yml permissions: per-job scope
Fine-grained per-job permissions would be more precise, but all four existing jobs are uniformly read-only, making a single workflow-level `permissions: contents: read` equivalent and simpler.

## Open Questions

- **CodeQL as required status check**: Adding `codeql.yml` does not automatically block PRs — branch protection must list "CodeQL / Analyze (python)" and "CodeQL / Analyze (javascript)" as required checks. This is a GitHub settings change, not a file change, and is out of scope for this implementation. Tracking in issue #378 as a manual follow-up.
- **Semgrep finding count**: `--config=auto` may surface existing findings in the current codebase on first run. The implementation step should run semgrep locally first and add targeted `# nosemgrep` suppressions for any false positives before enabling as a gate.

## Assumptions

- The repo is public (`gh repo view --json visibility` → `PUBLIC`), so CodeQL runs free without GHAS.
- `appleboy/ssh-action@v1` supports the `envs:` field for passing env vars to the remote shell. Confirmed in `appleboy/ssh-action` v1 documentation.
- `semgrep --config=auto` resolves correctly in GitHub Actions without a Semgrep account token (OSS usage, not SaaS).
- The existing `ci.yml` PR-gating jobs do not write to the repo or packages, making `contents: read` a safe least-privilege floor.
