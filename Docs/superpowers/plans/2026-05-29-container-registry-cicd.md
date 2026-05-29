# Container Registry and CI/CD Deployment Pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish backend, frontend, and dark-factory Docker images to GitHub Container Registry (GHCR) on every merge to `main`, add a manual `workflow_dispatch` deployment workflow, update `docker-compose.yml` to support both local builds and registry pulls, and document the rollback procedure.

**Architecture:** Two new GitHub Actions workflows — `ci-publish.yml` (parallel image builds + Trivy security scanning on push to `main`) and `deploy.yml` (SSH-based deployment via manual trigger). `docker-compose.yml` updated with `image:` fields on all eight built services, preserving `build:` for local development. Existing `ci.yml` test workflow is left unchanged.

**Tech Stack:** GitHub Actions, GHCR (`docker/login-action@v3`, `docker/build-push-action@v6`, `docker/metadata-action@v5`), Trivy (`aquasecurity/trivy-action`), SSH (`appleboy/ssh-action`), Docker Compose v2

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `.github/workflows/ci-publish.yml` | Create | Build and push backend/frontend/dark-factory images to GHCR; run Trivy scan on all three |
| `.github/workflows/deploy.yml` | Create | `workflow_dispatch` SSH deployment with `image_tag` input and `run_migrations` toggle |
| `docker-compose.yml` | Modify | Add `image:` field to 8 built services for dual local-build/registry-pull mode |
| `deployment-guide.md` | Modify | Add rollback procedure section (SHA tag pinning) |

---

## Task 1: Create `ci-publish.yml` — GHCR build and publish workflow

**Files:**
- Create: `.github/workflows/ci-publish.yml`

Covers R1 (three images), R2 (sha + latest tags), R5 (Trivy non-blocking scan with SARIF upload).

- [ ] **Step 1: Verify the file is absent**

```bash
ls .github/workflows/ci-publish.yml 2>&1 | grep "No such file" && echo "PASS: file absent"
```

Expected: `PASS: file absent`

- [ ] **Step 2: Create `.github/workflows/ci-publish.yml`**

```yaml
name: Build and Publish Images

on:
  push:
    branches: [main]

permissions:
  contents: read
  packages: write
  security-events: write

jobs:
  build-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Generate image metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/omniscient/markethawk-backend
          tags: |
            type=sha,prefix=sha-,format=short
            type=raw,value=latest

      - name: Build and push backend image
        uses: docker/build-push-action@v6
        with:
          context: ./backend
          file: ./backend/Dockerfile
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}

  build-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Generate image metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/omniscient/markethawk-frontend
          tags: |
            type=sha,prefix=sha-,format=short
            type=raw,value=latest

      - name: Build and push frontend image
        uses: docker/build-push-action@v6
        with:
          context: ./frontend
          file: ./frontend/Dockerfile
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}

  build-dark-factory:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Generate image metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/omniscient/markethawk-dark-factory
          tags: |
            type=sha,prefix=sha-,format=short
            type=raw,value=latest

      - name: Build and push dark-factory image
        uses: docker/build-push-action@v6
        with:
          context: .
          file: ./dark-factory/Dockerfile
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}

  scan:
    runs-on: ubuntu-latest
    needs: [build-backend, build-frontend, build-dark-factory]
    continue-on-error: true
    strategy:
      matrix:
        include:
          - image: ghcr.io/omniscient/markethawk-backend
            sarif: backend-trivy.sarif
          - image: ghcr.io/omniscient/markethawk-frontend
            sarif: frontend-trivy.sarif
          - image: ghcr.io/omniscient/markethawk-dark-factory
            sarif: dark-factory-trivy.sarif
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Scan ${{ matrix.image }} with Trivy
        uses: aquasecurity/trivy-action@0.28.0
        with:
          image-ref: ${{ matrix.image }}:latest
          format: sarif
          output: ${{ matrix.sarif }}
          exit-code: "0"

      - name: Upload Trivy SARIF for ${{ matrix.image }}
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: ${{ matrix.sarif }}
          category: trivy-${{ matrix.image }}
```

- [ ] **Step 3: Validate YAML and verify spec requirements R1, R2, R5**

