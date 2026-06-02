# Docker Compose Dev/Live Split -- Implementation Plan

**Goal:** Remove source bind-mounts from the base docker-compose.yml so the live stack runs baked images, while restoring them in docker-compose.override.yml for local dev hot-reload.
**Issue:** [#146](https://github.com/omniscient/markethawk/issues/146)
**Spec:** [2026-06-01-docker-compose-dev-live-split-design.md](../specs/2026-06-01-docker-compose-dev-live-split-design.md)

## Architecture

Docker Compose's built-in override mechanism is the only new mechanism introduced. When `docker-compose up -d` runs in a directory containing both `docker-compose.yml` and `docker-compose.override.yml`, Compose automatically merges them — the override file wins on any key that conflicts. The base file becomes the stable, baked-image definition used by CI, preview stacks, and the live trading stack. The committed override file restores bind-mounts and dev-server commands for local development. No wrapper scripts, Makefile targets, or aliases are introduced.

The frontend image gains a production serving capability (`npx vite preview`) by adding `RUN npm run build` to its Dockerfile before the existing `CMD`. This means the built `dist/` directory is always available inside the image, so `npx vite preview --host --port 3333` works without a host mount. The override command replaces this with `npm run dev` and restores the bind-mount, exactly as today.

The dark-factory/backlog-scheduler path is decoupled from the host working tree: `scheduler.sh` currently calls `docker compose -f /workspace/project/docker-compose.yml`, which relies on the repo being bind-mounted into the container. After this change the compose file is baked into the image at `/opt/dark-factory/docker-compose.yml` and the path in `scheduler.sh` is updated to match.

## Tech Stack

- Docker Compose (override merge, no new tooling)
- Vite (production preview server via `npx vite preview`)
- Bash (scheduler.sh path update)
- YAML (docker-compose.yml, docker-compose.override.yml)

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `frontend/Dockerfile` | Modify | Add `RUN npm run build` to bake `dist/` for production serving; update `EXPOSE` to 3333 |
| `dark-factory/scheduler.sh` | Modify | Update `dispatch()` path from `/workspace/project/docker-compose.yml` to `/opt/dark-factory/docker-compose.yml` |
| `dark-factory/Dockerfile` | Modify | Add `COPY docker-compose.yml /opt/dark-factory/docker-compose.yml` to bake the compose file |
| `docker-compose.yml` | Modify | Remove source bind-mounts from six services; add stable commands; add inline comments |
| `docker-compose.override.yml` | Create | Restore bind-mounts and dev commands for all six affected services; declare named volume stub |
| `CLAUDE.md` | Modify | Add dev/live split note to Docker commands section and dark factory note |
| `DEVELOPMENT.md` | Modify | Add "Dev vs. live stack isolation" subsection after the Docker Commands block |

---

## Task 1: Resolve frontend production serving

**Files:** `frontend/Dockerfile`

The frontend Dockerfile currently has `CMD ["npm", "run", "dev", "--", "--host"]` as its only runtime instruction. The base compose needs a stable command (`npx vite preview --host --port 3333`) that serves the pre-built `dist/` directory. Without `RUN npm run build` in the Dockerfile, no `dist/` exists inside the image and `vite preview` would fail. The Dockerfile CMD is left unchanged; the base compose overrides it via the `command:` key, and the override file overrides it back to the dev server.

`EXPOSE` is updated from 3000 to 3333 to reflect the port the production-serving mode actually binds. `EXPOSE` is metadata-only and does not block any port, but 3333 is more accurate given the base compose's `command: npx vite preview --host --port 3333`.

**Current `frontend/Dockerfile`:**
```dockerfile
FROM node:22-alpine

WORKDIR /app

COPY package*.json ./

RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host"]
```

### Steps

**Step 1a:** Add `RUN npm run build` immediately before the `CMD` line and update `EXPOSE 3000` to `EXPOSE 3333`.

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

**Step 1b:** Verify the frontend image builds successfully (no build errors).

```bash
docker compose build frontend
```

Expected: Build completes with exit code 0 and the final layer includes the `dist/` directory. No `npm run dev` is executed during build.

**Commit:**
```bash
git add frontend/Dockerfile
git commit -m "build(frontend): add npm run build to Dockerfile for production image serving

Bakes dist/ into the image so that the base docker-compose.yml can serve
the frontend with 'npx vite preview' without requiring a host bind-mount.
Updates EXPOSE from 3000 to 3333 to match the production-serving port.
The dev override restores the bind-mount and npm run dev command."
```

---

## Task 2: Update scheduler.sh baked path

**Files:** `dark-factory/scheduler.sh`

The `dispatch()` function at line 140 currently uses `/workspace/project/docker-compose.yml`, which points to the bind-mounted repo checkout inside the container. After this change, the compose file is baked into the image at `/opt/dark-factory/docker-compose.yml` (Task 3), so the scheduler must reference that baked path. This makes the scheduler independent of any host bind-mount.

**Current line 140 (inside `dispatch()`):**
```bash
  docker compose -f /workspace/project/docker-compose.yml --profile factory run -d --rm dark-factory "$command"
```

### Steps

**Step 2a:** Change the path in `dispatch()` from `/workspace/project/docker-compose.yml` to `/opt/dark-factory/docker-compose.yml`.

The full updated `dispatch()` function (lines 137–141):

```bash
# --- Dispatch ---
dispatch() {
  local command="$1"
  echo "Dispatching: $command"
  docker compose -f /opt/dark-factory/docker-compose.yml --profile factory run -d --rm dark-factory "$command"
}
```

**Step 2b:** Verify the change is correct and no other references to the old path remain. Use an absolute path for the grep to ensure it works regardless of current working directory.

```bash
grep -n "docker-compose.yml" /workspace/markethawk/dark-factory/scheduler.sh
```

Expected output (only one match, showing the new path):
```
140:  docker compose -f /opt/dark-factory/docker-compose.yml --profile factory run -d --rm dark-factory "$command"
```

**Commit:**
```bash
git add dark-factory/scheduler.sh
git commit -m "fix(scheduler): use baked /opt/dark-factory/docker-compose.yml path

The scheduler runs inside the dark-factory image and previously relied on
the repo being bind-mounted at /workspace/project. The compose file will
now be baked into the image (see dark-factory/Dockerfile), so update the
dispatch() path to the baked location."
```

---

## Task 3: Update dark-factory/Dockerfile to bake docker-compose.yml

**Files:** `dark-factory/Dockerfile`

The scheduler (Task 2) now expects `docker-compose.yml` at `/opt/dark-factory/docker-compose.yml` inside the image. This task bakes it there. The `COPY` is placed alongside the other baked files in `/opt/dark-factory/`, before the `COPY dark-factory/entrypoint.sh` line, keeping baked assets grouped together.

**Current relevant lines in `dark-factory/Dockerfile` (lines 68–73):**
```dockerfile
# Copy entrypoint, scheduler, preview template, and seed data
COPY dark-factory/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY dark-factory/scheduler.sh /opt/dark-factory/scheduler.sh
COPY dark-factory/docker-compose.preview.yml /opt/dark-factory/docker-compose.preview.yml
COPY dark-factory/seed/ /opt/dark-factory/seed/
COPY .claude/skills/refinement/ /opt/refinement-skills/
RUN chmod +x /usr/local/bin/entrypoint.sh /opt/dark-factory/scheduler.sh
```

### Steps

**Step 3a:** Add `COPY docker-compose.yml /opt/dark-factory/docker-compose.yml` into the existing COPY block, immediately before the `COPY dark-factory/entrypoint.sh` line.

The updated block:

```dockerfile
# Copy entrypoint, scheduler, preview template, seed data, and base compose file
COPY dark-factory/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY dark-factory/scheduler.sh /opt/dark-factory/scheduler.sh
COPY dark-factory/docker-compose.preview.yml /opt/dark-factory/docker-compose.preview.yml
COPY dark-factory/seed/ /opt/dark-factory/seed/
COPY docker-compose.yml /opt/dark-factory/docker-compose.yml
COPY .claude/skills/refinement/ /opt/refinement-skills/
RUN chmod +x /usr/local/bin/entrypoint.sh /opt/dark-factory/scheduler.sh
```

**Step 3b:** Verify the COPY instruction is present. Use an absolute path for the grep.

```bash
grep -n "docker-compose.yml" /workspace/markethawk/dark-factory/Dockerfile
```

Expected output (one match):
```
72:COPY docker-compose.yml /opt/dark-factory/docker-compose.yml
```

(Line number may vary slightly depending on surrounding context.)

**Commit:**
```bash
git add dark-factory/Dockerfile
git commit -m "build(dark-factory): bake docker-compose.yml into image at /opt/dark-factory/

The scheduler references /opt/dark-factory/docker-compose.yml to spawn
factory runs; baking the file removes the dependency on the host repo
bind-mount that is eliminated by the dev/live split."
```

---

## Task 4: Modify docker-compose.yml to remove bind-mounts from six services

**Files:** `docker-compose.yml`

This is the core change. Each of the six source-serving services loses its source bind-mount and gains (where needed) an explicit stable command. An inline comment is added above each service's `volumes:` block (or `command:` key for services where the command changes) pointing implementors to the override file.

### Steps

**Step 4a: backend** — Remove `./backend:/app:ro` from volumes; add explicit `command:`; add inline comment.

Replace the `backend` service block. Before (lines 86–134):

```yaml
  # Backend API
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: stockscanner-api
    environment:
      DATABASE_URL: ${DATABASE_URL}
      POLYGON_API_KEY: ${POLYGON_API_KEY:-}
      REDIS_URL: redis://redis:6379/0
      ENVIRONMENT: ${ENVIRONMENT:-development}
      SEQ_URL: http://seq:5341
      WATCHFILES_FORCE_POLLING: "true"
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      IBKR_HOST: ib-gateway
      IBKR_PORT: 4004
      IBKR_CLIENT_ID: ${IBKR_CLIENT_ID:-10}
      PYTHONDONTWRITEBYTECODE: "1"
      # Alerting & Push Notifications
      VAPID_PRIVATE_KEY: ${VAPID_PRIVATE_KEY}
      VAPID_PUBLIC_KEY: ${VAPID_PUBLIC_KEY}
      VAPID_CLAIMS_EMAIL: ${VAPID_CLAIMS_EMAIL}
      SMTP_HOST: ${SMTP_HOST}
      SMTP_PORT: ${SMTP_PORT}
      SMTP_USER: ${SMTP_USER}
      SMTP_PASSWORD: ${SMTP_PASSWORD}
      SMTP_FROM_EMAIL: ${SMTP_FROM_EMAIL}
      PROMETHEUS_MULTIPROC_DIR: /tmp/prometheus_multiproc
      OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4317
      OTEL_SERVICE_NAME: markethawk-backend
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      ib-gateway:
        condition: service_started
    volumes:
      - ./backend:/app:ro
      - prometheus_multiproc:/tmp/prometheus_multiproc
    networks:
      - stockscanner-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '1.0'
```

After:

```yaml
  # Backend API
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: stockscanner-api
    # Bind-mount (./backend:/app:ro) and --reload are restored in docker-compose.override.yml for local dev.
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    environment:
      DATABASE_URL: ${DATABASE_URL}
      POLYGON_API_KEY: ${POLYGON_API_KEY:-}
      REDIS_URL: redis://redis:6379/0
      ENVIRONMENT: ${ENVIRONMENT:-development}
      SEQ_URL: http://seq:5341
      WATCHFILES_FORCE_POLLING: "true"
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      IBKR_HOST: ib-gateway
      IBKR_PORT: 4004
      IBKR_CLIENT_ID: ${IBKR_CLIENT_ID:-10}
      PYTHONDONTWRITEBYTECODE: "1"
      # Alerting & Push Notifications
      VAPID_PRIVATE_KEY: ${VAPID_PRIVATE_KEY}
      VAPID_PUBLIC_KEY: ${VAPID_PUBLIC_KEY}
      VAPID_CLAIMS_EMAIL: ${VAPID_CLAIMS_EMAIL}
      SMTP_HOST: ${SMTP_HOST}
      SMTP_PORT: ${SMTP_PORT}
      SMTP_USER: ${SMTP_USER}
      SMTP_PASSWORD: ${SMTP_PASSWORD}
      SMTP_FROM_EMAIL: ${SMTP_FROM_EMAIL}
      PROMETHEUS_MULTIPROC_DIR: /tmp/prometheus_multiproc
      OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4317
      OTEL_SERVICE_NAME: markethawk-backend
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      ib-gateway:
        condition: service_started
    volumes:
      - prometheus_multiproc:/tmp/prometheus_multiproc
    networks:
      - stockscanner-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '1.0'
```

**Step 4b: frontend** — Remove `./frontend:/app` and `/app/node_modules` from volumes; add explicit `command:`; add inline comment.

Before (lines 136–152):

```yaml
  # Frontend
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: stockscanner-frontend
    ports:
      - "3333:3333"
    environment:
      REACT_APP_API_URL: http://localhost:8000
      VITE_API_TARGET: http://backend:8000
    volumes:
      - ./frontend:/app
      - /app/node_modules
    networks:
      - stockscanner-network
    restart: unless-stopped
```

After:

```yaml
  # Frontend
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: stockscanner-frontend
    # Bind-mounts (./frontend:/app, /app/node_modules) and npm run dev are restored in docker-compose.override.yml for local dev.
    command: npx vite preview --host --port 3333
    ports:
      - "3333:3333"
    environment:
      REACT_APP_API_URL: http://localhost:8000
      VITE_API_TARGET: http://backend:8000
    networks:
      - stockscanner-network
    restart: unless-stopped
```

**Step 4c: celery-worker** — Remove `./backend:/app:ro` from volumes; change command to plain celery (no watchfiles); add inline comment.

Before (lines 154–202):

```yaml
  # Celery for background tasks
  celery-worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: stockscanner-celery
    command: python -m watchfiles --filter python 'celery -A app.core.celery_app:celery_app worker --loglevel=info' /app/app
    environment:
      DATABASE_URL: ${DATABASE_URL}
      POLYGON_API_KEY: ${POLYGON_API_KEY:-}
      REDIS_URL: redis://redis:6379/0
      ENVIRONMENT: ${ENVIRONMENT:-development}
      SEQ_URL: http://seq:5341
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      WATCHFILES_FORCE_POLLING: "true"
      IBKR_HOST: ib-gateway
      IBKR_PORT: 4004
      IBKR_CLIENT_ID: ${IBKR_CLIENT_ID:-10}
      PYTHONDONTWRITEBYTECODE: "1"
      # Alerting & Push Notifications
      VAPID_PRIVATE_KEY: ${VAPID_PRIVATE_KEY}
      VAPID_PUBLIC_KEY: ${VAPID_PUBLIC_KEY}
      VAPID_CLAIMS_EMAIL: ${VAPID_CLAIMS_EMAIL}
      SMTP_HOST: ${SMTP_HOST}
      SMTP_PORT: ${SMTP_PORT}
      SMTP_USER: ${SMTP_USER}
      SMTP_PASSWORD: ${SMTP_PASSWORD}
      SMTP_FROM_EMAIL: ${SMTP_FROM_EMAIL}
      PROMETHEUS_MULTIPROC_DIR: /tmp/prometheus_multiproc
      OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4317
      OTEL_SERVICE_NAME: markethawk-worker
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      ib-gateway:
        condition: service_started
    volumes:
      - ./backend:/app:ro
      - prometheus_multiproc:/tmp/prometheus_multiproc
    networks:
      - stockscanner-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '2.0'
```

After:

```yaml
  # Celery for background tasks
  celery-worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: stockscanner-celery
    # Bind-mount (./backend:/app:ro) and watchfiles hot-reload are restored in docker-compose.override.yml for local dev.
    command: celery -A app.core.celery_app:celery_app worker --loglevel=info
    environment:
      DATABASE_URL: ${DATABASE_URL}
      POLYGON_API_KEY: ${POLYGON_API_KEY:-}
      REDIS_URL: redis://redis:6379/0
      ENVIRONMENT: ${ENVIRONMENT:-development}
      SEQ_URL: http://seq:5341
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      WATCHFILES_FORCE_POLLING: "true"
      IBKR_HOST: ib-gateway
      IBKR_PORT: 4004
      IBKR_CLIENT_ID: ${IBKR_CLIENT_ID:-10}
      PYTHONDONTWRITEBYTECODE: "1"
      # Alerting & Push Notifications
      VAPID_PRIVATE_KEY: ${VAPID_PRIVATE_KEY}
      VAPID_PUBLIC_KEY: ${VAPID_PUBLIC_KEY}
      VAPID_CLAIMS_EMAIL: ${VAPID_CLAIMS_EMAIL}
      SMTP_HOST: ${SMTP_HOST}
      SMTP_PORT: ${SMTP_PORT}
      SMTP_USER: ${SMTP_USER}
      SMTP_PASSWORD: ${SMTP_PASSWORD}
      SMTP_FROM_EMAIL: ${SMTP_FROM_EMAIL}
      PROMETHEUS_MULTIPROC_DIR: /tmp/prometheus_multiproc
      OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4317
      OTEL_SERVICE_NAME: markethawk-worker
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      ib-gateway:
        condition: service_started
    volumes:
      - prometheus_multiproc:/tmp/prometheus_multiproc
    networks:
      - stockscanner-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '2.0'
```

**Step 4d: live-scanner** — Remove `./backend:/app:ro` from volumes; add inline comment. Command is unchanged (`python -m live_scanner.main`).

Before (lines 204–237):

```yaml
  # Live Scanner — streams real-time IBKR bars for watchlist symbols
  live-scanner:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: stockscanner-live
    command: python -m live_scanner.main
    environment:
      DATABASE_URL: ${DATABASE_URL}
      POLYGON_API_KEY: ${POLYGON_API_KEY:-}
      REDIS_URL: redis://redis:6379/0
      ENVIRONMENT: ${ENVIRONMENT:-development}
      SEQ_URL: http://seq:5341
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      IBKR_HOST: ib-gateway
      IBKR_PORT: 4004
      IBKR_CLIENT_ID: 5   # dedicated clientId — never shares with backend or Celery
      PYTHONDONTWRITEBYTECODE: "1"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      ib-gateway:
        condition: service_started
    volumes:
      - ./backend:/app:ro
    networks:
      - stockscanner-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M
```

After:

```yaml
  # Live Scanner — streams real-time IBKR bars for watchlist symbols
  live-scanner:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: stockscanner-live
    command: python -m live_scanner.main
    environment:
      DATABASE_URL: ${DATABASE_URL}
      POLYGON_API_KEY: ${POLYGON_API_KEY:-}
      REDIS_URL: redis://redis:6379/0
      ENVIRONMENT: ${ENVIRONMENT:-development}
      SEQ_URL: http://seq:5341
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      IBKR_HOST: ib-gateway
      IBKR_PORT: 4004
      IBKR_CLIENT_ID: 5   # dedicated clientId — never shares with backend or Celery
      PYTHONDONTWRITEBYTECODE: "1"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      ib-gateway:
        condition: service_started
    # Bind-mount (./backend:/app:ro) is restored in docker-compose.override.yml for local dev.
    volumes: []
    networks:
      - stockscanner-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M
```

Note: `volumes: []` is valid YAML and is handled correctly by Compose v2. Verify `docker-compose -f docker-compose.yml config` parses without warnings on the target environment after this step.

**Step 4e: celery-beat** — Remove `./backend:/app:ro` from volumes; add inline comment. Command is unchanged.

Before (lines 239–269):

```yaml
  # Celery Beat for reliable scheduling
  celery-beat:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: stockscanner-beat
    command: celery -A app.core.celery_app:celery_app beat --loglevel=info -s /tmp/celerybeat-schedule
    environment:
      DATABASE_URL: ${DATABASE_URL}
      POLYGON_API_KEY: ${POLYGON_API_KEY:-}
      REDIS_URL: redis://redis:6379/0
      ENVIRONMENT: ${ENVIRONMENT:-development}
      SEQ_URL: http://seq:5341
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      PYTHONDONTWRITEBYTECODE: "1"
      OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4317
      OTEL_SERVICE_NAME: markethawk-beat
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./backend:/app:ro
    networks:
      - stockscanner-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 256M
```

After:

```yaml
  # Celery Beat for reliable scheduling
  celery-beat:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: stockscanner-beat
    command: celery -A app.core.celery_app:celery_app beat --loglevel=info -s /tmp/celerybeat-schedule
    environment:
      DATABASE_URL: ${DATABASE_URL}
      POLYGON_API_KEY: ${POLYGON_API_KEY:-}
      REDIS_URL: redis://redis:6379/0
      ENVIRONMENT: ${ENVIRONMENT:-development}
      SEQ_URL: http://seq:5341
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      PYTHONDONTWRITEBYTECODE: "1"
      OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4317
      OTEL_SERVICE_NAME: markethawk-beat
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    # Bind-mount (./backend:/app:ro) is restored in docker-compose.override.yml for local dev.
    volumes: []
    networks:
      - stockscanner-network
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 256M
```

Note: `volumes: []` is valid YAML and is handled correctly by Compose v2. Verify `docker-compose -f docker-compose.yml config` parses without warnings on the target environment after this step.

**Step 4f: backlog-scheduler** — Remove `.:/workspace/project:ro` from volumes; add inline comment.

Before (lines 419–442):

```yaml
  # Backlog Scheduler — polls GitHub board and dispatches dark factory runs
  backlog-scheduler:
    build:
      context: .
      dockerfile: dark-factory/Dockerfile
    container_name: backlog-scheduler
    restart: unless-stopped
    entrypoint: ["/opt/dark-factory/scheduler.sh"]
    env_file:
      - path: .archon/.env
        required: true
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/workspace/project:ro
    networks:
      - factory-network
      - stockscanner-network
    logging:
      driver: gelf
      options:
        gelf-address: "udp://host.docker.internal:12201"
        tag: "backlog-scheduler"
    profiles:
      - scheduler
```

After:

```yaml
  # Backlog Scheduler — polls GitHub board and dispatches dark factory runs
  backlog-scheduler:
    build:
      context: .
      dockerfile: dark-factory/Dockerfile
    container_name: backlog-scheduler
    restart: unless-stopped
    entrypoint: ["/opt/dark-factory/scheduler.sh"]
    env_file:
      - path: .archon/.env
        required: true
    # Bind-mount (.:/workspace/project:ro) is restored in docker-compose.override.yml for local dev.
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    networks:
      - factory-network
      - stockscanner-network
    logging:
      driver: gelf
      options:
        gelf-address: "udp://host.docker.internal:12201"
        tag: "backlog-scheduler"
    profiles:
      - scheduler
```

**Step 4g: Verify the base compose has no source bind-mounts.**

Note: `docker-compose config` resolves relative source paths to absolute paths (e.g. `./backend` becomes `/workspace/markethawk/backend`). The grep below covers both the relative form (in the raw file) and the resolved absolute form (in config output). Run both commands.

```bash
# Check resolved config output for any remaining source bind-mounts
docker-compose -f /workspace/markethawk/docker-compose.yml config 2>/dev/null | grep "source:" | grep -E "backend|frontend|/workspace/markethawk"
```

Expected: no output (all source bind-mounts removed from base file).

```bash
# Also verify /workspace/project bind-mount (backlog-scheduler) is gone
docker-compose -f /workspace/markethawk/docker-compose.yml config 2>/dev/null | grep "/workspace/project"
```

Expected: no output.

**Commit:**
```bash
git add docker-compose.yml
git commit -m "refactor(compose): remove source bind-mounts from base docker-compose.yml

The six source-serving services (backend, celery-worker, celery-beat,
live-scanner, frontend, backlog-scheduler) now run baked images in the
base file. Stable commands replace hot-reload commands where needed.
Bind-mounts and dev commands are restored in docker-compose.override.yml."
```

---

## Task 5: Create docker-compose.override.yml

**Files:** `docker-compose.override.yml` (new file)

This file is committed to the repo. Docker Compose automatically merges it with `docker-compose.yml` when both files are present, so `docker-compose up -d` in a local dev checkout restores all six bind-mounts and dev-server commands. Services not listed here (flower, forecast-worker, postgres, redis, etc.) are unaffected.

**Important: Docker Compose volume list merge semantics.** When an override service specifies a `volumes:` list, it **replaces** the base service's list entirely — it does not append. This means every named volume that the service needs must be re-declared in the override's `volumes:` list, not just the new bind-mounts. For `backend` and `celery-worker`, the `prometheus_multiproc` named volume must be included alongside the restored bind-mount.

**Important: Named volume declaration in the override file.** Docker Compose requires any named volume referenced in an override file to also be declared in that file's top-level `volumes:` block (even as an empty stub). Without this declaration, `docker-compose up -d` fails with: *"service 'backend' refers to undefined volume prometheus_multiproc"*. The override file therefore includes a `volumes:` block at the bottom declaring `prometheus_multiproc: {}`.

**Note on `celery-worker` command quoting:** the watchfiles command uses a shell-string form with single quotes around the celery invocation. In the override YAML this must be a string value (not a list) so the shell parses the quoted inner command correctly — the same form used in the original `docker-compose.yml`.

**Note on `backlog-scheduler` volumes:** Docker Compose volume list merge semantics mean the override replaces the base list entirely. The base file keeps `- /var/run/docker.sock:/var/run/docker.sock`; the override re-declares both the docker.sock mount and the project bind-mount. Omitting docker.sock from the override would silently remove it from the dev stack, so both mounts are explicitly listed.

### Steps

**Step 5a:** Create `/workspace/markethawk/docker-compose.override.yml` with the following complete content:

```yaml
# docker-compose.override.yml — local development overrides
#
# Docker Compose automatically merges this file with docker-compose.yml when
# both are present (i.e. in a local dev checkout). It restores source bind-mounts
# and hot-reload commands for the six source-serving services so that
# "docker-compose up -d" behaves exactly as before the dev/live split.
#
# To run the stable baked-image stack without this file (live/CI mode):
#   docker-compose -f docker-compose.yml up -d

name: markethawk

services:
  backend:
    volumes:
      - ./backend:/app:ro
      - prometheus_multiproc:/tmp/prometheus_multiproc
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  celery-worker:
    volumes:
      - ./backend:/app:ro
      - prometheus_multiproc:/tmp/prometheus_multiproc
    command: python -m watchfiles --filter python 'celery -A app.core.celery_app:celery_app worker --loglevel=info' /app/app

  celery-beat:
    volumes:
      - ./backend:/app:ro

  live-scanner:
    volumes:
      - ./backend:/app:ro

  frontend:
    volumes:
      - ./frontend:/app
      - /app/node_modules
    command: npm run dev -- --host

  backlog-scheduler:
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/workspace/project:ro

# Named volumes used in service overrides above must be declared here.
# Docker Compose requires named volumes referenced in an override file to
# appear in its own top-level volumes: block (even as an empty stub), otherwise
# "docker-compose up -d" fails with "refers to undefined volume" errors.
volumes:
  prometheus_multiproc: {}
```

**Step 5b:** Verify that with both files present, the merged config shows the dev bind-mounts. Use absolute paths for all commands.

```bash
docker-compose -f /workspace/markethawk/docker-compose.yml -f /workspace/markethawk/docker-compose.override.yml config 2>/dev/null | grep "source:" | grep -E "backend|frontend|/workspace/markethawk$"
```

Expected: lines showing `backend`, `frontend`, and the project root bind-mounts from the override.

```bash
docker-compose -f /workspace/markethawk/docker-compose.yml -f /workspace/markethawk/docker-compose.override.yml config 2>/dev/null | grep "/workspace/project"
```

Expected: one line showing the bind-mount from the override.

**Step 5c:** Verify that without the override file, the base compose shows no source bind-mounts:

```bash
docker-compose -f /workspace/markethawk/docker-compose.yml config 2>/dev/null | grep "source:" | grep -E "backend|frontend|/workspace/markethawk$"
```

Expected: no output.

**Step 5d:** Verify the override file's named volume declaration prevents the "undefined volume" error. The following command must exit 0 with no errors:

```bash
docker-compose -f /workspace/markethawk/docker-compose.yml -f /workspace/markethawk/docker-compose.override.yml config 2>&1 | grep -i "error\|undefined"
```

Expected: no output (no errors about undefined volumes).

**Commit:**
```bash
git add docker-compose.override.yml
git commit -m "feat(compose): add docker-compose.override.yml for local dev bind-mounts

Restores source bind-mounts and hot-reload commands for backend,
celery-worker, celery-beat, live-scanner, frontend, and backlog-scheduler.
Declares prometheus_multiproc volume stub to satisfy Compose named-volume
validation. Auto-merged by Compose when present in a local checkout;
omitted in preview stacks and the dark-factory container for baked-image
isolation."
```

---

## Task 6: Update CLAUDE.md

**Files:** `CLAUDE.md`

Two additions are required: a note in the Docker commands section explaining the dev/live split, and a sentence in the Dark Factory section clarifying that preview stacks omit the override file.

### Steps

**Step 6a:** In the Docker commands section, add a blockquote note immediately after the closing triple-backtick of the Docker commands code block (after line 24 in the current file).

Current block (lines 18–24):
```markdown
### Docker (recommended for full stack)
```bash
docker-compose up -d                        # Start all services
docker-compose logs -f backend              # Stream backend logs
docker-compose exec backend bash            # Shell into backend
docker-compose restart backend              # Restart one service
```
```

Updated block:
```markdown
### Docker (recommended for full stack)
```bash
docker-compose up -d                        # Start all services
docker-compose logs -f backend              # Stream backend logs
docker-compose exec backend bash            # Shell into backend
docker-compose restart backend              # Restart one service
```

> **Dev vs. live stack isolation:** `docker-compose up -d` auto-applies `docker-compose.override.yml` when present (local dev checkout), restoring bind-mounts and hot-reload. To run the baked-image stack without the override: `docker-compose -f docker-compose.yml up -d`.
```

**Step 6b:** In the Dark Factory section, add one sentence at the end of the existing "An isolated Docker container..." paragraph (after line 217 in the current file).

Current paragraph (lines 215–217):
```markdown
## Dark Factory (Autonomous Docker Development)

An isolated Docker container that autonomously develops features from GitHub issues. Runs Claude Code inside a sandboxed environment with no host access.
```

Updated paragraph:
```markdown
## Dark Factory (Autonomous Docker Development)

An isolated Docker container that autonomously develops features from GitHub issues. Runs Claude Code inside a sandboxed environment with no host access. Preview stacks and the dark-factory container deliberately omit `docker-compose.override.yml` and always run baked images — do not rely on bind-mount behavior in autonomous workflows.
```

**Commit:**
```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE.md): document dev/live stack isolation and dark factory override note"
```

---

## Task 7: Update DEVELOPMENT.md

**Files:** `DEVELOPMENT.md`

Add a dedicated "Dev vs. live stack isolation" subsection in the Docker Commands section. The current Docker Commands block ends at approximately line 105. The new subsection is inserted immediately after the closing triple-backtick of that block, before the "## Manual Setup" heading.

### Steps

**Step 7a:** Locate the end of the Docker Commands block and the start of "## Manual Setup" (around lines 105–107 in the current file):

```markdown
  docker-compose exec redis redis-cli
```

## Manual Setup (without Docker)
```

Insert the new subsection between them:

```markdown
  docker-compose exec redis redis-cli
```

## Dev vs. live stack isolation

The base `docker-compose.yml` runs **baked images** — source bind-mounts are absent so that editing files on the host or switching git branches cannot change the behavior of a running stack. This is the mode used by CI, preview environments, and the live trading stack.

`docker-compose.override.yml` is committed to the repo and is **automatically merged** by Docker Compose whenever both files are present (the standard Docker Compose behavior). In a local dev checkout this means `docker-compose up -d` restores bind-mounts and hot-reload commands as if the split never happened.

**Services covered by the override (the six that lose their bind-mount in the base file):**
- `backend` — restores `./backend:/app:ro` and adds `--reload` to uvicorn
- `celery-worker` — restores `./backend:/app:ro` and the watchfiles hot-reload command
- `celery-beat` — restores `./backend:/app:ro`
- `live-scanner` — restores `./backend:/app:ro`
- `frontend` — restores `./frontend:/app` and `/app/node_modules`, switches command back to `npm run dev`
- `backlog-scheduler` — restores `.:/workspace/project:ro`

Services with no source bind-mount (`flower`, `forecast-worker`, and all infrastructure services) are unchanged in both files.

**Run the stable baked-image stack without the override (live/CI mode):**
```bash
docker-compose -f docker-compose.yml up -d
```

**Force a full rebuild before starting (e.g. after dependency changes):**
```bash
docker-compose -f docker-compose.yml up -d --build
```

## Manual Setup (without Docker)
```

**Commit:**
```bash
git add DEVELOPMENT.md
git commit -m "docs(DEVELOPMENT.md): add dev vs. live stack isolation subsection

Explains the override file, which six services it covers, how to run the
stable stack without the override, and how to force a rebuild."
```

---

## Verification Checklist

After all tasks are complete, run these end-to-end checks. All commands use absolute paths to ensure they work regardless of current working directory.

**1. Base compose has no source bind-mounts (checks both relative and resolved-absolute forms):**
```bash
docker-compose -f /workspace/markethawk/docker-compose.yml config 2>/dev/null | grep "source:" | grep -E "backend|frontend|/workspace/markethawk$"
# Expected: no output
docker-compose -f /workspace/markethawk/docker-compose.yml config 2>/dev/null | grep "/workspace/project"
# Expected: no output
```

**2. Merged (dev) compose restores all six bind-mounts:**
```bash
docker-compose -f /workspace/markethawk/docker-compose.yml -f /workspace/markethawk/docker-compose.override.yml config 2>/dev/null | grep "source:" | grep -E "backend|frontend|/workspace/markethawk$"
# Expected: lines showing backend (x4), frontend (x1), project root (x1)
```

**3. Merged config has no undefined-volume errors:**
```bash
docker-compose -f /workspace/markethawk/docker-compose.yml -f /workspace/markethawk/docker-compose.override.yml config 2>&1 | grep -i "error\|undefined"
# Expected: no output
```

**4. Backend command in base has no --reload:**
```bash
docker-compose -f /workspace/markethawk/docker-compose.yml config 2>/dev/null | grep -A 5 "container_name: stockscanner-api" | grep command
# Expected: uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**5. Backend command in merged config has --reload:**
```bash
docker-compose -f /workspace/markethawk/docker-compose.yml -f /workspace/markethawk/docker-compose.override.yml config 2>/dev/null | grep -A 5 "container_name: stockscanner-api" | grep command
# Expected: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**6. Frontend command in base uses vite preview:**
```bash
docker-compose -f /workspace/markethawk/docker-compose.yml config 2>/dev/null | grep -A 5 "container_name: stockscanner-frontend" | grep command
# Expected: npx vite preview --host --port 3333
```

**7. Frontend image builds successfully (dist/ is baked in):**
```bash
docker compose build frontend
# Expected: exits 0
```

**8. scheduler.sh references the baked path:**
```bash
grep -n "docker-compose.yml" /workspace/markethawk/dark-factory/scheduler.sh
# Expected: /opt/dark-factory/docker-compose.yml
```

**9. dark-factory/Dockerfile bakes docker-compose.yml:**
```bash
grep -n "docker-compose.yml" /workspace/markethawk/dark-factory/Dockerfile
# Expected: COPY docker-compose.yml /opt/dark-factory/docker-compose.yml
```

**10. frontend/Dockerfile exposes port 3333:**
```bash
grep "EXPOSE" /workspace/markethawk/frontend/Dockerfile
# Expected: EXPOSE 3333
```
