# Plan: Pin Floating :latest Tags + Unpinned Base Images/Actions (F-SUPPLY-01)

**Date:** 2026-06-15
**Issue:** #374
**Epic:** #372 (Defensive Security Review 2026-06-12)
**Spec:** docs/superpowers/specs/2026-06-13-pin-floating-tags-supply-chain-design.md
**Branch:** `feat/issue-374-*`

---

## Goal

Resolve F-SUPPLY-01 by pinning all supply-chain entry points: (1) four docker-compose `:latest` image tags, (2) eight Dockerfile `FROM` lines converted to `image:tag@sha256:<digest>` format, (3) all ten GitHub Actions `uses:` references pinned to 40-character commit SHAs, and (4) a Dependabot config for weekly automated bump PRs. No runtime behaviour changes.

---

## Architecture

This is a pure configuration change. No application code, no database migrations, no new services. All changes are in:
- `docker-compose.yml` (compose image tags)
- 8 Dockerfiles (base image digests)
- 3 workflow files (action SHA pins)
- 1 new file: `.github/dependabot.yml`

The dark-factory rebuilds images on every run, so digest pins are live constraints immediately after merge.

---

## Tech Stack

- Docker / Docker Compose
- GitHub Actions
- `docker inspect` (digest lookup)
- `gh` CLI (action SHA lookup)

---

## File Structure

| File | Change |
|------|--------|
| `docker-compose.yml` | Pin 4 `:latest` compose images to explicit version tags |
| `backend/Dockerfile` | Add `@sha256:` digest to `FROM python:3.12-slim` |
| `backend/Dockerfile.forecast` | Add `@sha256:` digest to `FROM python:3.12-slim` |
| `dark-factory/Dockerfile` | Add `@sha256:` digest to `FROM ubuntu:24.04` |
| `docker/Dockerfile.backup` | Add `@sha256:` digest to `FROM alpine:3.19` |
| `frontend/Dockerfile` | Add `@sha256:` digest to `FROM node:22-alpine` |
| `grafana/Dockerfile` | Add `@sha256:` digest to `FROM grafana/grafana:11.1.0` |
| `monitoring/prometheus/Dockerfile` | Add `@sha256:` digest to `FROM prom/prometheus:v2.53.0` |
| `services/tweet-monitor/Dockerfile` | Add `@sha256:` digest to `FROM python:3.11-slim` |
| `.github/workflows/ci.yml` | Pin 7 `uses:` references to 40-char commit SHAs |
| `.github/workflows/ci-publish.yml` | Pin 17 `uses:` references to 40-char commit SHAs |
| `.github/workflows/deploy.yml` | Pin 1 `uses:` reference to 40-char commit SHA |
| `.github/dependabot.yml` | New file — weekly docker + github-actions update PRs |

---

## Tasks

### Task 1: Pin docker-compose `:latest` image tags

**Files:** `docker-compose.yml`

**Step 1 — Verify failing state**

```bash
grep -n ":latest" /workspace/markethawk/docker-compose.yml
```

Expected output (4 hits):
```
359:    image: dpage/pgadmin4:latest
381:    image: datalust/seq:latest
400:    image: datalust/seq-input-gelf:latest
455:    image: tecnativa/docker-socket-proxy:latest
```

**Step 2 — Look up current stable version tags**

Pull each image to confirm the latest stable tag available on Docker Hub, then record the version:

```bash
# Check Docker Hub for current stable tags — do NOT use :latest
# pgadmin4 stable: https://hub.docker.com/r/dpage/pgadmin4/tags
# seq stable: https://hub.docker.com/r/datalust/seq/tags
# seq-input-gelf: https://hub.docker.com/r/datalust/seq-input-gelf/tags (must match seq major.minor)
# docker-socket-proxy stable: https://hub.docker.com/r/tecnativa/docker-socket-proxy/tags

# Confirm versions can be pulled:
docker pull dpage/pgadmin4:<VERSION>
docker pull datalust/seq:<VERSION>
docker pull datalust/seq-input-gelf:<VERSION>
docker pull tecnativa/docker-socket-proxy:<VERSION>
```

