# Docker Socket Hardening + Non-Root Containers — Design Spec

**Date:** 2026-06-05  
**Status:** Brainstormed → ready for implementation plan  
**Issue:** [#203 — Harden Docker socket mount (dark-factory / scheduler) + non-root containers](https://github.com/omniscient/markethawk/issues/203)

## Overview

Two overlapping security gaps carried over from the Architecture Quality Report v2:

1. **Raw Docker socket mount** — `/var/run/docker.sock` is bound directly into `dark-factory` and `backlog-scheduler`. Any process in either container can make arbitrary Docker API calls to the host daemon, which is equivalent to root on the host.

2. **Root-running app containers** — `backend/Dockerfile`, `frontend/Dockerfile`, and `dark-factory/Dockerfile` have no `USER` directive. All process trees inside those containers run as UID 0.

ADR-0008 already described `tecnativa/docker-socket-proxy` as the intended security boundary but it was never implemented. This spec implements what ADR-0008 promised and adds the Dockerfile non-root changes.

## Requirements

From acceptance criteria + Q&A:

- Replace raw `/var/run/docker.sock` mounts in `dark-factory` and `backlog-scheduler` with `DOCKER_HOST=tcp://docker-socket-proxy:2375`.
- Add `docker-socket-proxy` as an always-on (no profile, `restart: unless-stopped`) service on `factory-network` only.
- Proxy allowlist: `CONTAINERS=1, IMAGES=1, NETWORKS=1, VOLUMES=1, BUILD=1, POST=1`; block `SERVICES=0, EXEC=0`.
- Add non-root `USER` to `backend/Dockerfile` (new `appuser` UID 1000), `frontend/Dockerfile` (existing `node` user from `node:22-alpine`), and `dark-factory/Dockerfile` (new `factory` user UID 1000 — closing the gap with ADR-0008's existing promise).
- Update ADR-0008 in-place to: (a) mark the proxy as now-implemented, (b) add a formal residual-risk-acceptance section.

**Out of scope**: `grafana/Dockerfile` and `monitoring/prometheus/Dockerfile` (upstream images already run non-root), `services/tweet-monitor/Dockerfile`, `backend/Dockerfile.forecast` (outside the socket/app security thesis of this issue).

## Architecture

### 1. Socket Proxy Service (`docker-compose.yml`)

Add a new service before `dark-factory`:

```yaml
docker-socket-proxy:
  image: tecnativa/docker-socket-proxy:latest
  container_name: markethawk-docker-socket-proxy
  restart: unless-stopped
  environment:
    CONTAINERS: 1
    IMAGES: 1
    NETWORKS: 1
    VOLUMES: 1
    BUILD: 1
    POST: 1
    SERVICES: 0
    EXEC: 0
    AUTH: 0
    SECRETS: 0
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
  networks:
    - factory-network
```

The proxy is always-on (no profile) because `backlog-scheduler` runs under the `scheduler` profile and is a long-running daemon — the proxy lifecycle must be a superset of both the `scheduler` and `factory` profiles.

### 2. Drop Raw Socket Mounts

In `dark-factory` and `backlog-scheduler`:
- Remove `- /var/run/docker.sock:/var/run/docker.sock` from `volumes:`
- Add `DOCKER_HOST: tcp://docker-socket-proxy:2375` to `environment:`
- Add `depends_on: [docker-socket-proxy]`

`POST=1` is required: without it, the proxy blocks all write operations, preventing `docker compose run`, `docker build`, network and volume creation for preview stacks.

### 3. `backend/Dockerfile` — Non-Root User

```dockerfile
# After the COPY . . line, before EXPOSE
RUN addgroup --system --gid 1000 appuser \
 && adduser --system --uid 1000 --ingroup appuser --no-create-home appuser

COPY --chown=appuser:appuser . .

USER appuser
```

The `python:3.12-slim` base provides no pre-existing app user. UID/GID 1000 is the convention. All celery-worker and celery-beat services share this Dockerfile and inherit the change automatically. The app reads files at `/app` but does not write to it at runtime (Alembic migrations run in a separate migration step, not in the long-running process).

### 4. `frontend/Dockerfile` — Non-Root User

```dockerfile
# node:22-alpine already ships a `node` user (UID 1000)
# After npm install and COPY, before EXPOSE:
RUN chown -R node:node /app
USER node
```

The `node:22-alpine` base image already provides a `node` user (UID 1000). No new user creation needed. The dev-mode `CMD ["npm", "run", "dev", "--", "--host"]` binds to port 3333 (non-privileged), so no capabilities needed.

### 5. `dark-factory/Dockerfile` — Non-Root `factory` User (UID 1000)

This is the highest-value change (the socket proxy consumer) and carries the most implementation risk because of path coupling.

**Key dependencies to relocate:**

| Current path | Root cause | Fix |
|---|---|---|
| `ENV PATH="/root/.bun/bin:${PATH}"` | Bun installs to current user's home | Install Bun as root to `/opt/bun`; update PATH |
| `/root/.archon/workspaces/...` in `entrypoint.sh:585` | Hardcoded absolute path | Replace with `${HOME}/.archon/workspaces/...` |
| Archon CLI `bun link` in `/root/.bun` scope | bun link writes to user's local bin | Link in `/opt/bun` scope (globally accessible) |

**Approach:**

```dockerfile
# Install Bun to /opt/bun (not user-home) so it works for any user
RUN mkdir -p /opt/bun && \
    BUN_INSTALL=/opt/bun curl -fsSL https://bun.sh/install | bash

ENV PATH="/opt/bun/bin:${PATH}"

# Create factory user AFTER all root-level installs
RUN groupadd --gid 1000 factory && \
    useradd --uid 1000 --gid 1000 --create-home --home-dir /home/factory factory

# Fix workspace ownership
RUN chown -R factory:factory /workspace

# Archon link must be visible to factory user
RUN cd /opt/archon/packages/cli && /opt/bun/bin/bun link

USER factory
WORKDIR /workspace
```

`entrypoint.sh` line 585 must be updated:
```bash
DECONFLICT_ARTIFACTS_DIR="${HOME}/.archon/workspaces/omniscient/markethawk/artifacts"
```

This change must be tested against the full entrypoint workflow (GitHub CLI auth, Archon `archon workflow run`, preview stack creation) to catch any remaining `/root/` path assumptions.

### 6. ADR-0008 Update

Update `docs/adr/0008-dark-factory-autonomous-development.md` to:

1. Change the **Status** line from `Accepted` to `Accepted (updated 2026-06-05 — socket proxy implemented, factory user added)`.
2. Replace the aspirational language "The Dark Factory uses `tecnativa/docker-socket-proxy`" with present-tense description of the now-implemented proxy.
3. Update "Claude Code runs inside the factory as a non-root user (`factory`, UID 1000)" — change "runs" to confirm it is now enforced via `USER factory` in the Dockerfile.
4. Add a **Residual Risk Acceptance** subsection under **Consequences**:

> **Residual Risk Acceptance (2026-06-05):** `tecnativa/docker-socket-proxy` does not support label-based container filtering. With `POST=1, CONTAINERS=1`, the factory can create or list any container on the host, not only `mh-preview-*` stacks. This risk is accepted: the factory is a trusted first-party tool run by the repo owner, not an adversarial workload. The entrypoint and Archon workflows operate on `mh-preview-*` resources by convention. A custom proxy with namespace-enforcement would require writing and maintaining a bespoke API gateway — cost not justified at this scale. Reviewed and accepted: issue #203.

## Alternatives Considered

### Rootless Docker

Replace the Docker daemon with rootless mode (user-namespaced daemon). Would eliminate the socket-as-root problem entirely — each user's daemon is isolated.

**Rejected**: Requires kernel user-namespace configuration on the host (`/etc/subuid`, `/etc/subgid`), a separate socket path per user, and changes to the host systemd unit. Non-trivial to set up in a WSL2/dev environment. No existing precedent in this stack. Higher operational complexity for a dev/self-hosted tool.

### Docker-in-Docker (DinD)

Run a full Docker daemon inside the factory container using `--privileged` mode.

**Rejected**: `--privileged` grants even broader host capabilities than the socket mount it replaces. DinD image builds are slow (no layer cache sharing with host), and the privileged flag is widely considered worse than the restricted socket approach for security.

### Share the `factory` Profile for the Proxy

Put `docker-socket-proxy` under `profiles: [factory]` alongside `dark-factory`.

**Rejected**: `backlog-scheduler` is under the `scheduler` profile (not `factory`) and runs continuously. If the proxy shared the `factory` profile, the scheduler would lose its Docker API access between factory invocations. The proxy's lifecycle must be always-on to be a reliable dependency for the scheduler.

## Open Questions

- **Bun install path**: The standard `bun install` script always writes to `$BUN_INSTALL` or `$HOME/.bun`. Setting `BUN_INSTALL=/opt/bun` before the curl invocation should redirect the install. This should be verified during implementation; if the env var is not honored, a manual `mv /root/.bun /opt/bun` + PATH fix is the fallback.
- **Pre-existing `mh-preview-*` containers**: Any running preview stacks from before this change will not be affected (they were started by old code). The proxy change is forward-only.

## Assumptions

- `tecnativa/docker-socket-proxy:latest` is an acceptable version pin; the team may want to pin to a specific digest for production hardening (non-blocking, can be done post-merge).
- No volume or bind-mount in `backend` or `frontend` containers writes to paths owned by root at runtime — the Alembic migration runs in a separate `migrate` step, not the long-running server process.
- The factory `scheduler.sh` DECONFLICT_ARTIFACTS_DIR on line 585 is the only hardcoded `/root/` path in entrypoint.sh (confirmed by grep; no other occurrences).
- The `node:22-alpine` `node` user (UID 1000) does not conflict with any host-mapped volume permissions. If the scheduler_state volume is mapped to a path owned by a different UID, the celery beat/worker will hit permission errors — but this does not affect the factory/scheduler services (they use different volumes).
