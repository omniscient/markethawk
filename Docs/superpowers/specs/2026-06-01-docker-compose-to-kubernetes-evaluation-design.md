# Docker Compose to Kubernetes Migration Evaluation

**Issue:** #141 — Evaluate going from Docker Compose to Kubernetes  
**Date:** 2026-06-01  
**Status:** Draft

---

## Background

MarketHawk currently runs its full stack via Docker Compose. As the platform matures, operational requirements are pushing toward a managed Kubernetes environment: zero-downtime deploys, horizontal scaling of Celery workers, and a credible path to cloud-hosted production. This spec evaluates three migration options and recommends an approach.

---

## Goals

- Identify the lowest-friction path from Docker Compose to a production-ready Kubernetes setup
- Preserve the developer-machine workflow (fast iteration, easy service restart)
- Establish a manifest structure that maps directly to a managed cloud provider (EKS, GKE, AKS) without re-architecture
- Document what cannot be migrated and why

---

## Non-Goals

- Full production deployment (that is a follow-on issue)
- CI/CD pipeline changes (separate concern)
- Cost modelling for cloud providers

---

## Constraints

1. **Docker-out-of-Docker services are hard-excluded.** The Dark Factory (`dark-factory`) and Backlog Scheduler (`scheduler`) both mount `/var/run/docker.sock`. This pattern is unsupported in managed Kubernetes environments. Both services remain as Docker Compose profile services (`--profile factory`, `--profile scheduler`) indefinitely.
2. **IB Gateway is a singleton.** Interactive Brokers enforces a single concurrent connection per account. IB Gateway must run as a StatefulSet with `replicas: 1` and a PodDisruptionBudget that prevents simultaneous eviction.
3. **Secrets must not be committed.** All credentials (API keys, passwords, tokens) are injected via Kubernetes Secrets, never baked into manifests.

---

## Options Evaluated

### Option A: Helm Charts

Package each service as a Helm chart or use a community chart (e.g., Bitnami Postgres).

| Pros | Cons |
|------|------|
| Industry standard for K8s packaging | Steep learning curve; Helm DSL adds indirection |
| Large library of community charts | Community charts often over-parameterised for a small team |
| Release management via `helm upgrade` | Adds a new CLI and templating engine to the stack |

**Verdict:** Too much upfront complexity for a team without documented Kubernetes experience. Revisit when the cluster is stable and the team is comfortable with raw manifests.

### Option B: k3d + Kustomize (Recommended)

Run a local Kubernetes cluster inside Docker via k3d. Manage manifests with Kustomize (`base/` + `overlays/`), which ships with `kubectl` (no extra install).

| Pros | Cons |
|------|------|
| k3d only requires `kubectl` + `k3d` as new prereqs | k3d is not production — overlays must be swapped at cloud launch |
| Kustomize `base/overlays` maps directly to any managed provider | Overlay discipline must be enforced from day one |
| No new templating language; manifests are plain YAML | Resource limits must be tuned per environment |
| Local cluster mirrors production topology | |

**Verdict:** Recommended. This threads the needle between developer ergonomics and production readiness.

### Option C: Docker Compose on a VM (lift-and-shift)

Run the existing `docker-compose.yml` on a cloud VM (e.g., EC2, a Hetzner VPS).

| Pros | Cons |
|------|------|
| Zero migration effort | Does not achieve the Kubernetes goal |
| Familiar tooling | No horizontal scaling, no rolling deploys |
| | Single point of failure |

**Verdict:** Excluded. Does not satisfy the goal of this issue.

---

## Recommended Approach: k3d + Kustomize

### Repository Layout

```
k8s/
  base/
    namespace.yaml
    backend/
      deployment.yaml
      service.yaml
      hpa.yaml
    celery/
      worker-deployment.yaml
      beat-deployment.yaml
      flower-deployment.yaml
    frontend/
      deployment.yaml
      service.yaml
    postgres/
      statefulset.yaml
      service.yaml
      pvc.yaml
    redis/
      statefulset.yaml
      service.yaml
      pvc.yaml
    seq/
      statefulset.yaml
      service.yaml
    prometheus/
      deployment.yaml
      service.yaml
      configmap.yaml
    grafana/
      deployment.yaml
      service.yaml
    jaeger/
      deployment.yaml
      service.yaml
    ibgateway/
      statefulset.yaml
      service.yaml
      pdb.yaml
    kustomization.yaml
  overlays/
    local/
      kustomization.yaml
      patches/
    staging/
      kustomization.yaml
      patches/
    production/
      kustomization.yaml
      patches/
```

### What Stays in Docker Compose