**Step 3 — Update docker-compose.yml**

In `docker-compose.yml`, replace the four `:latest` references with the explicit versions found above:

```yaml
# Line ~359 — pgadmin4
    image: dpage/pgadmin4:<VERSION>   # was :latest

# Line ~381 — seq
    image: datalust/seq:<VERSION>     # was :latest

# Line ~400 — seq-input-gelf (must match seq major version)
    image: datalust/seq-input-gelf:<VERSION>   # was :latest

# Line ~455 — docker-socket-proxy
    image: tecnativa/docker-socket-proxy:<VERSION>   # was :latest
```

**Step 4 — Verify passing state**

```bash
grep -n ":latest" /workspace/markethawk/docker-compose.yml
```

Expected: no output (zero hits).

Also confirm none of the four images appear without a version:
```bash
grep -E "(pgadmin4|datalust/seq|seq-input-gelf|docker-socket-proxy):" /workspace/markethawk/docker-compose.yml
```

Expected: all four lines show explicit version tags, none show `:latest`.

**Step 5 — Commit**

```bash
git add docker-compose.yml
git commit -m "fix(supply-chain): pin 4 docker-compose :latest tags to explicit versions (#374)"
```

Expected: commit succeeds, no hook failures.

---

### Task 2: Add `@sha256:` digests to all Dockerfile FROM lines

**Files:** `backend/Dockerfile`, `backend/Dockerfile.forecast`, `dark-factory/Dockerfile`, `docker/Dockerfile.backup`, `frontend/Dockerfile`, `grafana/Dockerfile`, `monitoring/prometheus/Dockerfile`, `services/tweet-monitor/Dockerfile`

**Step 1 — Verify failing state**

```bash
grep -rn "^FROM" \
  backend/Dockerfile \
  backend/Dockerfile.forecast \
  dark-factory/Dockerfile \
  docker/Dockerfile.backup \
  frontend/Dockerfile \
  grafana/Dockerfile \
  monitoring/prometheus/Dockerfile \
  services/tweet-monitor/Dockerfile \
  | grep -v "@sha256:"
```

Expected: 8 lines (all FROM lines, none containing `@sha256:`).

**Step 2 — Pull each image and retrieve its sha256 digest**

For each base image, pull the exact tagged version and extract the repo digest. The format to use is `image:tag@sha256:<64-char-hex>`.

```bash
# Function to get the digest for a pulled image
get_digest() {
  local image="$1"
  docker inspect --format='{{index .RepoDigests 0}}' "$image" 2>/dev/null | sed 's/.*@//'
}

# Pull each base image (exact tag) and get digest
docker pull python:3.12-slim
DIGEST_PYTHON_312=$(get_digest python:3.12-slim)
echo "python:3.12-slim → $DIGEST_PYTHON_312"

docker pull python:3.11-slim
DIGEST_PYTHON_311=$(get_digest python:3.11-slim)
echo "python:3.11-slim → $DIGEST_PYTHON_311"

docker pull ubuntu:24.04
DIGEST_UBUNTU=$(get_digest ubuntu:24.04)
echo "ubuntu:24.04 → $DIGEST_UBUNTU"

docker pull alpine:3.19
DIGEST_ALPINE=$(get_digest alpine:3.19)
echo "alpine:3.19 → $DIGEST_ALPINE"

docker pull node:22-alpine
DIGEST_NODE=$(get_digest node:22-alpine)
echo "node:22-alpine → $DIGEST_NODE"

docker pull grafana/grafana:11.1.0
DIGEST_GRAFANA=$(get_digest grafana/grafana:11.1.0)
echo "grafana/grafana:11.1.0 → $DIGEST_GRAFANA"

docker pull prom/prometheus:v2.53.0
DIGEST_PROMETHEUS=$(get_digest prom/prometheus:v2.53.0)
echo "prom/prometheus:v2.53.0 → $DIGEST_PROMETHEUS"
```

