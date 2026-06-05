# Docker Socket Hardening + Non-Root Containers — Implementation Plan

**Date:** 2026-06-05  
**Issue:** [#203 — Harden Docker socket mount (dark-factory / scheduler) + non-root containers](https://github.com/omniscient/markethawk/issues/203)  
**Spec:** `docs/superpowers/specs/2026-06-05-docker-socket-hardening-design.md`  
**Branch:** `refine/issue-203--arch-v2--med--harden-docker-socket-moun`

## Goal

Replace raw `/var/run/docker.sock` mounts in `dark-factory` and `backlog-scheduler` with a `tecnativa/docker-socket-proxy` sidecar. Add non-root `USER` directives to `backend/Dockerfile` (`appuser` UID 1000), `frontend/Dockerfile` (existing `node` user), and `dark-factory/Dockerfile` (`factory` UID 1000, with Bun relocated to `/opt/bun`). Fix the one hardcoded `/root/` path in `entrypoint.sh`. Update ADR-0008 to present-tense and add a residual-risk-acceptance section.

## Architecture

- `docker-socket-proxy` is added as an always-on service (no profile, `restart: unless-stopped`) on `factory-network` only, so it is a lifecycle superset of both the `scheduler` and `factory` profiles.
- `dark-factory` and `backlog-scheduler` drop their `volumes: /var/run/docker.sock` and instead set `DOCKER_HOST: tcp://docker-socket-proxy:2375` plus `depends_on: [docker-socket-proxy]`.
- All app-container Dockerfiles (`backend`, `frontend`, `dark-factory`) add a non-root user. The `dark-factory` change is the most complex because Bun must be installed to `/opt/bun` (not `$HOME/.bun`) before the user switch.
- `entrypoint.sh` line 585 uses `${HOME}` instead of the hardcoded `/root/` so the artifacts directory resolves correctly under UID 1000.

## Tech Stack

- Docker Compose v2, `tecnativa/docker-socket-proxy:latest`, `python:3.12-slim`, `node:22-alpine`, `ubuntu:24.04`
- Bash shell scripts (`entrypoint.sh`, `scheduler.sh`)
- Markdown (ADR update)

## File Structure

| File | Change |
|------|--------|
| `docker-compose.yml` | Add `docker-socket-proxy` service; drop socket volumes from `dark-factory` and `backlog-scheduler`; add `DOCKER_HOST` env + `depends_on` |
| `backend/Dockerfile` | Add `addgroup`/`adduser` + `chown` + `USER appuser` |
| `frontend/Dockerfile` | Add `chown` + `USER node` |
| `dark-factory/Dockerfile` | Relocate Bun to `/opt/bun`; add `factory` user; `USER factory` at end |
| `dark-factory/entrypoint.sh` | Line 585: `/root/.archon` → `${HOME}/.archon` |
| `docs/adr/0008-dark-factory-autonomous-development.md` | Update status, present-tense prose, residual risk section |

---

## Task 1 — Add `docker-socket-proxy` service to `docker-compose.yml`

**Files:** `docker-compose.yml`

### TDD Steps

**Write failing test** — assert the service does not exist yet:
```bash
# Run from repo root
grep -q "docker-socket-proxy" docker-compose.yml && echo "ALREADY EXISTS" || echo "NOT FOUND — expected"
# Expected output: NOT FOUND — expected
```

**Implement** — Insert the following block into `docker-compose.yml` immediately before the `dark-factory:` service (before line 411 in the current file). Find the exact insertion point with:
```bash
grep -n "# Dark Factory" docker-compose.yml
```

Add this service block:
```yaml
  # Docker Socket Proxy — restricts Docker API access for dark-factory and backlog-scheduler
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

**Verify passing test:**
```bash
grep -q "docker-socket-proxy" docker-compose.yml && echo "PASS" || echo "FAIL"
# Expected: PASS

docker compose config --quiet && echo "YAML valid" || echo "YAML INVALID"
# Expected: YAML valid

grep -A5 "docker-socket-proxy:" docker-compose.yml | grep "restart: unless-stopped" && echo "PASS restart" || echo "FAIL"
# Expected: PASS restart

grep -A10 "docker-socket-proxy:" docker-compose.yml | grep "factory-network" && echo "PASS network" || echo "FAIL"
# Expected: PASS network

# Verify no profile restriction (should NOT appear on proxy service)
awk '/docker-socket-proxy:/,/^  [a-z]/' docker-compose.yml | grep "profiles:" && echo "FAIL — proxy has a profile" || echo "PASS — no profile on proxy"
# Expected: PASS — no profile on proxy
```

**Commit:**
```bash
git add docker-compose.yml
git commit -m "feat(infra): add docker-socket-proxy sidecar service

Adds tecnativa/docker-socket-proxy as always-on (no profile) on
factory-network. Allowlist: CONTAINERS, IMAGES, NETWORKS, VOLUMES, BUILD,
POST=1; SERVICES, EXEC, AUTH, SECRETS=0. Proxy lifecycle is a superset of
both 'factory' and 'scheduler' profiles so the scheduler daemon always has
Docker API access.

Closes part of #203."
```

---

## Task 2 — Migrate `dark-factory` and `backlog-scheduler` to proxy

**Files:** `docker-compose.yml`

### TDD Steps

**Write failing test** — assert raw socket mounts still exist:
```bash
grep -c "/var/run/docker.sock:/var/run/docker.sock" docker-compose.yml
# Expected: 2  (one per service)
```

**Implement** — Edit `docker-compose.yml` `dark-factory` service:

1. **Remove** the raw socket volume line:
   ```yaml
       - /var/run/docker.sock:/var/run/docker.sock
   ```

2. **Add** `DOCKER_HOST` to the `dark-factory` environment block (create the block if absent):
   ```yaml
       environment:
         DOCKER_HOST: tcp://docker-socket-proxy:2375
   ```

3. **Add** `depends_on` to `dark-factory`:
   ```yaml
       depends_on:
         - docker-socket-proxy
   ```

Repeat for `backlog-scheduler` service:

1. **Remove** the raw socket volume line:
   ```yaml
       - /var/run/docker.sock:/var/run/docker.sock
   ```

2. **Add** `DOCKER_HOST` to the `backlog-scheduler` environment block (it already has `FACTORY_IMAGE` there):
   ```yaml
       environment:
         FACTORY_IMAGE: "ghcr.io/omniscient/markethawk-dark-factory:${IMAGE_TAG:-latest}"
         DOCKER_HOST: tcp://docker-socket-proxy:2375
   ```

3. **Add** `depends_on` to `backlog-scheduler`:
   ```yaml
       depends_on:
         - docker-socket-proxy
   ```

**Verify passing test:**
```bash
# No raw socket mounts remain in either service
grep -c "/var/run/docker.sock:/var/run/docker.sock" docker-compose.yml
# Expected: 1  (only the proxy itself mounts the socket)

# Proxy's own socket mount is read-only
grep "docker-socket-proxy" -A15 docker-compose.yml | grep "docker.sock:ro" && echo "PASS proxy ro" || echo "FAIL"

# DOCKER_HOST present in both consumer services
grep -A20 "dark-factory:" docker-compose.yml | grep "DOCKER_HOST: tcp://docker-socket-proxy" && echo "PASS df" || echo "FAIL df"
grep -A20 "backlog-scheduler:" docker-compose.yml | grep "DOCKER_HOST: tcp://docker-socket-proxy" && echo "PASS bs" || echo "FAIL bs"

# depends_on set on both
grep -A25 "dark-factory:" docker-compose.yml | grep "docker-socket-proxy" && echo "PASS df depends" || echo "FAIL"
grep -A25 "backlog-scheduler:" docker-compose.yml | grep "docker-socket-proxy" && echo "PASS bs depends" || echo "FAIL"

# YAML still valid
docker compose config --quiet && echo "YAML valid"
```

**Commit:**
```bash
git add docker-compose.yml
git commit -m "feat(infra): route dark-factory and backlog-scheduler through socket proxy

Removes /var/run/docker.sock direct mounts from both services.
Sets DOCKER_HOST=tcp://docker-socket-proxy:2375 and depends_on the proxy.
The raw socket is now only accessible through the proxy's allowlist.

Closes part of #203."
```

---

## Task 3 — Add non-root `appuser` to `backend/Dockerfile`

**Files:** `backend/Dockerfile`

### TDD Steps

**Write failing test** — assert USER directive absent:
```bash
grep -q "USER appuser" backend/Dockerfile && echo "ALREADY PRESENT" || echo "ABSENT — expected"
# Expected: ABSENT — expected
```

**Implement** — Edit `backend/Dockerfile`. The current file ends with:
```dockerfile
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

Replace the `COPY . .` + `EXPOSE` + `CMD` section with:
```dockerfile
RUN addgroup --system --gid 1000 appuser \
 && adduser --system --uid 1000 --ingroup appuser --no-create-home appuser

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

The full updated `backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

RUN addgroup --system --gid 1000 appuser \
 && adduser --system --uid 1000 --ingroup appuser --no-create-home appuser

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

**Verify passing test:**
```bash
grep -q "USER appuser" backend/Dockerfile && echo "PASS" || echo "FAIL"
grep -q "addgroup.*appuser" backend/Dockerfile && echo "PASS addgroup" || echo "FAIL"
grep -q "COPY --chown=appuser:appuser" backend/Dockerfile && echo "PASS chown" || echo "FAIL"

# Build the image to confirm no syntax errors (use --no-cache to get a clean result):
docker build -t mh-backend-test backend/ --quiet && echo "BUILD PASS" || echo "BUILD FAIL"

# Verify the running user:
docker run --rm --entrypoint="" mh-backend-test id
# Expected output contains: uid=1000

docker image rm mh-backend-test 2>/dev/null || true
```

**Commit:**
```bash
git add backend/Dockerfile
git commit -m "feat(security): run backend container as non-root appuser (UID 1000)

Adds appuser (uid/gid 1000) via addgroup/adduser and switches USER.
All celery-worker and celery-beat services inherit this change.
Alembic migrations run in a separate migrate step and are not affected.

Closes part of #203."
```

---

## Task 4 — Add `USER node` to `frontend/Dockerfile`

**Files:** `frontend/Dockerfile`

### TDD Steps

**Write failing test** — assert USER directive absent:
```bash
grep -q "USER node" frontend/Dockerfile && echo "ALREADY PRESENT" || echo "ABSENT — expected"
# Expected: ABSENT — expected
```

**Implement** — The `node:22-alpine` base image already ships a `node` user (UID 1000). The current file:
```dockerfile
FROM node:22-alpine

WORKDIR /app

COPY package*.json ./

RUN npm install

COPY . .

RUN npm run build

EXPOSE 3333

CMD ["npm", "run", "dev", "--", "--host"]
```

Add `chown` and `USER node` after `RUN npm run build`:
```dockerfile
FROM node:22-alpine

WORKDIR /app

COPY package*.json ./

RUN npm install

COPY . .

RUN npm run build

RUN chown -R node:node /app

USER node

EXPOSE 3333

CMD ["npm", "run", "dev", "--", "--host"]
```

**Verify passing test:**
```bash
grep -q "USER node" frontend/Dockerfile && echo "PASS" || echo "FAIL"
grep -q "chown -R node:node /app" frontend/Dockerfile && echo "PASS chown" || echo "FAIL"

# Build (skipping the dev CMD — just verify image builds):
docker build -t mh-frontend-test frontend/ --quiet && echo "BUILD PASS" || echo "BUILD FAIL"

# Verify running user:
docker run --rm --entrypoint="" mh-frontend-test id
# Expected: uid=1000(node)

docker image rm mh-frontend-test 2>/dev/null || true
```

**Commit:**
```bash
git add frontend/Dockerfile
git commit -m "feat(security): run frontend container as non-root node user (UID 1000)

node:22-alpine ships a 'node' user at UID 1000. Adds chown of /app and
USER node directive. Port 3333 is non-privileged; no capabilities needed.

Closes part of #203."
```

---

## Task 5 — Relocate Bun to `/opt/bun` in `dark-factory/Dockerfile`

**Files:** `dark-factory/Dockerfile`

This is a prerequisite for Task 6 (non-root factory user). Bun's default install writes to `$HOME/.bun`; moving it to `/opt/bun` makes it accessible to any user, including `factory` (UID 1000).

### TDD Steps

**Write failing test** — assert Bun still installs to root home:
```bash
grep -q 'BUN_INSTALL=/opt/bun' dark-factory/Dockerfile && echo "ALREADY RELOCATED" || echo "NOT RELOCATED — expected"
grep -q '/root/.bun' dark-factory/Dockerfile && echo "ROOT PATH EXISTS — expected" || echo "ABSENT"
# Expected: NOT RELOCATED — expected
# Expected: ROOT PATH EXISTS — expected
```

**Implement** — Replace the Bun install section in `dark-factory/Dockerfile`.

Current lines (approximately line 41–42):
```dockerfile
# Bun
RUN curl -fsSL https://bun.sh/install | bash
ENV PATH="/root/.bun/bin:${PATH}"
```

Replace with:
```dockerfile
# Bun — install to /opt/bun so it is accessible to non-root users
RUN BUN_INSTALL=/opt/bun curl -fsSL https://bun.sh/install | bash
ENV PATH="/opt/bun/bin:${PATH}"
```

After this change, also update the Archon `bun link` command. The existing line:
```dockerfile
    cd /opt/archon/packages/cli && bun link
```
…uses the `bun` already on PATH, so it will resolve to `/opt/bun/bin/bun` automatically. No change required there.

**Verify passing test:**
```bash
grep -q 'BUN_INSTALL=/opt/bun' dark-factory/Dockerfile && echo "PASS" || echo "FAIL"
grep -q '"/opt/bun/bin:' dark-factory/Dockerfile && echo "PASS PATH" || echo "FAIL"
grep -v "^#" dark-factory/Dockerfile | grep -q '/root/.bun' && echo "FAIL — root path remains" || echo "PASS — no root bun path"

# Build and verify bun is at /opt/bun:
docker build -t mh-factory-test dark-factory/ -f dark-factory/Dockerfile . --quiet && echo "BUILD PASS" || echo "BUILD FAIL"
docker run --rm --entrypoint="" mh-factory-test ls /opt/bun/bin/bun && echo "PASS bun at /opt/bun" || echo "FAIL"
docker image rm mh-factory-test 2>/dev/null || true
```

> **Note:** If `BUN_INSTALL=/opt/bun` is not honored by the install script (unlikely but documented as an open question in the spec), fall back to:
> ```dockerfile
> RUN curl -fsSL https://bun.sh/install | bash && mv /root/.bun /opt/bun
> ENV PATH="/opt/bun/bin:${PATH}"
> ```

**Commit:**
```bash
git add dark-factory/Dockerfile
git commit -m "feat(security): relocate Bun install from /root/.bun to /opt/bun

Sets BUN_INSTALL=/opt/bun before the install script so Bun is globally
accessible regardless of the running user. Required prep for adding a
non-root factory user in the next step.

Closes part of #203."
```

---

## Task 6 — Add `factory` user (UID 1000) to `dark-factory/Dockerfile`

**Files:** `dark-factory/Dockerfile`

### TDD Steps

**Write failing test** — assert factory user and USER directive absent:
```bash
grep -q "USER factory" dark-factory/Dockerfile && echo "ALREADY PRESENT" || echo "ABSENT — expected"
grep -q "factory" dark-factory/Dockerfile && echo "SOME FACTORY REF EXISTS" || echo "NO FACTORY USER — expected"
# Expected second line: NO FACTORY USER — expected
```

**Implement** — At the end of `dark-factory/Dockerfile`, after the final `RUN chmod` line and before `WORKDIR /workspace`, add the user creation and ownership fix:

Current tail of `dark-factory/Dockerfile`:
```dockerfile
RUN chmod +x /usr/local/bin/entrypoint.sh /opt/dark-factory/scheduler.sh

WORKDIR /workspace

ENTRYPOINT ["entrypoint.sh"]
```

Replace with:
```dockerfile
RUN chmod +x /usr/local/bin/entrypoint.sh /opt/dark-factory/scheduler.sh

# Non-root factory user — must be created AFTER all root-level installs
RUN groupadd --gid 1000 factory && \
    useradd --uid 1000 --gid 1000 --create-home --home-dir /home/factory factory

# Transfer workspace ownership to the factory user
RUN chown -R factory:factory /workspace

# Re-link archon CLI as root so it is in the global scope, then verify factory can call it
RUN cd /opt/archon/packages/cli && /opt/bun/bin/bun link

USER factory
WORKDIR /workspace

ENTRYPOINT ["entrypoint.sh"]
```

**Verify passing test:**
```bash
grep -q "USER factory" dark-factory/Dockerfile && echo "PASS USER" || echo "FAIL"
grep -q "useradd.*--uid 1000.*factory" dark-factory/Dockerfile && echo "PASS useradd" || echo "FAIL"
grep -q "chown -R factory:factory /workspace" dark-factory/Dockerfile && echo "PASS chown" || echo "FAIL"

# Build image:
docker build -t mh-factory-test dark-factory/ -f dark-factory/Dockerfile . --quiet && echo "BUILD PASS" || echo "BUILD FAIL"

# Verify running user is factory (UID 1000):
docker run --rm --entrypoint="" mh-factory-test id
# Expected: uid=1000(factory)

# Verify bun is accessible as factory user:
docker run --rm --entrypoint="" mh-factory-test bun --version
# Expected: a version string like 1.x.x

# Verify archon CLI is accessible as factory user:
docker run --rm --entrypoint="" mh-factory-test archon --version 2>&1 | head -2
# Expected: archon version output (not "command not found")

docker image rm mh-factory-test 2>/dev/null || true
```

**Commit:**
```bash
git add dark-factory/Dockerfile
git commit -m "feat(security): run dark-factory as non-root 'factory' user (UID 1000)

Creates factory user (uid/gid 1000) with home /home/factory after all
root-level installs. Transfers /workspace ownership. USER factory ensures
Claude Code runs non-root (--dangerously-skip-permissions requires it).
Bun was pre-relocated to /opt/bun in the previous commit.

Closes part of #203."
```

---

## Task 7 — Fix hardcoded `/root/` path in `entrypoint.sh`

**Files:** `dark-factory/entrypoint.sh`

### TDD Steps

**Write failing test** — assert hardcoded `/root/` path exists:
```bash
grep -n 'DECONFLICT_ARTIFACTS_DIR="/root/' dark-factory/entrypoint.sh
# Expected: line 585 with the hardcoded path
```

**Implement** — Edit line 585 of `dark-factory/entrypoint.sh`.

Current (line 585):
```bash
  DECONFLICT_ARTIFACTS_DIR="/root/.archon/workspaces/omniscient/markethawk/artifacts"
```

Replace with:
```bash
  DECONFLICT_ARTIFACTS_DIR="${HOME}/.archon/workspaces/omniscient/markethawk/artifacts"
```

**Verify passing test:**
```bash
# Old hardcoded path is gone:
grep -c 'DECONFLICT_ARTIFACTS_DIR="/root/' dark-factory/entrypoint.sh
# Expected: 0

# New HOME-relative path is present:
grep -q 'DECONFLICT_ARTIFACTS_DIR="${HOME}/' dark-factory/entrypoint.sh && echo "PASS" || echo "FAIL"

# Verify no other /root/ paths remain in entrypoint.sh:
grep -n '/root/' dark-factory/entrypoint.sh && echo "REVIEW REMAINING PATHS" || echo "PASS — no /root/ paths"
```

**Run existing scheduler tests to confirm no regressions:**
```bash
bash dark-factory/tests/test_scheduler.sh 2>&1 | tail -5
# Expected: all tests PASS, exit 0
```

**Commit:**
```bash
git add dark-factory/entrypoint.sh
git commit -m "fix(entrypoint): replace hardcoded /root/ path with \${HOME} in deconflict step

DECONFLICT_ARTIFACTS_DIR used a hardcoded /root/.archon path that is
unreachable when the container runs as factory (UID 1000, HOME=/home/factory).
Replacing with \${HOME} makes it resolve correctly for any user.

Closes part of #203."
```

---

## Task 8 — Update ADR-0008 to present-tense and add residual-risk section

**Files:** `docs/adr/0008-dark-factory-autonomous-development.md`

### TDD Steps

**Write failing test** — assert ADR still has old status:
```bash
grep -q "^\\*\\*Status\\*\\*: Accepted$" docs/adr/0008-dark-factory-autonomous-development.md && echo "OLD STATUS — expected" || echo "UPDATED"
# Expected: OLD STATUS — expected
```

**Implement** — Make the following four edits to `docs/adr/0008-dark-factory-autonomous-development.md`:

**Edit 1:** Change the Status line from:
```markdown
**Status**: Accepted
```
to:
```markdown
**Status**: Accepted (updated 2026-06-05 — socket proxy implemented, factory user added)
```

**Edit 2:** In the **Context / Trust model** paragraph, change aspirational language to present-tense:

Old text (in the `### Trust model` subsection):
```markdown
The Dark Factory uses `tecnativa/docker-socket-proxy` to restrict the Docker API surface. The proxy allows `CONTAINERS`, `IMAGES`, `NETWORKS`, `VOLUMES`, and `BUILD`, while blocking `SERVICES`, `EXEC`, and write access to `/info` endpoints. The factory container has no bind-mount to the host filesystem — it clones fresh from GitHub each run.
```
New text:
```markdown
The Dark Factory routes Docker API calls through a `tecnativa/docker-socket-proxy` sidecar. The proxy allowlist is `CONTAINERS=1, IMAGES=1, NETWORKS=1, VOLUMES=1, BUILD=1, POST=1`; it blocks `SERVICES=0, EXEC=0, AUTH=0, SECRETS=0`. The raw socket is mounted read-only on the proxy only (`/var/run/docker.sock:ro`); `dark-factory` and `backlog-scheduler` connect via `DOCKER_HOST=tcp://docker-socket-proxy:2375`. The factory container has no bind-mount to the host filesystem — it clones fresh from GitHub each run.
```

**Edit 3:** In the **Decision** section, change:
```markdown
Claude Code runs inside the factory as a non-root user (`factory`, UID 1000). `--dangerously-skip-permissions` is required and is a built-in safety check that fails if run as root.
```
to (confirm present-tense enforcement):
```markdown
Claude Code runs inside the factory as a non-root user (`factory`, UID 1000) — enforced via `USER factory` in `dark-factory/Dockerfile`. `--dangerously-skip-permissions` is required and is a built-in safety check that fails if run as root.
```

**Edit 4:** Add a **Residual Risk Acceptance** subsection under **Consequences**. At the end of the Consequences section append:

```markdown
### Residual Risk Acceptance (2026-06-05)

`tecnativa/docker-socket-proxy` does not support label-based container filtering. With `POST=1, CONTAINERS=1`, the factory can create or list any container on the host, not only `mh-preview-*` stacks. This risk is accepted: the factory is a trusted first-party tool run by the repo owner, not an adversarial workload. The entrypoint and Archon workflows operate on `mh-preview-*` resources by convention. A custom proxy with namespace-enforcement would require writing and maintaining a bespoke API gateway — cost not justified at this scale. Reviewed and accepted: issue #203.
```

**Verify passing test:**
```bash
grep -q "updated 2026-06-05" docs/adr/0008-dark-factory-autonomous-development.md && echo "PASS status" || echo "FAIL"
grep -q "DOCKER_HOST=tcp://docker-socket-proxy" docs/adr/0008-dark-factory-autonomous-development.md && echo "PASS present-tense" || echo "FAIL"
grep -q "USER factory.*Dockerfile" docs/adr/0008-dark-factory-autonomous-development.md && echo "PASS factory user" || echo "FAIL"
grep -q "Residual Risk Acceptance" docs/adr/0008-dark-factory-autonomous-development.md && echo "PASS residual risk" || echo "FAIL"
grep -q "issue #203" docs/adr/0008-dark-factory-autonomous-development.md && echo "PASS ref" || echo "FAIL"
```

**Commit:**
```bash
git add docs/adr/0008-dark-factory-autonomous-development.md
git commit -m "docs(adr): update ADR-0008 — proxy implemented, factory user enforced, residual risk accepted

Updates status to reflect socket proxy and non-root user are now implemented
(not just intended). Replaces aspirational language with present-tense
description of the proxy allowlist and DOCKER_HOST routing. Adds formal
Residual Risk Acceptance for container enumeration scope limitation.
Reference: issue #203."
```

---

## Summary

| Task | Files | Commit |
|------|-------|--------|
| 1. Add socket proxy service | `docker-compose.yml` | `feat(infra): add docker-socket-proxy sidecar` |
| 2. Migrate consumers to proxy | `docker-compose.yml` | `feat(infra): route dark-factory and backlog-scheduler through proxy` |
| 3. Backend non-root user | `backend/Dockerfile` | `feat(security): run backend as appuser (UID 1000)` |
| 4. Frontend non-root user | `frontend/Dockerfile` | `feat(security): run frontend as node user (UID 1000)` |
| 5. Relocate Bun to /opt/bun | `dark-factory/Dockerfile` | `feat(security): relocate Bun to /opt/bun` |
| 6. Factory non-root user | `dark-factory/Dockerfile` | `feat(security): run dark-factory as factory user (UID 1000)` |
| 7. Fix entrypoint.sh path | `dark-factory/entrypoint.sh` | `fix(entrypoint): replace hardcoded /root/ with ${HOME}` |
| 8. Update ADR-0008 | `docs/adr/0008-*.md` | `docs(adr): update ADR-0008 with present-tense and residual risk` |

**Total: 8 tasks, 32 steps**