| Service | Reason |
|---------|--------|
| `dark-factory` | Mounts `/var/run/docker.sock`; incompatible with managed K8s |
| `scheduler` (backlog scheduler) | Mounts `/var/run/docker.sock`; incompatible with managed K8s |
| `pgadmin` | Development convenience tool; no production requirement |

These remain accessible via `docker compose --profile factory` and `docker compose --profile scheduler`.

---

## Migration Phases

### Phase 1 — Stateless Services (backend, Celery, frontend)

Migrate the three stateless service groups first. These have no persistent volume requirements and can be rolled back instantly.

- `backend`: Deployment + Service + HPA (scale on CPU; target 70%)
- `celery-worker`: Deployment (replicas configurable per overlay)
- `celery-beat`: Deployment (replicas: 1 — beat must not run in parallel)
- `flower`: Deployment + Service
- `frontend`: Deployment + Service (or serve via CDN — overlay decision)

**Exit criteria:** All services healthy in k3d local cluster; `curl http://localhost/api/health` returns 200.

### Phase 2 — Stateful Data (Postgres, Redis)

Migrate Postgres and Redis as StatefulSets with PersistentVolumeClaims.

- Postgres: StatefulSet with `volumeClaimTemplates`, init container for `alembic upgrade head`
- Redis: StatefulSet with `volumeClaimTemplates`

**Exit criteria:** Scanner runs successfully end-to-end against the K8s Postgres instance; Celery tasks enqueue and complete via K8s Redis.

### Phase 3 — Observability Stack (Seq, Prometheus, Grafana, Jaeger)

Migrate the observability services. These are non-critical-path; outage during migration does not affect trading data.

- Seq: StatefulSet (licence key injected via Secret)
- Prometheus: Deployment + ConfigMap for scrape targets
- Grafana: Deployment + PVC for dashboards (or ConfigMap-backed dashboards)
- Jaeger: Deployment (all-in-one image for local; split collector/query for production overlay)

**Exit criteria:** Backend traces visible in Jaeger UI; Prometheus scraping all targets; Grafana dashboards loading.

### Phase 4 — IB Gateway

Migrate the Interactive Brokers gateway last, as it carries the highest operational risk.

- StatefulSet with `replicas: 1`
- PodDisruptionBudget: `maxUnavailable: 0`
- `startupProbe` on the TWS API port (4002) before readiness
- Overlay patches for paper vs. live trading credentials

**Exit criteria:** `ibkr.py` provider connects successfully from the backend pod; live data flows through the scanner.

### Phase 5 — Deferred (separate issue)

- `forecast-worker` (not yet implemented)
- Dark Factory (blocked on Docker socket constraint — revisit if a DinD solution is approved)

---

## Open Questions

The following questions require answers from the team before implementation begins. Each answer may affect the overlay structure or resource manifests.

| # | Question | Impact |
|---|----------|--------|
| 1 | What are the developer machine specs (CPU cores, RAM)? | k3d resource limits in `overlays/local` |
| 2 | Which cloud provider is targeted for production? | StorageClass names, LoadBalancer annotations |
| 3 | Single namespace or one namespace per environment? | `namespace.yaml` and RBAC design |
| 4 | How are production secrets managed? (Vault, AWS Secrets Manager, K8s Secrets only?) | Secret injection strategy |
| 5 | Is autoscaling required from day one, or phased in? | HPA manifests in Phase 1 |
| 6 | Should Docker Compose remain as a supported alternative for application services, or is it replaced entirely? | Whether to maintain `docker-compose.yml` long-term |

---

## Assumptions

The following inferences were made where information was not available. Flag any incorrect assumption before implementation starts.

1. The team has no prior Kubernetes operational experience (drives the Helm exclusion).
2. IB Gateway runs a single live account (drives the `replicas: 1` and PDB requirement).
3. Production will use a managed Kubernetes provider (not self-hosted K8s on bare metal).
4. Manifests should be provider-agnostic in `base/`; provider-specific configuration lives in overlays.
5. The scanner's correctness does not depend on the observability stack (justifies Phase 3 ordering).
6. `celery-beat` must remain a single replica in all environments (standard Celery constraint).
7. The existing `docker-compose.yml` is the authoritative source of environment variables and image tags during the migration.
8. pgAdmin is a developer convenience tool and is not required in Kubernetes.

---

## References

- [ARCHITECTURE.md](../../ARCHITECTURE.md) — service topology and Celery task map
- [dark-factory design spec](2026-05-02-dark-factory-design.md) — Dark Factory architecture and Docker socket dependency
- [ENV_VARIABLES.md](../../ENV_VARIABLES.md) — all environment variables that become K8s Secrets or ConfigMap entries
- [GitHub Issue #141](https://github.com/omniscient/markethawk/issues/141) — original evaluation request