Each variable holds a string like `sha256:abc123...` (64 hex chars after `sha256:`).

**Step 3 — Update each Dockerfile FROM line**

Apply the digest to each file. The format must be `image:tag@sha256:<hex>` — keep the human-readable tag and append the digest.

**`backend/Dockerfile`** — replace `FROM python:3.12-slim` with:
```dockerfile
FROM python:3.12-slim@$DIGEST_PYTHON_312
```

**`backend/Dockerfile.forecast`** — replace `FROM python:3.12-slim` with:
```dockerfile
FROM python:3.12-slim@$DIGEST_PYTHON_312
```

(Same digest as `backend/Dockerfile` — both use `python:3.12-slim`.)

**`dark-factory/Dockerfile`** — replace `FROM ubuntu:24.04` with:
```dockerfile
FROM ubuntu:24.04@$DIGEST_UBUNTU
```

**`docker/Dockerfile.backup`** — replace `FROM alpine:3.19` with:
```dockerfile
FROM alpine:3.19@$DIGEST_ALPINE
```

**`frontend/Dockerfile`** — replace `FROM node:22-alpine` with:
```dockerfile
FROM node:22-alpine@$DIGEST_NODE
```

**`grafana/Dockerfile`** — replace `FROM grafana/grafana:11.1.0` with:
```dockerfile
FROM grafana/grafana:11.1.0@$DIGEST_GRAFANA
```

**`monitoring/prometheus/Dockerfile`** — replace `FROM prom/prometheus:v2.53.0` with:
```dockerfile
FROM prom/prometheus:v2.53.0@$DIGEST_PROMETHEUS
```

**`services/tweet-monitor/Dockerfile`** — replace `FROM python:3.11-slim` with:
```dockerfile
FROM python:3.11-slim@$DIGEST_PYTHON_311
```

**Step 4 — Verify passing state**

```bash
# All FROM lines must now contain @sha256:
grep -rn "^FROM" \
  backend/Dockerfile \
  backend/Dockerfile.forecast \
  dark-factory/Dockerfile \
  docker/Dockerfile.backup \
  frontend/Dockerfile \
  grafana/Dockerfile \
  monitoring/prometheus/Dockerfile \
  services/tweet-monitor/Dockerfile \
  | grep -v "@sha256:"
```

Expected: no output (zero hits — all 8 FROM lines contain `@sha256:`).

```bash
# Verify sha256 values look correct (64 hex chars)
grep -rn "^FROM" \
  backend/Dockerfile \
  backend/Dockerfile.forecast \
  dark-factory/Dockerfile \
  docker/Dockerfile.backup \
  frontend/Dockerfile \
  grafana/Dockerfile \
  monitoring/prometheus/Dockerfile \
  services/tweet-monitor/Dockerfile \
  | grep -oP 'sha256:[0-9a-f]{64}' | wc -l
```

Expected: `8` (one valid digest per file).

**Step 5 — Commit**

```bash
git add \
  backend/Dockerfile \
  backend/Dockerfile.forecast \
  dark-factory/Dockerfile \
  docker/Dockerfile.backup \
  frontend/Dockerfile \
  grafana/Dockerfile \
  monitoring/prometheus/Dockerfile \
  services/tweet-monitor/Dockerfile
git commit -m "fix(supply-chain): add sha256 digests to all 8 Dockerfile FROM lines (#374)"
```

---

### Task 3: Pin GitHub Actions `uses:` to 40-character commit SHAs

**Files:** `.github/workflows/ci.yml`, `.github/workflows/ci-publish.yml`, `.github/workflows/deploy.yml`

**Step 1 — Verify failing state**