```bash
python3 -c "
import yaml
with open('.github/workflows/ci-publish.yml') as f:
    content = f.read()
doc = yaml.safe_load(content)

# Structure
assert 'jobs' in doc, 'no jobs key'
for job in ['build-backend', 'build-frontend', 'build-dark-factory', 'scan']:
    assert job in doc['jobs'], f'missing job: {job}'

# R1: three images
assert 'markethawk-backend' in content
assert 'markethawk-frontend' in content
assert 'markethawk-dark-factory' in content

# R2: sha + latest tags
assert 'type=sha,prefix=sha-,format=short' in content
assert 'type=raw,value=latest' in content

# R5: non-blocking scan with SARIF
assert 'continue-on-error: true' in content
assert 'exit-code: \"0\"' in content
assert 'upload-sarif' in content

print('PASS: YAML valid, R1 / R2 / R5 satisfied')
"
```

Expected: `PASS: YAML valid, R1 / R2 / R5 satisfied`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci-publish.yml
git commit -m "ci: add GHCR build and publish workflow for backend, frontend, dark-factory"
```

---

## Task 2: Create `deploy.yml` — manual deployment workflow

**Files:**
- Create: `.github/workflows/deploy.yml`

Covers R6 (`workflow_dispatch` SSH deploy), R7 (`image_tag` parameter, default `latest`). Scaffolded — non-functional until `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` secrets are configured in GitHub Settings → Environments → `production`.

- [ ] **Step 1: Verify the file is absent**

```bash
ls .github/workflows/deploy.yml 2>&1 | grep "No such file" && echo "PASS: file absent"
```

Expected: `PASS: file absent`

- [ ] **Step 2: Create `.github/workflows/deploy.yml`**

```yaml
name: Deploy to Production

on:
  workflow_dispatch:
    inputs:
      image_tag:
        description: "Image tag to deploy (e.g. latest or sha-abc1234)"
        required: true
        default: latest
        type: string
      run_migrations:
        description: "Run alembic upgrade head after pulling images"
        required: true
        default: "true"
        type: boolean

permissions:
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    steps:
      - name: Deploy ${{ github.event.inputs.image_tag }} to production
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key: ${{ secrets.DEPLOY_SSH_KEY }}
          script: |
            set -e
            cd /opt/markethawk

            # docker-compose.yml uses ${IMAGE_TAG:-latest} in all image fields.
            # Exporting IMAGE_TAG causes docker compose to substitute it at runtime.
            export IMAGE_TAG="${{ github.event.inputs.image_tag }}"

            # Pull updated images (docker compose reads IMAGE_TAG from the environment).
            # dark-factory and backlog-scheduler share the dark-factory image but are
            # profile-gated — pull updates the cached image; they are started separately.
            docker compose pull backend frontend \
              celery-worker celery-beat live-scanner flower backlog-scheduler

            # Rolling restart of all continuously-running app services
            docker compose up -d --no-deps \
              backend frontend celery-worker celery-beat live-scanner flower backlog-scheduler

            # Run migrations if requested
            if [ "${{ github.event.inputs.run_migrations }}" = "true" ]; then
              docker compose exec -T backend python -m alembic upgrade head
            fi

            # Health check
            curl -f http://localhost:8000/api/health
```

- [ ] **Step 3: Validate YAML and verify spec requirements R6, R7**

```bash
python3 -c "
import yaml
with open('.github/workflows/deploy.yml') as f:
    content = f.read()
doc = yaml.safe_load(content)

# R6: workflow_dispatch trigger
assert 'workflow_dispatch' in doc['on'], 'missing workflow_dispatch trigger'

# R7: image_tag input with default 'latest'
inputs = doc['on']['workflow_dispatch']['inputs']
assert 'image_tag' in inputs, 'missing image_tag input'
assert inputs['image_tag']['default'] == 'latest', 'image_tag default is not latest'
assert 'run_migrations' in inputs, 'missing run_migrations input'

# R6: deploy job with SSH action
assert 'deploy' in doc['jobs']
steps = doc['jobs']['deploy']['steps']
assert any('appleboy/ssh-action' in str(s) for s in steps), 'missing ssh-action step'

# Secrets referenced
assert 'DEPLOY_HOST' in content
assert 'DEPLOY_USER' in content
assert 'DEPLOY_SSH_KEY' in content

print('PASS: YAML valid, R6 / R7 satisfied')
"
```

Expected: `PASS: YAML valid, R6 / R7 satisfied`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add workflow_dispatch deployment workflow (scaffolded — requires DEPLOY_HOST/USER/SSH_KEY secrets)"
```

---

## Task 3: Update `docker-compose.yml` — dual build/pull mode

**Files:**
- Modify: `docker-compose.yml`

