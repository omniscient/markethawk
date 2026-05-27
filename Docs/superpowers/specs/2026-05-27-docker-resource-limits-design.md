# Docker Service Resource Limits — Design Spec

**Issue**: [#93 — Add resource limits (memory/CPU) to all Docker services](https://github.com/omniscient/markethawk/issues/93)  
**Date**: 2026-05-27  
**Status**: Pending Review

## Overview

Most Docker services in `docker-compose.yml` have no memory or CPU limits. Only `forecast-worker` (36G) and `tweet-monitor` (1G) have explicit limits. A runaway process — memory leak, large data sync, or ML task — can starve critical services like the API or database. This spec adds `deploy.resources.limits` to all remaining services that warrant protection, preventing resource starvation and making capacity planning predictable.

## Requirements

- Add hard memory limits to 10 services currently missing them (postgres, redis, ib-gateway, backend, celery-worker, celery-beat, live-scanner, flower, pgadmin, seq)
- Add CPU limits to the two compute-heavy services (backend, celery-worker)
- Use `deploy.resources.limits` only (no `reservations`) — consistent with the existing pattern set by `forecast-worker` and `tweet-monitor`
- Do not modify `forecast-worker` or `tweet-monitor` (already limited)
- Do not add limits to `frontend`, `dark-factory`, or `backlog-scheduler` (see Alternatives section)

## Implementation

### docker-compose.yml Changes

Add a `deploy.resources.limits` block to each service listed below. The `deploy` key must be at the top level of the service definition (same level as `image`, `environment`, etc.).

#### postgres
```yaml
deploy:
  resources:
    limits:
      memory: 2G
```

#### redis
```yaml
deploy:
  resources:
    limits:
      memory: 512M
```

#### ib-gateway
```yaml
deploy:
  resources:
    limits:
      memory: 1G
```
ib-gateway is a long-running JVM-based third-party process (`restart: always`). Java heap growth is unbounded by default; 1G is a reasonable ceiling for a socket-relay gateway.

#### backend
```yaml
deploy:
  resources:
    limits:
      memory: 1G
      cpus: "1.0"
```

#### celery-worker
```yaml
deploy:
  resources:
    limits:
      memory: 2G
      cpus: "2.0"
```
celery-worker gets 2G and 2 CPU cores because it runs the most CPU-intensive work: scanner tasks, data sync, quality checks, and signal scoring (see `backend/app/tasks/`).

#### celery-beat
```yaml
deploy:
  resources:
    limits:
      memory: 256M
```

#### live-scanner
```yaml
deploy:
  resources:
    limits:
      memory: 512M
```

#### flower
```yaml
deploy:
  resources:
    limits:
      memory: 256M
```

#### pgadmin
```yaml
deploy:
  resources:
    limits:
      memory: 512M
```

#### seq
```yaml
deploy:
  resources:
    limits:
      memory: 1G
```

### Placement

Place each `deploy` block immediately after the `networks` key (or `restart` key where present) for each service. This matches the placement pattern used by `forecast-worker` and `tweet-monitor`.

## Acceptance Criteria

- [ ] All 10 services listed above have a `deploy.resources.limits.memory` value in `docker-compose.yml`
- [ ] `backend` and `celery-worker` additionally have `deploy.resources.limits.cpus`
- [ ] `docker-compose config` validates without errors
- [ ] `docker-compose up -d` starts all services successfully
- [ ] `docker stats` shows memory limits applied (visible as `MEM LIMIT` column)
- [ ] `forecast-worker` and `tweet-monitor` limits are unchanged
- [ ] `frontend`, `dark-factory`, and `backlog-scheduler` have no new limits

## Alternatives Considered

### Add limits to all services including frontend, dark-factory, backlog-scheduler
Rejected. `frontend` is a dev-only Vite server with transient, small footprint. `dark-factory` runs on-demand with highly variable memory (runs Claude Code autonomously) — a hard cap would cause unpredictable mid-task OOM failures. `backlog-scheduler` is a lightweight shell poller; its footprint is negligible and capping it adds risk with no benefit.

### Add memory reservations (soft limits) alongside hard limits
Rejected. The existing pattern (`forecast-worker`, `tweet-monitor`) uses hard limits only. Reservations are scheduler hints for Swarm/Kubernetes orchestration; in Docker Compose standalone mode they have no practical effect. Adding them would diverge from convention without operational benefit.

### Apply CPU limits to all services
Rejected. CPU limits are only warranted where runaway CPU is a realistic threat. `postgres`, `redis`, `seq`, and monitoring tools are I/O-bound or scheduling-only — capping their CPU could degrade critical-path operations under load without protecting against any known risk.

## Open Questions

- After applying limits, what are the actual `docker stats` baselines under typical pre-market scan load? The issue suggests ~2x headroom; real profiling may suggest adjustments (non-blocking — limits can be tuned after initial deployment).

## Assumptions

- **The host machine has sufficient RAM**: ~8.8G in limits across all services. This is the sum of all limits simultaneously, which will not be reached in practice since `forecast-worker` and `seq` are rarely at their ceiling concurrently.
- **Docker Compose standalone mode**: `deploy.resources.limits` works in Docker Compose v2+ without Swarm. CPU throttling via `cpus:` is enforced by cgroups on the host kernel (Linux). On macOS/Windows Docker Desktop, behavior is identical.
- **OOM kills are acceptable as a monitoring signal**: An OOM-killed container will be restarted by its `restart: unless-stopped` policy. This is the desired behavior — fail fast and recover rather than degrading the entire host.