```bash
grep -rn "uses:" .github/workflows/ | grep -v "sha256" | grep -v "#"
```

Expected: multiple lines still referencing `@v4`, `@v5`, `@v6`, `@v3`, `@v1`, `@0.28.0` etc.

```bash
# Count unpinned references
grep -rn "uses:.*@v[0-9]\|uses:.*@[0-9]\." .github/workflows/ | wc -l
```

Expected: ≥10 lines.

**Step 2 — Look up the commit SHA for each action**

For each action, resolve its current tag to the underlying commit SHA. GitHub annotated tags require two API calls (tag object → commit object):

```bash
# Helper: resolve a GitHub Action tag to its commit SHA
resolve_action_sha() {
  local owner_repo="$1"   # e.g. "actions/checkout"
  local tag="$2"           # e.g. "v4.1.7"
  # Get the tag object SHA
  local tag_sha
  tag_sha=$(gh api "repos/${owner_repo}/git/ref/tags/${tag}" --jq '.object.sha' 2>/dev/null)
  local tag_type
  tag_type=$(gh api "repos/${owner_repo}/git/ref/tags/${tag}" --jq '.object.type' 2>/dev/null)
  if [ "$tag_type" = "tag" ]; then
    # Annotated tag — dereference to the commit
    gh api "repos/${owner_repo}/git/tags/${tag_sha}" --jq '.object.sha'
  else
    echo "$tag_sha"
  fi
}
```

Retrieve SHAs for the exact versions currently referenced in the workflows. Use the version tag comment to record the human-readable version:

```bash
# actions/checkout — find current v4.x.x tag (check releases page)
# https://github.com/actions/checkout/releases
SHA_CHECKOUT=$(resolve_action_sha "actions/checkout" "v4.2.2")
echo "actions/checkout@v4.2.2 → $SHA_CHECKOUT"

# actions/setup-python — find current v5.x.x tag
SHA_SETUP_PYTHON=$(resolve_action_sha "actions/setup-python" "v5.3.0")
echo "actions/setup-python@v5.3.0 → $SHA_SETUP_PYTHON"

# actions/setup-node — find current v4.x.x tag
SHA_SETUP_NODE=$(resolve_action_sha "actions/setup-node" "v4.1.0")
echo "actions/setup-node@v4.1.0 → $SHA_SETUP_NODE"

# actions/upload-artifact — find current v4.x.x tag
SHA_UPLOAD_ARTIFACT=$(resolve_action_sha "actions/upload-artifact" "v4.4.3")
echo "actions/upload-artifact@v4.4.3 → $SHA_UPLOAD_ARTIFACT"

# docker/login-action — find current v3.x.x tag
SHA_DOCKER_LOGIN=$(resolve_action_sha "docker/login-action" "v3.3.0")
echo "docker/login-action@v3.3.0 → $SHA_DOCKER_LOGIN"

# docker/metadata-action — find current v5.x.x tag
SHA_DOCKER_META=$(resolve_action_sha "docker/metadata-action" "v5.6.1")
echo "docker/metadata-action@v5.6.1 → $SHA_DOCKER_META"

# docker/build-push-action — find current v6.x.x tag
SHA_DOCKER_BUILD=$(resolve_action_sha "docker/build-push-action" "v6.15.0")
echo "docker/build-push-action@v6.15.0 → $SHA_DOCKER_BUILD"

# github/codeql-action/upload-sarif — v3.x.x
SHA_CODEQL=$(resolve_action_sha "github/codeql-action" "v3.28.1")
echo "github/codeql-action@v3.28.1 → $SHA_CODEQL"

# aquasecurity/trivy-action — @0.28.0
SHA_TRIVY=$(resolve_action_sha "aquasecurity/trivy-action" "0.28.0")
echo "aquasecurity/trivy-action@0.28.0 → $SHA_TRIVY"

# appleboy/ssh-action — v1.x.x
SHA_SSH=$(resolve_action_sha "appleboy/ssh-action" "v1.2.0")
echo "appleboy/ssh-action@v1.2.0 → $SHA_SSH"
```