Covers R3 (all five backend-derived services share `markethawk-backend`), R4 (both `image:` and `build:` present on all 8 services so local builds and registry pulls both work), R7 (image tag parameterized via `${IMAGE_TAG:-latest}` so `deploy.yml` can pin a SHA without mutating the compose file), R9 (`tweet-monitor` and `forecast-worker` are not touched).

**Why `${IMAGE_TAG:-latest}`:** Docker Compose substitutes env vars from the shell environment. When `IMAGE_TAG` is unset (local development), Docker Compose falls back to `latest`. When the deployment workflow exports `IMAGE_TAG=sha-abc1234`, all pulled images use that exact SHA. This avoids fragile `sed` patching of the compose file on the server.

- [ ] **Step 1: Run the validation script — must fail now (services have no `image:` field)**

```bash
python3 -c "
import yaml
with open('docker-compose.yml') as f:
    config = yaml.safe_load(f)
services = config['services']
missing = [s for s in ['backend','celery-worker','celery-beat','live-scanner','flower','frontend','dark-factory','backlog-scheduler']
           if 'image' not in services.get(s, {})]
print(f'Services missing image: field: {missing}')
assert len(missing) == 0, 'EXPECTED FAILURE — proceed to add image: fields'
"
```

Expected: `Services missing image: field: ['backend', 'celery-worker', ...]` (this is the red state)

- [ ] **Step 2: Add `image:` to the `backend` service**

In `docker-compose.yml`, locate the `backend:` service block and add `image:` as the first field:

```yaml
  backend:
    image: ghcr.io/omniscient/markethawk-backend:${IMAGE_TAG:-latest}
    build:
      context: ./backend
      dockerfile: Dockerfile
```

- [ ] **Step 3: Add `image:` to the `celery-worker` service**

```yaml
  celery-worker:
    image: ghcr.io/omniscient/markethawk-backend:${IMAGE_TAG:-latest}
    build:
      context: ./backend
      dockerfile: Dockerfile
```

- [ ] **Step 4: Add `image:` to the `celery-beat` service**

```yaml
  celery-beat:
    image: ghcr.io/omniscient/markethawk-backend:${IMAGE_TAG:-latest}
    build:
      context: ./backend
      dockerfile: Dockerfile
```

- [ ] **Step 5: Add `image:` to the `live-scanner` service**

```yaml
  live-scanner:
    image: ghcr.io/omniscient/markethawk-backend:${IMAGE_TAG:-latest}
    build:
      context: ./backend
      dockerfile: Dockerfile
```

- [ ] **Step 6: Add `image:` to the `flower` service**

```yaml
  flower:
    image: ghcr.io/omniscient/markethawk-backend:${IMAGE_TAG:-latest}
    build:
      context: ./backend
      dockerfile: Dockerfile
```

- [ ] **Step 7: Add `image:` to the `frontend` service**

```yaml
  frontend:
    image: ghcr.io/omniscient/markethawk-frontend:${IMAGE_TAG:-latest}
    build:
      context: ./frontend
      dockerfile: Dockerfile
```

- [ ] **Step 8: Add `image:` to the `dark-factory` service**

```yaml
  dark-factory:
    image: ghcr.io/omniscient/markethawk-dark-factory:${IMAGE_TAG:-latest}
    build:
      context: .
      dockerfile: dark-factory/Dockerfile
```

- [ ] **Step 9: Add `image:` to the `backlog-scheduler` service**

```yaml
  backlog-scheduler:
    image: ghcr.io/omniscient/markethawk-dark-factory:${IMAGE_TAG:-latest}
    build:
      context: .
      dockerfile: dark-factory/Dockerfile
```

- [ ] **Step 10: Run the validation script — must pass now**

```bash
python3 -c "
import yaml
with open('docker-compose.yml') as f:
    config = yaml.safe_load(f)
services = config['services']

# R3: all backend-derived services use the same backend image (env-var tag)
backend_image = 'ghcr.io/omniscient/markethawk-backend:\${IMAGE_TAG:-latest}'
for s in ['backend', 'celery-worker', 'celery-beat', 'live-scanner', 'flower']:
    assert services[s].get('image') == backend_image, f'{s}: wrong image {services[s].get(\"image\")}'

# R4: frontend and factory images correct
assert services['frontend']['image'] == 'ghcr.io/omniscient/markethawk-frontend:\${IMAGE_TAG:-latest}'
assert services['dark-factory']['image'] == 'ghcr.io/omniscient/markethawk-dark-factory:\${IMAGE_TAG:-latest}'
assert services['backlog-scheduler']['image'] == 'ghcr.io/omniscient/markethawk-dark-factory:\${IMAGE_TAG:-latest}'

# R4: build: still present (dual mode)
for s in ['backend','celery-worker','celery-beat','live-scanner','flower','frontend','dark-factory','backlog-scheduler']:
    assert 'build' in services[s], f'{s} lost its build: field'

# R9: tweet-monitor and forecast-worker unchanged (no image: field added)
assert 'image' not in services.get('tweet-monitor', {}), 'tweet-monitor should not have image:'
assert 'image' not in services.get('forecast-worker', {}), 'forecast-worker should not have image:'

print('PASS: R3, R4, R7 (env-var tag), R9 satisfied')
"
```

