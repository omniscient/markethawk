# Implementation Plan: Docker Service Resource Limits

**Issue**: [#93 — Add resource limits (memory/CPU) to all Docker services](https://github.com/omniscient/markethawk/issues/93)  
**Spec**: `Docs/superpowers/specs/2026-05-27-docker-resource-limits-design.md`  
**Date**: 2026-05-28

## Goal

Add `deploy.resources.limits` to 10 Docker services that currently have no resource caps. Two services (backend, celery-worker) additionally get CPU limits. This prevents runaway processes from starving critical services and makes capacity planning predictable.

## Architecture

Pure infrastructure change — one file (`docker-compose.yml`), no application code, no migrations, no frontend changes. Because there is no application logic being tested, the TDD cycle is adapted: **assert-before** (grep confirms deploy block is absent) → **implement** (add YAML block) → **assert-after** (`docker-compose config` validates syntax).

The canonical placement pattern for `deploy` blocks follows `tweet-monitor`: immediately after the last key in the service definition (`networks:` for services without a restart policy, `restart:` for services that have one). Note: `forecast-worker`'s deploy block appears before its `volumes` and `networks` keys — do not use it as a placement reference.

## Tech Stack

- Docker Compose v2 (`deploy.resources.limits` enforced by cgroups on the host)
- YAML configuration only

## File Structure

| File | Change |
|------|--------|
| `docker-compose.yml` | Add `deploy.resources.limits` to 10 services |

---

## Task 1: Validate baseline and add limits to postgres and redis

**Files**: `docker-compose.yml`

### Steps

**1.1 — Assert baseline passes**
```bash
docker-compose config --quiet
echo "exit code: $?"
# Expected: exit code: 0
```

**1.2 — Assert postgres has no deploy block (test-before)**
```bash
grep -n "deploy" docker-compose.yml
# Expected: only the existing forecast-worker and tweet-monitor deploy lines
# (lines containing "deploy:", "resources:", "limits:", "memory:" for those two services)
# postgres, redis, and all other services must NOT appear
```

**1.3 — Add memory limit to postgres**

In `docker-compose.yml`, after the postgres `healthcheck` block (which ends with `retries: 10`), add:

```yaml
  postgres:
    image: postgres:15-alpine
    container_name: stockscanner-db
    environment:
      ...
    ports:
      ...
    volumes:
      ...
    networks:
      - stockscanner-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres}"]
      interval: 5s
      timeout: 5s
      retries: 10
    deploy:                    # ADD THIS BLOCK
      resources:
        limits:
          memory: 2G
```

**1.4 — Add memory limit to redis**

After the redis `healthcheck` block (ends with `retries: 10`), add:

```yaml
  redis:
    image: redis:7-alpine
    container_name: stockscanner-redis
    ports:
      ...
    volumes:
      ...
    networks:
      - stockscanner-network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
    deploy:                    # ADD THIS BLOCK
      resources:
        limits:
          memory: 512M
```

**1.5 — Assert-after: syntax validates**
```bash
docker-compose config --quiet
echo "exit code: $?"
# Expected: exit code: 0
```

**1.6 — Commit**
```bash
git add docker-compose.yml
git commit -m "chore(docker): add memory limits to postgres and redis"
```

---

## Task 2: Add limit to ib-gateway

**Files**: `docker-compose.yml`

### Steps

**2.1 — Assert ib-gateway has no deploy block**
```bash
grep -A30 "^  ib-gateway:" docker-compose.yml | grep "deploy"
# Expected: no output
```

**2.2 — Add memory limit to ib-gateway**

After the ib-gateway `healthcheck` block (ends with `start_period: 60s`), add:

```yaml
  ib-gateway:
    image: ghcr.io/gnzsnz/ib-gateway:stable
    container_name: stockscanner-ibgateway
    restart: always
    environment:
      ...
    ports:
      ...
    volumes:
      ...
    networks:
      - stockscanner-network
    healthcheck:
      test: ["CMD", "bash", "-c", "socat /dev/null TCP:localhost:4004,connect-timeout=3"]
      interval: 10s
      timeout: 5s
      retries: 18
      start_period: 60s
    deploy:                    # ADD THIS BLOCK
      resources:
        limits:
          memory: 1G
```

**2.3 — Assert-after: syntax validates**
```bash
docker-compose config --quiet
echo "exit code: $?"
# Expected: exit code: 0
```

**2.4 — Commit**
```bash
git add docker-compose.yml
git commit -m "chore(docker): add memory limit to ib-gateway"
```

---

## Task 3: Add memory + CPU limits to backend and celery-worker

**Files**: `docker-compose.yml`

### Steps

**3.1 — Assert backend and celery-worker have no deploy blocks**
```bash
grep -A50 "^  backend:" docker-compose.yml | grep "deploy"
# Expected: no output
grep -A50 "^  celery-worker:" docker-compose.yml | grep "deploy"
# Expected: no output
```

**3.2 — Add memory + CPU limit to backend**

Find the line `    restart: unless-stopped` under the `backend:` service and insert the deploy block on the very next line:

```yaml
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: stockscanner-api
    environment:
      ...
    ports:
      - "8000:8000"
    depends_on:
      ...
    volumes:
      - ./backend:/app:ro
    networks:
      - stockscanner-network
    restart: unless-stopped
    deploy:                    # ADD THIS BLOCK
      resources:
        limits:
          memory: 1G
          cpus: "1.0"
```

**3.3 — Add memory + CPU limit to celery-worker**

`celery-worker` ends with `restart: unless-stopped`. Add deploy immediately after:

```yaml
  celery-worker:
    build:
      ...
    container_name: stockscanner-celery
    command: ...
    environment:
      ...
    depends_on:
      ...
    volumes:
      ...
    networks:
      - stockscanner-network
    restart: unless-stopped
    deploy:                    # ADD THIS BLOCK
      resources:
        limits:
          memory: 2G
          cpus: "2.0"
```

**3.4 — Assert-after: syntax validates**
```bash
docker-compose config --quiet
echo "exit code: $?"
# Expected: exit code: 0
```

**3.5 — Commit**
```bash
git add docker-compose.yml
git commit -m "chore(docker): add memory and CPU limits to backend and celery-worker"
```

---

## Task 4: Add limits to celery-beat and live-scanner

**Files**: `docker-compose.yml`

### Steps

**4.1 — Assert no deploy blocks on celery-beat or live-scanner**
```bash
grep -A40 "^  celery-beat:" docker-compose.yml | grep "deploy"
# Expected: no output
grep -A30 "^  live-scanner:" docker-compose.yml | grep "deploy"
# Expected: no output
```

**4.2 — Add memory limit to celery-beat**

`celery-beat` ends with `restart: unless-stopped`. Add deploy immediately after:

```yaml
  celery-beat:
    build:
      ...
    container_name: stockscanner-beat
    command: celery -A app.core.celery_app:celery_app beat --loglevel=info -s /tmp/celerybeat-schedule
    environment:
      ...
    depends_on:
      ...
    volumes:
      ...
    networks:
      - stockscanner-network
    restart: unless-stopped
    deploy:                    # ADD THIS BLOCK
      resources:
        limits:
          memory: 256M
```

**4.3 — Add memory limit to live-scanner**

`live-scanner` ends with `restart: unless-stopped`. Add deploy immediately after:

```yaml
  live-scanner:
    build:
      ...
    container_name: stockscanner-live
    command: python -m live_scanner.main
    environment:
      ...
    depends_on:
      ...
    volumes:
      ...
    networks:
      - stockscanner-network
    restart: unless-stopped
    deploy:                    # ADD THIS BLOCK
      resources:
        limits:
          memory: 512M
```

**4.4 — Assert-after: syntax validates**
```bash
docker-compose config --quiet
echo "exit code: $?"
# Expected: exit code: 0
```

**4.5 — Commit**
```bash
git add docker-compose.yml
git commit -m "chore(docker): add memory limits to live-scanner and celery-beat"
```

---

## Task 5: Add limits to flower, pgadmin, and seq

**Files**: `docker-compose.yml`

### Steps

**5.1 — Assert no deploy blocks on flower, pgadmin, or seq**
```bash
grep -A20 "^  flower:" docker-compose.yml | grep "deploy"
# Expected: no output
grep -A15 "^  pgadmin:" docker-compose.yml | grep "deploy"
# Expected: no output
grep -A15 "^  seq:" docker-compose.yml | grep "deploy"
# Expected: no output
```

**5.2 — Add memory limit to flower**

`flower` ends with its `networks:` block (no restart). Add deploy immediately after:

```yaml
  flower:
    build:
      ...
    container_name: stockscanner-flower
    command: celery -A app.core.celery_app:celery_app flower --port=5555
    environment:
      ...
    ports:
      ...
    depends_on:
      ...
    networks:
      - stockscanner-network
    deploy:                    # ADD THIS BLOCK
      resources:
        limits:
          memory: 256M
```

**5.3 — Add memory limit to pgadmin**

`pgadmin` ends with its `networks:` block (no restart). Add deploy immediately after:

```yaml
  pgadmin:
    image: dpage/pgadmin4:latest
    container_name: stockscanner-pgadmin
    environment:
      ...
    ports:
      ...
    volumes:
      ...
    depends_on:
      ...
    networks:
      - stockscanner-network
    deploy:                    # ADD THIS BLOCK
      resources:
        limits:
          memory: 512M
```

**5.4 — Add memory limit to seq**

`seq` ends with its `networks:` block (no restart). Add deploy immediately after:

```yaml
  seq:
    image: datalust/seq:latest
    container_name: stockscanner-seq
    environment:
      ...
    ports:
      ...
    volumes:
      ...
    networks:
      - stockscanner-network
    deploy:                    # ADD THIS BLOCK
      resources:
        limits:
          memory: 1G
```

**5.5 — Assert-after: syntax validates**
```bash
docker-compose config --quiet
echo "exit code: $?"
# Expected: exit code: 0
```

**5.6 — Commit**
```bash
git add docker-compose.yml
git commit -m "chore(docker): add memory limits to flower, pgadmin, and seq"
```

---

## Task 6: End-to-end validation and acceptance criteria sign-off

**Files**: none (read-only verification)

### Steps

**6.1 — Final config validation**
```bash
docker-compose config --quiet
echo "exit code: $?"
# Expected: exit code: 0
```

**6.2 — Count deploy blocks: 12 total (10 new + 2 existing)**
```bash
grep -c "deploy:" docker-compose.yml
# Expected: 12
# (postgres, redis, ib-gateway, backend, celery-worker, celery-beat,
#  live-scanner, flower, pgadmin, seq = 10 new; + forecast-worker, tweet-monitor = 2 existing)
```

**6.3 — Confirm excluded services have no deploy block**
```bash
for svc in frontend dark-factory backlog-scheduler; do
  echo -n "$svc: "
  grep -A20 "^  $svc:" docker-compose.yml | grep "deploy" || echo "no deploy block (correct)"
done
# Expected: each prints "no deploy block (correct)"
```

**6.4 — Confirm unchanged services still have their original limits**
```bash
grep -A20 "^  forecast-worker:" docker-compose.yml | grep -A3 "limits:"
# Expected: memory: 36G

grep -A20 "^  tweet-monitor:" docker-compose.yml | grep -A3 "limits:"
# Expected: memory: 1G
```

**6.5 — Start all services**
```bash
docker-compose up -d
docker-compose ps
# Expected: all non-profile services show "running"
```

**6.6 — Verify memory limits are applied at runtime**
```bash
docker stats --no-stream --format "table {{.Name}}\t{{.MemLimit}}"
# Expected: each of the 10 services shows its configured MEM LIMIT value:
# stockscanner-db        2GiB
# stockscanner-redis     512MiB
# stockscanner-ibgateway 1GiB
# stockscanner-api       1GiB
# stockscanner-celery    2GiB
# stockscanner-beat      256MiB
# stockscanner-live      512MiB
# stockscanner-flower    256MiB
# stockscanner-pgadmin   512MiB
# stockscanner-seq       1GiB
```

**6.7 — Validation complete**

No files changed in this task. All steps above are read-only checks. If any step produced unexpected output, stop and investigate before reporting the issue as done.
