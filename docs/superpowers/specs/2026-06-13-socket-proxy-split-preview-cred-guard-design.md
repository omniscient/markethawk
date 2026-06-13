# Docker Socket Proxy Split + Preview Credential Guard

**Date:** 2026-06-13
**Issue:** #379
**Epic:** #372 (Defensive Security Review 2026-06-12)
**Status:** Spec

---

## Problem

Two related security findings from the 2026-06-12 defensive security review:

1. **Socket-proxy over-privilege**: The single `docker-socket-proxy` shared by the
   dark-factory and backlog-scheduler has `BUILD=1` and `POST=1` enabled. A foothold
   in the long-lived scheduler container (which polls GitHub continuously) would allow
   building and running arbitrary Docker images — the same blast radius as the scheduler
   gaining unrestricted Docker socket access.

2. **Preview compose hardcoded credentials**: `dark-factory/docker-compose.preview.yml`
   hardcodes `POSTGRES_PASSWORD: preview_password` and
   `JWT_SECRET_KEY: preview-only-not-secret-0123456789abcdef`. These are intentional for
   ephemeral CI stacks, but there is no machine-enforced guard preventing the file from
   being used on a long-lived or staging host.

---

## Requirements

1. The backlog-scheduler gets a **dedicated socket proxy** with only the verbs it actually
   uses: `CONTAINERS=1, IMAGES=1, POST=1` (no BUILD, no EXEC, no NETWORKS, no VOLUMES).
2. The dark-factory gets a **dedicated socket proxy** with the full set it requires:
   `CONTAINERS=1, IMAGES=1, NETWORKS=1, VOLUMES=1, BUILD=1, POST=1, EXEC=1`.
   (Note: `EXEC=1` is also a **bug fix** — it was previously `0`, causing the
   preview-up postgres-probe to silently fall back to "0 tables" and re-run
   migrations on every continue run.)
3. A **pre-commit hook** and **CI lint step** greps all `docker-compose*.yml` files
   (except the allowlisted `dark-factory/docker-compose.preview.yml`) for the literal
   strings `preview_password` and `preview-only-not-secret`. Blocks on any match.
4. The preview compose file uses **env var fallbacks** so a non-ephemeral host can
   override the defaults:
   - `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-preview_password}`
   - `JWT_SECRET_KEY: ${JWT_SECRET_KEY:-preview-only-not-secret-0123456789abcdef}`
5. The `close-preview` DAG node asserts that `docker ps -a --filter name=mh-preview-${ISSUE}`
   returns empty after teardown; the node fails (non-zero exit) if containers remain.
6. The backlog-scheduler emits a **startup warning** (not a hard failure) if
   `docker ps -a --filter name=mh-preview` finds any stale preview containers; the
   threshold uses `STALE_PREVIEW_WARN_COUNT` (env var default: 3).

---

## Architecture / Approach

### Split: two proxy services

Replace the single `docker-socket-proxy` with two services in `docker-compose.yml`:

```yaml
# Proxy for backlog-scheduler only — no BUILD, no EXEC
docker-socket-proxy-scheduler:
  image: tecnativa/docker-socket-proxy:latest
  container_name: markethawk-docker-socket-proxy-scheduler
  restart: unless-stopped
  environment:
    CONTAINERS: 1
    IMAGES: 1
    POST: 1
    BUILD: 0
    EXEC: 0
    NETWORKS: 0
    VOLUMES: 0
    SERVICES: 0
    AUTH: 0
    SECRETS: 0
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
  networks:
    - factory-network

# Proxy for dark-factory only — full set including BUILD, EXEC
docker-socket-proxy-factory:
  image: tecnativa/docker-socket-proxy:latest
  container_name: markethawk-docker-socket-proxy-factory
  restart: unless-stopped
  environment:
    CONTAINERS: 1
    IMAGES: 1
    NETWORKS: 1
    VOLUMES: 1
    BUILD: 1
    POST: 1
    EXEC: 1
    SERVICES: 0
    AUTH: 0
    SECRETS: 0
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
  networks:
    - factory-network
```

Wire each consumer to its own proxy:
- `backlog-scheduler`: `DOCKER_HOST: tcp://docker-socket-proxy-scheduler:2375`,
  `depends_on: [docker-socket-proxy-scheduler]`
- `dark-factory`: `DOCKER_HOST: tcp://docker-socket-proxy-factory:2375`,
  `depends_on: [docker-socket-proxy-factory]`

The old `docker-socket-proxy` service and `markethawk-docker-socket-proxy` container
are removed.

The `docker-compose.override.yml` does not reference the proxy service (no change
needed there).

