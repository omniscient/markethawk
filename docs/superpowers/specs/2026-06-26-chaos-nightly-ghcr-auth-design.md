# chaos-nightly: GHCR auth fix for hosted CI

**Status:** design
**Date:** 2026-06-26
**Issue:** #606

## Problem

`.github/workflows/chaos-nightly.yml`'s `chaos-mock` job runs
`bash scripts/chaos/ibkr_kill_test.sh --mock`, which calls
`docker compose up -d postgres redis backend live-scanner`. These services all use the
private image `ghcr.io/omniscient/markethawk-backend:latest`. GitHub-hosted runners have
no GHCR credentials, so `docker compose up` fails with a 401 on the manifest fetch before
any test logic runs.

The nightly `schedule:` trigger was therefore commented out to stop the noise. The
`workflow_dispatch` trigger was retained so the harness can still be run manually or
locally.

The same root-cause affects `chaos-live`: its code path also calls
`docker compose up -d ... backend live-scanner`, so both jobs need the same fix.

## Requirements

1. Both `chaos-mock` and `chaos-live` jobs must be able to pull `ghcr.io/omniscient/markethawk-backend:latest` on a GitHub-hosted runner without any new repository secrets.
2. The fix must not require building images from source in CI (build time, cache complexity, and drift from the production artifact are not acceptable).
3. The `schedule:` trigger must remain commented out after this PR. It is re-enabled manually in a follow-up commit once a green `workflow_dispatch` run on the merged branch confirms the full harness passes on a hosted runner.
4. The inline workflow comment must explain the manual validation gate and what to do to re-enable the cron.

## Approach

Use `docker/login-action@v4` with `secrets.GITHUB_TOKEN` and `permissions: packages: read`
on each affected job — the same pattern `ci-publish.yml` already uses for `packages: write`.

`GITHUB_TOKEN` automatically gets `read:packages` scope for packages owned by the same
organisation (`ghcr.io/omniscient/...`) without any manual secret configuration.

### Changes to `.github/workflows/chaos-nightly.yml`

**Add `permissions:` block to `chaos-mock` job:**

```yaml
chaos-mock:
  name: Chaos test (mock mode)
  runs-on: ubuntu-latest
  permissions:
    contents: read
    packages: read
```

**Add GHCR login step before the chaos test step in `chaos-mock`:**

```yaml
      - name: Log in to GHCR
        uses: docker/login-action@650006c6eb7dba73a995cc03b0b2d7f5ac915bee # v4.2.0
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
```

Apply identical `permissions:` and login step to `chaos-live`.

**Update the paused-schedule comment** to reflect the new validation requirement:

```yaml
  # NOTE: the nightly `schedule:` trigger is intentionally PAUSED.
  # The chaos-mock and chaos-live jobs require GHCR auth to pull
  # ghcr.io/omniscient/markethawk-backend:latest. GHCR login via GITHUB_TOKEN
  # (packages:read) has been added to both jobs.
  # Re-enable the cron ONLY after a manual workflow_dispatch run on main confirms
  # the full harness (backend /api/ready, watchlist seed, mock assertions) is green
  # on a hosted runner:
  #   gh workflow run chaos-nightly.yml --ref main
  # Then uncomment the lines below and commit.
  # schedule:
  #   - cron: '0 3 * * 1-5'  # 03:00 UTC, weekdays only
```

### Pin consistency

`ci-publish.yml` already pins `docker/login-action` to commit hash
`650006c6eb7dba73a995cc03b0b2d7f5ac915bee` (v4.2.0). Use the **same** hash in
`chaos-nightly.yml` to keep action pins consistent across the repo. If the hash differs
from the published `ci-publish.yml` reference, verify against
`https://github.com/docker/login-action/releases`.

## Alternatives considered

**docker compose build in-job** — build backend/live-scanner from source before `up`.
Eliminates the pull auth concern entirely. Rejected: adds ~5-10 minutes of CI time per
nightly run, requires layer caching strategy, and exercises a freshly-built image instead
of the production artefact that shipped to GHCR. The chaos test should hit the same image
the rest of the system runs.

**Self-hosted runner with GHCR auth** — pre-authenticate a runner. Rejected: operational
overhead, runner maintenance, and not needed when `GITHUB_TOKEN` already provides the
required `read:packages` scope on hosted runners.

**Keep dispatch-only permanently** — document the harness as manual-only. Rejected: the
issue acceptance criterion is that nightly runs are green or the workflow is intentionally
dispatch-only. Intentionally dispatch-only is acceptable only as a documented interim state
(which the current commented-out schedule already covers), not as a permanent resolution
when a clean in-job fix exists.

## Open questions (non-blocking)

- **Cron re-enable PR**: once a green manual dispatch is confirmed, this is a one-line
  change (uncomment `schedule:`). It can be a direct push to main (no issue needed) or
  a follow-up micro-PR — implementer's choice.
- **`chaos-live` smoke**: the live job already guards on `IB_USERNAME` and skips cleanly
  when secrets are absent. The GHCR login step is safe to add unconditionally (it doesn't
  fail if the job would otherwise skip the live chaos run).

## Assumptions

- `ghcr.io/omniscient/markethawk-backend:latest` is a package owned by the `omniscient`
  organisation on the same GitHub account as the `omniscient/markethawk` repo. If the
  package is under a different org, `GITHUB_TOKEN` will not have `read:packages` and a
  separate PAT will be needed.
- The chaos harness itself (`ibkr_kill_test.sh --mock`) passes once the backend is
  reachable — the only current blocker is the 401 on image pull. No changes to the script
  are in scope.

## Validation

- Manually dispatch `chaos-nightly.yml` on the fix branch via
  `gh workflow run chaos-nightly.yml --ref <branch>` and confirm `chaos-mock` passes
  (backend reaches `/api/ready` within 120s, mock assertions green).
- Verify no new repository secrets are required (GITHUB_TOKEN only).
- After merge to main, run `gh workflow run chaos-nightly.yml --ref main` as the
  acceptance validation. If green, uncomment `schedule:` and commit.
