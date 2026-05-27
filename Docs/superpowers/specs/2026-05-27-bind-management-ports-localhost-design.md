# Bind Management Service Ports to Localhost — Security Hardening

## Problem

Management and infrastructure services in `docker-compose.yml` are bound to `0.0.0.0` (all network interfaces), making them reachable from any device on the local network. This exposes:

| Service | Port | Risk |
|---------|------|------|
| pgAdmin | :5050 | Full PostgreSQL admin access |
| Flower | :5555 | Celery task queue manipulation (no auth) |
| Seq | :5380 / :5341 | Log access including stack traces and error IDs |
| PostgreSQL | :5432 | Direct database access |
| Redis | :6379 | Direct cache/broker access |
| tweet-monitor | :8001 | Internal microservice API |

Identified in the Architecture & Quality Report as Risk R06 (High). The `deployment-guide.md` documents the fix but it has never been applied.

## Requirements

1. Bind pgAdmin (:5050), Flower (:5555), Seq (:5380, :5341), PostgreSQL (:5432), Redis (:6379), and tweet-monitor (:8001) to `127.0.0.1` in `docker-compose.yml`.
2. Keep frontend (:3333) and backend API (:8000) bound to all interfaces — they need to be reachable on the LAN by clients.
3. Add Flower basic authentication via `FLOWER_BASIC_AUTH` environment variable. Flower reads this automatically (strips `FLOWER_` prefix and maps to the `basic_auth` option); no `--basic_auth=` flag is needed on the command line.
4. Add `FLOWER_BASIC_AUTH` to `.env.example` with a placeholder credential, consistent with the `change_me_*` pattern already used for pgAdmin and Seq.
5. Document `FLOWER_BASIC_AUTH` in `ENV_VARIABLES.md`.
6. Mark the deployment-guide.md checklist items as complete (check the boxes).

## Approach

**Single-pass docker-compose edit with env var wiring.**

For each in-scope service, prefix the host-side port binding with `127.0.0.1:`. Add `FLOWER_BASIC_AUTH: ${FLOWER_BASIC_AUTH}` to the Flower service's `environment:` block. Update `.env.example` and `ENV_VARIABLES.md`. Mark the deployment-guide checklist items as done.

### docker-compose.yml changes

```yaml
# Before → After

postgres:
  ports:
    - "127.0.0.1:5432:5432"    # was "5432:5432"

redis:
  ports:
    - "127.0.0.1:6379:6379"    # was "6379:6379"

flower:
  environment:
    CELERY_BROKER_URL: redis://redis:6379/0
    CELERY_RESULT_BACKEND: redis://redis:6379/0
    FLOWER_BASIC_AUTH: ${FLOWER_BASIC_AUTH}     # new
  ports:
    - "127.0.0.1:5555:5555"    # was "5555:5555"

pgadmin:
  ports:
    - "127.0.0.1:5050:80"      # was "5050:80"

seq:
  ports:
    - "127.0.0.1:5380:80"      # was "5380:80"
    - "127.0.0.1:5341:5341"    # was "5341:5341"

tweet-monitor:
  ports:
    - "127.0.0.1:8001:8000"    # was "8001:8000"
```

### .env.example addition

```bash
# REQUIRED: Flower Basic Auth
# Protects the Celery monitoring UI (http://localhost:5555).
# Format: user:password
FLOWER_BASIC_AUTH=admin:changeme_flower_password
```

### ENV_VARIABLES.md addition

Add a row for `FLOWER_BASIC_AUTH` alongside the other management service credentials.

### deployment-guide.md

Change the two unchecked checklist items to checked:
- `[ ] Bind management service ports to 127.0.0.1` → `[x]`
- `[ ] Add authentication to Flower` → `[x]`

## Alternatives Considered

### A: Strictly follow issue scope (pgAdmin + Flower + Seq only)

The issue explicitly names three services. Keeping the change minimal reduces diff noise and risk of regression.

**Rejected**: PostgreSQL and Redis bound to all interfaces is a higher-severity risk than the named services — direct database and broker access with no application-layer auth. The product owner confirmed they should be included in the same PR.

### B: Extended scope including ib-gateway (:4003/:4004)

IB Gateway ports are also bound to `0.0.0.0`.

**Rejected**: IBKR connectivity has complex networking requirements and the connection path has not been fully validated for localhost-only binding. Addressed in a follow-up issue.

## Assumptions

- The host running Docker has no legitimate need to serve these management UIs to other LAN devices. If the developer needs remote access (e.g. from another machine), they can SSH tunnel.
- Flower's automatic env var mapping (`FLOWER_BASIC_AUTH` → `basic_auth`) is stable across the Flower version pinned to the backend `requirements.txt`. No `--basic_auth=` flag is needed on the `command:` line.
- ib-gateway (:4003/:4004) is intentionally out of scope; it requires separate network validation.

## Open Questions

- Should the `tweet-monitor` port (:8001) be removed entirely (no external use) rather than just bound to localhost? Deferred — out of scope for this PR; the current approach (localhost-only) is safe enough.