Expected: `PASS: R3, R4, R7 (env-var tag), R9 satisfied`

- [ ] **Step 11: Validate the full compose file is parseable**

```bash
docker compose config --quiet 2>&1 | head -5
echo "exit: $?"
```

Expected: exit code 0 (no output or warnings only)

- [ ] **Step 12: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(docker): add GHCR image references to all built services for dual build/pull mode"
```

---

## Task 4: Document rollback procedure in `deployment-guide.md`

**Files:**
- Modify: `deployment-guide.md`

Covers R8: operators can pin any `sha-{SHA}` tag to roll back to an exact prior build.

- [ ] **Step 1: Confirm the rollback section does not yet exist**

```bash
grep -in "rollback" deployment-guide.md | head -5 && echo "(found above)" || echo "PASS: no rollback section yet"
```

Expected: `PASS: no rollback section yet`

- [ ] **Step 2: Append the rollback section to `deployment-guide.md`**

Add the following at the end of the file (after the "Logs and Monitoring" section):

```markdown

---

## Rollback Procedure

Each image pushed to GHCR is tagged with both `latest` (moves forward on every merge to `main`) and `sha-{GIT_SHA}` (permanent — never changes). To roll back to any prior build:

### 1. Identify the target SHA tag

Browse [GitHub Packages](https://github.com/orgs/omniscient/packages) or find the SHA in the Actions run history for the `Build and Publish Images` workflow (e.g. `sha-abc1234`).

### 2. Set `IMAGE_TAG` and pull

The image fields in `docker-compose.yml` use `${IMAGE_TAG:-latest}`. Export the target SHA tag before running docker compose:

```bash
export IMAGE_TAG=sha-abc1234
docker compose pull backend frontend celery-worker celery-beat live-scanner flower
docker compose up -d --no-deps backend celery-worker celery-beat live-scanner flower
```

### 4. Handle schema rollbacks (if the rollback crosses a migration boundary)

Before pulling the older image, downgrade the database schema:

```bash
docker compose exec -T backend python -m alembic downgrade -1
```

Check `alembic/versions/` to identify how many steps back to go; run `downgrade -1` for each.

> **Tip:** SHA tags are immutable — `latest` may point to a broken image, but any `sha-` tag is guaranteed to be the exact image from that CI run.
```

- [ ] **Step 3: Verify the section was added**

```bash
grep -n "Rollback Procedure" deployment-guide.md && echo "PASS: rollback section present"
```

Expected: line number output + `PASS: rollback section present`

- [ ] **Step 4: Commit**

```bash
git add deployment-guide.md
git commit -m "docs: add rollback procedure for GHCR image tags to deployment-guide.md"
```

---

## Requirements Coverage

| Req | Description | Covered by |
|-----|-------------|-----------|
| R1 | Three images published to GHCR | Task 1 — `build-backend`, `build-frontend`, `build-dark-factory` jobs |
| R2 | `sha-{SHA}` + `latest` tags on every push to `main` | Task 1 — `docker/metadata-action` with `type=sha` and `type=raw,value=latest` |
| R3 | All backend-derived services share `markethawk-backend` image | Task 3 — backend, celery-worker, celery-beat, live-scanner, flower |
| R4 | `docker-compose.yml` has both `image:` and `build:` on all built services | Task 3 — dual-mode update |
| R5 | Trivy scans three images; SARIF to GitHub Security; non-blocking | Task 1 — `scan` job with `continue-on-error: true` and `exit-code: "0"` |
| R6 | `workflow_dispatch` deployment workflow with SSH | Task 2 — `deploy.yml` |
| R7 | `image_tag` input, default `latest` | Task 2 — `workflow_dispatch.inputs.image_tag` |
| R8 | Rollback documented | Task 4 — rollback section in `deployment-guide.md` |
| R9 | `tweet-monitor` and `forecast-worker` excluded | Task 3 — only 8 services modified, both excluded |