### Cred guard: pre-commit + env var fallback

**`dark-factory/scripts/check_preview_creds.sh`** (new, ~15 lines):
```bash
#!/usr/bin/env bash
ALLOWLIST="dark-factory/docker-compose.preview.yml"
DANGEROUS=("preview_password" "preview-only-not-secret")
FAILED=0
for pattern in "${DANGEROUS[@]}"; do
  hits=$(grep -rl "$pattern" . --include="docker-compose*.yml" 2>/dev/null \
         | grep -v "$ALLOWLIST" || true)
  if [ -n "$hits" ]; then
    echo "ERROR: preview credential '$pattern' found outside allowlisted file:"
    echo "$hits"
    FAILED=1
  fi
done
exit $FAILED
```

Register in `.pre-commit-config.yaml`:
```yaml
- repo: local
  hooks:
    - id: check-preview-creds
      name: No preview credentials in compose files
      entry: bash dark-factory/scripts/check_preview_creds.sh
      language: system
      pass_filenames: false
      files: docker-compose.*\.yml$
```

Add the same script as a step in `.github/workflows/ci.yml` (or the existing lint job).

**`dark-factory/docker-compose.preview.yml`** credential lines become:
```yaml
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-preview_password}
JWT_SECRET_KEY: ${JWT_SECRET_KEY:-preview-only-not-secret-0123456789abcdef}
```
The `DATABASE_URL` and seed-container `PGPASSWORD` references that hardcode
`preview_password` are updated to use `${POSTGRES_PASSWORD:-preview_password}` for
consistency.

### Teardown verification

**`close-preview` DAG node** (`.archon/workflows/archon-dark-factory.yaml`):
After the existing `docker compose -p "mh-preview-${ISSUE}" down -v`, add:
```bash
REMAINING=$(docker ps -a --filter "name=mh-preview-${ISSUE}" --format '{{.Names}}' 2>/dev/null || true)
if [ -n "$REMAINING" ]; then
  echo "ERROR: preview containers still running after teardown: $REMAINING" >&2
  exit 1
fi
echo "Teardown verified — no mh-preview-${ISSUE} containers remain."
```

**`dark-factory/scheduler.sh` startup**:
After the existing image-check probe, add a stale-preview warning:
```bash
STALE_PREVIEW_WARN_COUNT="${STALE_PREVIEW_WARN_COUNT:-3}"
STALE=$(docker ps -a --filter "name=mh-preview" --format '{{.Names}}' 2>/dev/null | wc -l || echo 0)
if [ "$STALE" -gt "$STALE_PREVIEW_WARN_COUNT" ]; then
  echo "[$(date -u +%FT%TZ)] WARNING: ${STALE} stale mh-preview-* containers found. Run 'Close issue #N' for each." >&2
fi
```

---

## Alternatives Considered

### Single proxy, accept BUILD+POST
Simpler — no service duplication. Rejected because the scheduler is the long-lived
always-on daemon (restart: unless-stopped, polling GitHub continuously) and retaining
BUILD there means a compromised scheduler container can build/run arbitrary images.
The asymmetry between scheduler and factory is real and audit-visible; splitting is
the right response.

### Option B: restructure preview-up to not use `--build`
Not viable — `docker buildx build` routes the same `POST /build` through the proxy,
so removing `docker compose up --build` in favor of a separate build step would not
drop `BUILD` from the required verb set.

### Env var fallback only (no grep guard)
Option C (env fallback) alone is insufficient because its silent-default failure mode
is precisely the staging-host risk the issue raises — a host without env vars set would
silently get the weak credentials. The static grep is the actual gate.

---

## Open Questions

- The `EXEC=0` bug (silent postgres-probe fallback) pre-exists this issue. The factory
  proxy fixes it as a side effect. Verify after implementation that `docker compose exec`
  in `preview-up` actually runs the TABLE_COUNT probe correctly now.
- The `docker-compose.override.yml` does not reference the proxy; confirm the override
  doesn't re-introduce raw `/var/run/docker.sock` volume mounts on any service.

---

## Assumptions

- Both proxy containers join the existing `factory-network`; no new network is needed.
- The `tecnativa/docker-socket-proxy:latest` image supports independent `BUILD`,
  `EXEC`, `NETWORKS`, `VOLUMES` env vars (confirmed in existing usage).
- The pre-commit hook fires only on changed `docker-compose*.yml` files
  (`pass_filenames: false` + `files:` pattern); it does not slow down unrelated commits.
- The scheduler's stale-preview warning is non-blocking (advisory only) so it does not
  trigger `restart: unless-stopped` loops.
