# Container Registry and CI/CD Deployment Pipeline Design

**Date**: 2026-05-28
**Status**: Draft
**Issue**: #104 — Set up container registry and CI/CD deployment pipeline
**Scope**: GitHub Container Registry (GHCR) setup, automated image builds, security scanning, and a scaffolded deployment workflow.

---

## Overview

MarketHawk currently builds Docker images locally on every `docker-compose up --build`. There is no container registry, no image versioning, and no automated deployment pipeline. Deployments are manual and not reproducible — the same commit can produce different images depending on when `pip install` and `npm install` run.

This spec covers:
1. Publishing versioned images to GitHub Container Registry (GHCR)
2. A new CI workflow that builds and pushes images on every merge to `main`
3. Trivy security scanning (informational, non-blocking)
4. A `workflow_dispatch`-triggered deployment workflow with placeholders for server credentials
5. Updating `docker-compose.yml` to support both local builds and registry pulls
6. A documented rollback procedure

---

## Requirements

- R1: Three images published to GHCR: `markethawk-backend`, `markethawk-frontend`, `markethawk-dark-factory`
- R2: Each image tagged with the short git SHA (`sha-{SHA}`) and `latest` on every push to `main`
- R3: All backend-derived services (celery-worker, celery-beat, live-scanner, flower) reference the same `markethawk-backend` image
- R4: `docker-compose.yml` updated to include both `image:` (registry pull) and `build:` (local override) for all built services
- R5: Trivy scans all three published images; results uploaded to GitHub Security tab as SARIF; build succeeds regardless of findings
- R6: A `workflow_dispatch` deployment workflow that SSH-deploys to a configured server: pull images, run migrations, restart services
- R7: Deployment workflow parameterized by image tag (default: `latest`) so operators can pin to a specific SHA
- R8: Rollback documented as pulling a specific SHA tag
- R9: tweet-monitor and forecast-worker excluded from this issue (separate Dockerfiles, separate cadence)

---

## Architecture

### New GitHub Actions Workflows

#### `ci-publish.yml` — Build and push on merge to main

Trigger: `push` to `main`

```
jobs:
  build-backend    → builds ./backend/Dockerfile
                   → pushes ghcr.io/omniscient/markethawk-backend:sha-{SHA} + :latest

  build-frontend   → builds ./frontend/Dockerfile
                   → pushes ghcr.io/omniscient/markethawk-frontend:sha-{SHA} + :latest

  build-dark-factory → builds dark-factory/Dockerfile (build context: .)
                     → pushes ghcr.io/omniscient/markethawk-dark-factory:sha-{SHA} + :latest

  scan             → runs trivy on all three images (after push)
  (needs: build-*) → uploads SARIF to GitHub Security tab
                   → continues-on-error: true (non-blocking)
```

All three build jobs run in parallel. GHCR login uses `GITHUB_TOKEN` (no additional secrets needed for same-repo pushes).

Image naming follows the existing repo org: `ghcr.io/omniscient/markethawk-{service}`.

#### `deploy.yml` — Manual deployment workflow

Trigger: `workflow_dispatch`

Inputs:
- `image_tag` (string, default: `latest`) — the tag to deploy
- `run_migrations` (boolean, default: `true`) — whether to run `alembic upgrade head`

Steps:
1. SSH to deployment server (via `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` environment secrets)
2. `docker compose pull` — pulls all images with the specified tag
3. `docker compose up -d --no-deps backend frontend celery-worker celery-beat live-scanner` — rolling restart of app services
4. (if run_migrations) `docker compose exec -T backend python -m alembic upgrade head`
5. Health check: `curl -f http://localhost:8000/health`

Deployment target uses a GitHub Environment named `production` to gate the workflow on required reviewers (optional, configured by the operator after server provisioning).

**Note:** `DEPLOY_HOST`, `DEPLOY_USER`, and `DEPLOY_SSH_KEY` are placeholder secrets. The workflow will be scaffolded but non-functional until a server is provisioned and these secrets are configured in GitHub Settings → Environments.

### Updated `docker-compose.yml`

Services that currently use `build:` only are updated to include an `image:` reference. When both fields are present, Docker Compose uses the named image if available locally (or after `docker compose pull`), and falls back to building if the image is absent. `docker compose up --build` always rebuilds.

Affected services and their image names:

