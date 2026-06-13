# Pin Floating Tags + Unpinned Base Images/Actions (F-SUPPLY-01)

**Date:** 2026-06-13
**Issue:** #374
**Epic:** #372 (Defensive Security Review 2026-06-12)
**Status:** Spec

---

## Problem

Four Docker Compose services use `:latest` tags, all Dockerfile `FROM` lines use mutable
tags without sha256 digests, and all GitHub Actions are pinned only to major version aliases
(e.g. `@v4`). Because the dark factory rebuilds images on every workflow, a retagged or
compromised upstream image or action silently enters the next build — supply-chain drift
with no review gate.

---

## Requirements

1. All four docker-compose `:latest` images are replaced with explicit version tags.
2. All Dockerfile `FROM` lines carry `@sha256:` digests alongside the human-readable tag
   (format: `image:tag@sha256:<digest>`), applied to every Dockerfile regardless of whether
   the base tag was already versioned.
3. All GitHub Actions `uses:` references are pinned to 40-character commit SHAs with the
   version tag preserved as a trailing comment (format:
   `uses: actions/checkout@<sha>  # v4.x.x`).
4. A Dependabot config (`/.github/dependabot.yml`) is added, covering `docker` and
   `github-actions` ecosystems, to keep pins fresh under human review. Scope is limited to
   these two ecosystems; `pip` and `npm` updates are a separate concern.
5. No existing runtime behaviour changes — this is purely a build-time reproducibility fix.

---

## Architecture / Approach

### docker-compose.yml — Replace `:latest` with explicit version tags

The four affected services and their recommended pins (implementer must retrieve current
stable versions at time of work and verify via `docker pull <image>:<version>`):

| Service image | Current | Recommended version |
|---|---|---|
| `dpage/pgadmin4` | `:latest` | latest stable (e.g. `8.x`) |
| `datalust/seq` | `:latest` | latest stable (e.g. `2024.x`) |
| `datalust/seq-input-gelf` | `:latest` | version matching seq above |
| `tecnativa/docker-socket-proxy` | `:latest` | latest stable |

The implementer retrieves digests via:
```bash
docker pull <image>:<version>
docker inspect --format='{{index .RepoDigests 0}}' <image>:<version>
```

Compose image references do **not** need sha256 digests — explicit version tags satisfy
the verification criteria (`grep -R ":latest" docker-compose*.yml` → no hits) and are the
idiomatic approach for compose services.

### Dockerfiles — Add `@sha256:` digests to all FROM lines

All eight Dockerfiles need their `FROM` lines converted to `image:tag@sha256:<digest>` format:

| Dockerfile | Current FROM |
|---|---|
| `backend/Dockerfile` | `FROM python:3.12-slim` |
| `backend/Dockerfile.forecast` | `FROM python:3.12-slim` |
| `dark-factory/Dockerfile` | `FROM ubuntu:24.04` |
| `docker/Dockerfile.backup` | `FROM alpine:3.19` |
| `frontend/Dockerfile` | `FROM node:22-alpine` |
| `grafana/Dockerfile` | `FROM grafana/grafana:11.1.0` |
| `monitoring/prometheus/Dockerfile` | `FROM prom/prometheus:v2.53.0` |
| `services/tweet-monitor/Dockerfile` | `FROM python:3.11-slim` |

Even Dockerfiles that already use versioned tags (`alpine:3.19`, `grafana/grafana:11.1.0`,
etc.) receive sha256 digests: named tags are mutable and the fix targets immutability.

The convention keeps both tag and digest for readability:
```dockerfile
FROM python:3.12-slim@sha256:<64-char-hex>
```

Digests are retrieved at implementation time via `docker inspect` or by pulling and
inspecting. The implementer must pull the specific tagged version (not `:latest`) before
inspecting to get the correct digest.

### GitHub Actions — Pin to commit SHAs

All `uses:` lines in `.github/workflows/ci.yml`, `.github/workflows/ci-publish.yml`, and
`.github/workflows/deploy.yml` are converted to commit-SHA form with a version comment:

```yaml
# Before
- uses: actions/checkout@v4
# After
- uses: actions/checkout@<40-char-sha>  # v4.x.x
```

Actions to pin (current major-version references):

| Action | Current |
|---|---|
| `actions/checkout` | `@v4` |
| `actions/setup-python` | `@v5` |
| `actions/setup-node` | `@v4` |
| `actions/upload-artifact` | `@v4` |
| `docker/login-action` | `@v3` |
| `docker/metadata-action` | `@v5` |
| `docker/build-push-action` | `@v6` |
| `github/codeql-action/upload-sarif` | `@v3` |
| `aquasecurity/trivy-action` | `@0.28.0` |
| `appleboy/ssh-action` | `@v1` |

Commit SHAs are retrieved from each action's GitHub release page or via:
```bash
gh api repos/<owner>/<repo>/git/ref/tags/<tag> --jq '.object.sha'
# If the tag points to a tag object (annotated), dereference:
gh api repos/<owner>/<repo>/git/tags/<tag-sha> --jq '.object.sha'
```

### Dependabot — docker + github-actions

Add `/.github/dependabot.yml` with two update entries:

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

Additional `docker` entries may be needed for each Dockerfile subdirectory if Dependabot
does not discover them from the root. Check post-merge whether Dependabot surfaces all
Dockerfiles; add per-directory entries if needed.

A weekly schedule with no grouping config is the default starting point to avoid PR noise.
Grouping rules can be tuned in a follow-up once the PR volume is observed.

---

## Alternatives Considered

### A: Digest-only (no tag in FROM lines)
`FROM python@sha256:<digest>` — omits the human-readable tag. Rejected: loses the version
signal that tells reviewers which base image release is in use; also breaks Dependabot's
ability to parse and bump the version.

### B: Pin compose services with sha256 in addition to version tags
Docker Compose supports the `image:tag@sha256:digest` format. Rejected for compose: the
verification criteria only requires no `:latest` hits, and digest pinning in compose requires
re-pulling and updating more frequently. Explicit version tags are the standard practice for
compose; sha256 digests belong in Dockerfiles where reproducibility matters most.

### C: Use Renovate instead of Dependabot
Renovate is more flexible (supports grouped PRs, auto-merge, more ecosystems). Rejected for
now: no existing config, and adding a new tool for a `priority: should-have` security fix
adds unnecessary complexity. Dependabot is built into GitHub and requires no extra service.
Renovate can replace it in a future refactor if the team prefers its semantics.

---

## Open Questions (non-blocking)

1. **Dependabot PR noise** — after enabling, the team may want to add grouping rules or
   increase the schedule interval (monthly) if weekly PRs become too frequent. Tunable
   post-merge.

2. **dark-factory image rebuild** — the dark-factory pulls and builds images on each run.
   Pinning `ubuntu:24.04` to a digest means factory builds use exactly that digest layer.
   If the factory's host Docker daemon already has the layer cached with a different digest,
   a forced pull will happen. This is expected behaviour, not a bug.

---

## Assumptions

- Implementer has Docker pull access to all referenced images to retrieve live digests.
- `gh` CLI is available for SHA lookup from GitHub release tags.
- The dark factory's CI will rebuild images cleanly after the digest pins are applied (no
  build cache compatibility issue).
- Dependabot is enabled for the `omniscient/markethawk` repository (GitHub setting,
  not a code change).