> **Note:** The exact `v4.x.x` / `v5.x.x` patch versions above are illustrative. Before implementing, check the action's GitHub releases page to confirm the current latest stable patch tag under the major version alias, and use that exact tag in the `# vX.Y.Z` comment. The critical output is the 40-char commit SHA.

**Step 3 — Update `.github/workflows/ci.yml`**

Current unpinned references in `ci.yml` (lines 26, 29, 85, 93, 96, 141, 144):

```yaml
# Line 26 — replace:
      - uses: actions/checkout@v4
# with:
      - uses: actions/checkout@<SHA_CHECKOUT>  # v4.x.x

# Line 29 — replace:
        uses: actions/setup-python@v5
# with:
        uses: actions/setup-python@<SHA_SETUP_PYTHON>  # v5.x.x

# Line 85 — replace:
        uses: actions/upload-artifact@v4
# with:
        uses: actions/upload-artifact@<SHA_UPLOAD_ARTIFACT>  # v4.x.x

# Line 93 — replace:
      - uses: actions/checkout@v4
# with:
      - uses: actions/checkout@<SHA_CHECKOUT>  # v4.x.x

# Line 96 — replace:
        uses: actions/setup-node@v4
# with:
        uses: actions/setup-node@<SHA_SETUP_NODE>  # v4.x.x

# Line 141 — replace:
      - uses: actions/checkout@v4
# with:
      - uses: actions/checkout@<SHA_CHECKOUT>  # v4.x.x

# Line 144 — replace:
        uses: actions/setup-python@v5
# with:
        uses: actions/setup-python@<SHA_SETUP_PYTHON>  # v5.x.x
```

**Step 4 — Update `.github/workflows/ci-publish.yml`**

Current unpinned references in `ci-publish.yml` (lines 17, 20, 28, 36, 47, 50, 58, 66, 77, 80, 88, 96, 118, 121, 128, 138, 148):

```yaml
# Lines 17, 47, 77, 118 — replace all:
      - uses: actions/checkout@v4
# with:
      - uses: actions/checkout@<SHA_CHECKOUT>  # v4.x.x

# Lines 20, 50, 80, 121 — replace all:
        uses: docker/login-action@v3
# with:
        uses: docker/login-action@<SHA_DOCKER_LOGIN>  # v3.x.x

# Lines 28, 58, 88 — replace all:
        uses: docker/metadata-action@v5
# with:
        uses: docker/metadata-action@<SHA_DOCKER_META>  # v5.x.x

# Lines 36, 66, 96 — replace all:
        uses: docker/build-push-action@v6
# with:
        uses: docker/build-push-action@<SHA_DOCKER_BUILD>  # v6.x.x

# Lines 128, 138 — replace all:
        uses: aquasecurity/trivy-action@0.28.0
# with:
        uses: aquasecurity/trivy-action@<SHA_TRIVY>  # 0.28.0

# Line 148 — replace:
        uses: github/codeql-action/upload-sarif@v3
# with:
        uses: github/codeql-action/upload-sarif@<SHA_CODEQL>  # v3.x.x
```

**Step 5 — Update `.github/workflows/deploy.yml`**

Current unpinned reference in `deploy.yml` (line 24):

```yaml
# Line 24 — replace:
        uses: appleboy/ssh-action@v1
# with:
        uses: appleboy/ssh-action@<SHA_SSH>  # v1.x.x
```

**Step 6 — Verify passing state**

```bash
# No version-aliased references should remain
grep -rn "uses:.*@v[0-9]\|uses:.*@[0-9]\." .github/workflows/
```

Expected: no output (all `uses:` lines now reference 40-char SHAs).