| Service | Image |
|---------|-------|
| backend | `ghcr.io/omniscient/markethawk-backend:latest` |
| celery-worker | `ghcr.io/omniscient/markethawk-backend:latest` |
| celery-beat | `ghcr.io/omniscient/markethawk-backend:latest` |
| live-scanner | `ghcr.io/omniscient/markethawk-backend:latest` |
| flower | `ghcr.io/omniscient/markethawk-backend:latest` |
| frontend | `ghcr.io/omniscient/markethawk-frontend:latest` |
| dark-factory | `ghcr.io/omniscient/markethawk-dark-factory:latest` |
| backlog-scheduler | `ghcr.io/omniscient/markethawk-dark-factory:latest` |

### Frontend VITE_API_TARGET

`VITE_API_TARGET=http://backend:8000` is baked into the frontend image at build time. This is correct for all Docker Compose deployments — the frontend container always communicates with the backend container over the `stockscanner-network` Docker bridge, where `backend` resolves as the container name. No changes to the frontend code or Dockerfile are needed.

### Rollback Procedure

To roll back to a previous version:

```bash
# Edit docker-compose.yml to pin the image tag, e.g.:
# image: ghcr.io/omniscient/markethawk-backend:sha-abc1234

docker compose pull
docker compose up -d --no-deps backend celery-worker celery-beat live-scanner

# If the rollback includes a schema change, downgrade the migration:
docker compose exec -T backend python -m alembic downgrade -1
```

SHA tags are permanent — `latest` moves forward but SHA tags never change.

---

## Alternatives Considered

### Alt 1: Extend the existing `ci.yml` with publish jobs

Add build-and-push steps to the existing test workflow. Simpler (one file), but creates an awkward conditional — tests run on PR, image push should only run on merge to `main`. This leads to `if: github.ref == 'refs/heads/main'` guards throughout the existing file, reducing readability.

**Rejected**: A dedicated `ci-publish.yml` is cleaner — test workflow stays test-only.

### Alt 2: Tag-based deployment trigger (`v1.2.3` git tag)

Pushing a semver tag triggers deployment. Conventional for traditional releases but requires tagging discipline and complicates the workflow (needs to detect the target environment from the tag format). Also requires the deployment server to be provisioned before this can be validated.

**Rejected**: `workflow_dispatch` is simpler, safer, and equally functional for a single-server deployment. Tag-based can be added as a follow-up.

### Alt 3: Hard-fail on Trivy CRITICAL/HIGH CVEs

Block pushes when trivy finds high-severity vulnerabilities. Enforces a secure baseline but will immediately block deploys on the first run — both backend (Python + scikit-learn + LightGBM) and frontend (Node 22 + 30+ npm packages) have deep dependency trees with likely transitive CVEs. The team has already addressed a round of CVEs (commit `9e9da92`).

**Rejected**: Informational-only scanning gives security visibility without blocking every release until transitive dependencies are patched by upstream vendors.

---

## Open Questions

- OQ1: Will a production server be provisioned before this issue is fully closed? The `deploy.yml` workflow can be merged as a non-functional scaffold and activated when secrets are set.
- OQ2: Should GHCR packages be public or private? Public packages are accessible without authentication (fine for open-source); private packages require `docker login ghcr.io` on the deployment server. This is a GitHub repository visibility decision, not a code change.
- OQ3: `forecast-worker` and `tweet-monitor` are excluded from this issue. Should they be tracked as a follow-up?

---

## Assumptions

- **A1**: The GitHub repository (`omniscient/markethawk`) has GitHub Actions enabled and the default `GITHUB_TOKEN` has `packages: write` permission (standard for GHCR publishing). If not, the `ci-publish.yml` workflow needs `permissions: packages: write` added to the job.
- **A2**: The deployment server runs Docker Compose v2 (`docker compose`, not `docker-compose`). If Compose v1 is in use, the deploy script uses `docker-compose` instead.
- **A3**: The existing Dockerfiles are dev-mode images (backend runs with `--reload`; frontend runs `npm run dev`). This spec publishes them as-is. Production-hardened multi-stage Dockerfiles are out of scope.
- **A4**: `dark-factory/Dockerfile` uses the full repo as its build context. The CI job must `actions/checkout@v4` before building, and the build context path in the workflow is `.` (repo root).