```bash
# Count SHA-pinned lines (should equal the total uses: count)
grep -c "uses:.*@[0-9a-f]\{40\}" .github/workflows/ci.yml \
  .github/workflows/ci-publish.yml \
  .github/workflows/deploy.yml 2>/dev/null
```

Expected: file-by-file counts summing to ≥18 (all `uses:` references in those three files).

```bash
# Confirm version comments are present for readability
grep "uses:.*@[0-9a-f]\{40\}" .github/workflows/ci.yml \
  .github/workflows/ci-publish.yml \
  .github/workflows/deploy.yml | grep -v "#"
```

Expected: no output (every pinned line has a `# vX.Y.Z` comment).

**Step 7 — Commit**

```bash
git add .github/workflows/ci.yml .github/workflows/ci-publish.yml .github/workflows/deploy.yml
git commit -m "fix(supply-chain): pin GitHub Actions uses: to commit SHAs (#374)"
```

---

### Task 4: Add Dependabot config for docker + github-actions

**Files:** `.github/dependabot.yml` (new)

**Step 1 — Verify failing state**

```bash
ls .github/dependabot.yml 2>/dev/null && echo "EXISTS" || echo "NOT EXISTS"
```

Expected: `NOT EXISTS`.

**Step 2 — Create `.github/dependabot.yml`**

```yaml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"

  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"
```

> **Note on Dockerfile discovery:** If Dependabot does not surface Dockerfile updates from all subdirectories (backend/, frontend/, etc.) via the root `"/"` directory entry, add per-directory `docker` entries after the first PR wave. Observe the first Dependabot run output to determine if additional directory scopes are needed.

**Step 3 — Verify passing state**

```bash
ls .github/dependabot.yml
```

Expected: file exists.

```bash
grep "package-ecosystem" .github/dependabot.yml
```

Expected:
```
  - package-ecosystem: "github-actions"
  - package-ecosystem: "docker"
```

**Step 4 — Commit**

```bash
git add .github/dependabot.yml
git commit -m "feat(supply-chain): add Dependabot config for docker + github-actions (#374)"
```

---

## End-to-End Verification

After all four tasks, run the full verification suite from the spec:

```bash
# Req 1: No :latest in any docker-compose file
grep -R ":latest" docker-compose*.yml
# Expected: no output

# Req 2: All FROM lines have @sha256:
grep -rn "^FROM" \
  backend/Dockerfile backend/Dockerfile.forecast dark-factory/Dockerfile \
  docker/Dockerfile.backup frontend/Dockerfile grafana/Dockerfile \
  monitoring/prometheus/Dockerfile services/tweet-monitor/Dockerfile \
  | grep -v "@sha256:"
# Expected: no output

# Req 3: All uses: references contain 40-char SHAs
grep -rn "uses:" .github/workflows/ | grep -v "@[0-9a-f]\{40\}"
# Expected: no output (all uses: lines use SHA pins)

# Req 4: Dependabot config covers docker + github-actions
cat .github/dependabot.yml | grep "package-ecosystem"
# Expected: two entries (github-actions, docker)

# Req 5: No runtime changes — confirm compose services still start
docker-compose config --quiet
# Expected: exits 0 with no errors
```

---

## Notes

- The `ghcr.io/omniscient/markethawk-*` and `ghcr.io/omniscient/markethawk-dark-factory` images in `docker-compose.yml` use `${IMAGE_TAG:-latest}` which is a parameterized tag set at deployment time — these are intentional and not in scope for this fix.
- `jaegertracing/all-in-one:1.57`, `caddy:2-alpine`, `postgres:15-alpine`, `redis:7-alpine`, and `ghcr.io/gnzsnz/ib-gateway:stable` are already versioned (non-`:latest`) and are not in scope.
- The `ghcr.io/gnzsnz/ib-gateway:stable` tag is a rolling alias managed upstream; it is outside this issue's scope (not listed in F-SUPPLY-01 affected items).
