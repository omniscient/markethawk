# Admin Credential Fail-Fast Validation

**Date:** 2026-06-13
**Issue:** #371
**Status:** Spec

---

## Problem

MarketHawk's four admin tools — pgAdmin (`:5050`), Flower (`:5555`), Seq (`:5380`), and
Grafana (`:3001`) — require credentials supplied via environment variables, but the stack
imposes no validation at boot time. If `FLOWER_BASIC_AUTH` is empty Flower starts with no
authentication; if `SEQ_ADMIN_PASSWORD_HASH` is empty Seq starts unauthenticated; Grafana
silently falls back to the hard-coded password `admin` when `GRAFANA_ADMIN_PASSWORD` is
unset; and pgAdmin starts with the placeholder `change_me_pgadmin_password` without complaint.

Observed live: the `backlog-scheduler` recreate emitted
`The "FLOWER_BASIC_AUTH" variable is not set. Defaulting to a blank string.`

Although all admin ports already bind to `127.0.0.1` (from issue #202), a mis-set
firewall or shared-VM scenario still exposes unauthenticated endpoints to anyone with
network access. The fix must be fail-fast — not a documentation reminder.

---

## Requirements

1. The stack refuses to start any admin service when its credential env var is empty,
   matches a known placeholder, or is a known-weak default.
2. Validation applies in **all environments** (development, staging, production) with no
   bypass — consistent with the existing `JWT_SECRET_KEY` and `POLYGON_API_KEY` validators.
3. Credential rules per service:
   - **pgAdmin** — `PGADMIN_DEFAULT_PASSWORD`: non-empty and not matching `change_me*`
     (case-insensitive). `PGADMIN_DEFAULT_EMAIL` is not validated (it is an identifier,
     not a secret).
   - **Seq** — `SEQ_ADMIN_PASSWORD_HASH`: non-empty AND starts with a bcrypt prefix
     (`$2a$`, `$2b$`, or `$2y$`). An empty or raw-password value is rejected.
   - **Flower** — `FLOWER_BASIC_AUTH`: format `user:password`; password portion (after
     first `:`) must be non-empty and not matching `change_me*`.
   - **Grafana** — `GRAFANA_ADMIN_PASSWORD`: non-empty, not `changeme`, not `admin`.
     The `:-admin` fallback in `docker-compose.yml` is removed as part of this change.
4. Validation failure prints a human-readable error listing every failing variable with
   a remediation hint, then exits non-zero so Docker marks the check container as failed.
5. Dependent admin services gate on the check succeeding — they do not start at all when
   credentials are bad.
6. `.env.example` updated: Seq hash entry clarified with generation command;
   Grafana placeholder changed from `changeme` to `change_me_grafana_password`
   (consistent with other placeholders, and rejected by the same `change_me*` rule).

---

## Architecture / Approach

### New service: `admin-env-check`

A new, minimal Docker Compose service runs a credential validation shell script before
any admin container starts:

```yaml
admin-env-check:
  image: alpine:3
  container_name: markethawk-admin-env-check
  restart: "no"
  environment:
    PGADMIN_DEFAULT_PASSWORD: ${PGADMIN_DEFAULT_PASSWORD}
    SEQ_ADMIN_PASSWORD_HASH: ${SEQ_ADMIN_PASSWORD_HASH}
    FLOWER_BASIC_AUTH: ${FLOWER_BASIC_AUTH}
    GRAFANA_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}
  command: >
    sh -c "
      ERRORS='';
      if [ -z \"$$PGADMIN_DEFAULT_PASSWORD\" ] || echo \"$$PGADMIN_DEFAULT_PASSWORD\" | grep -qi '^change_me'; then
        ERRORS=\"$$ERRORS\n  - PGADMIN_DEFAULT_PASSWORD: empty or placeholder\";
      fi;
      if [ -z \"$$SEQ_ADMIN_PASSWORD_HASH\" ] || ! echo \"$$SEQ_ADMIN_PASSWORD_HASH\" | grep -q '^\$2[aby]\$'; then
        ERRORS=\"$$ERRORS\n  - SEQ_ADMIN_PASSWORD_HASH: empty or not a bcrypt hash (generate: docker run --rm datalust/seq config hash)\";
      fi;
      FLOWER_PASS=\$(echo \"$$FLOWER_BASIC_AUTH\" | cut -d: -f2);
      if [ -z \"$$FLOWER_PASS\" ] || echo \"$$FLOWER_PASS\" | grep -qi '^change_me'; then
        ERRORS=\"$$ERRORS\n  - FLOWER_BASIC_AUTH: password portion empty or placeholder (format: user:password)\";
      fi;
      if [ -z \"$$GRAFANA_ADMIN_PASSWORD\" ] || echo \"$$GRAFANA_ADMIN_PASSWORD\" | grep -qiE '^(changeme|admin|change_me.*)$$'; then
        ERRORS=\"$$ERRORS\n  - GRAFANA_ADMIN_PASSWORD: empty, 'admin', 'changeme', or placeholder\";
      fi;
      if [ -n \"$$ERRORS\" ]; then
        printf 'ERROR: Admin credential validation failed.\nThe following env vars are empty, placeholder, or known-weak:\n%b\n\nUpdate your .env file before starting the stack.\n' \"$$ERRORS\";
        exit 1;
      fi;
      echo 'Admin credential check passed.';
    "
  networks:
    - stockscanner-network
```

### depends_on wiring

All four admin services add:

```yaml
depends_on:
  admin-env-check:
    condition: service_completed_successfully
```

This is the same idiomatic `depends_on` pattern the rest of the stack uses for postgres
(`condition: service_healthy`) and redis (`condition: service_healthy`). Compose will not
start flower, pgadmin, seq, or grafana if `admin-env-check` exits non-zero.

### Grafana fallback removal

`docker-compose.yml` changes:
```yaml
# Before
GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}

# After
GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}
```

The `:-admin` default silently provisions the well-known weak credential `admin` when
the env var is missing — defeating the whole check. With `admin-env-check` gating
startup, the fallback is both redundant and dangerous.

### `.env.example` updates

```bash
# REQUIRED: pgAdmin Credentials
PGADMIN_DEFAULT_EMAIL=admin@example.com
PGADMIN_DEFAULT_PASSWORD=change_me_pgadmin_password   # must be changed — rejected at startup if placeholder

# REQUIRED: Seq Admin Password Hash  (must be changed — empty or non-bcrypt hash rejected at startup)
# Generate: echo 'YourPassword' | docker run --rm -i datalust/seq config hash
SEQ_ADMIN_PASSWORD_HASH=

# REQUIRED: Flower Basic Auth (must be changed — change_me_* password rejected at startup)
FLOWER_BASIC_AUTH=admin:change_me_flower_password

# REQUIRED: Grafana Admin Password (must be changed — 'admin', 'changeme', or change_me_* rejected at startup)
GRAFANA_ADMIN_PASSWORD=change_me_grafana_password
```

`GRAFANA_ADMIN_PASSWORD` changes from `changeme` to `change_me_grafana_password` so it
is caught by the uniform `change_me*` prefix rule (not a Grafana-only special case).

---

## Files Changed

| File | Change |
|------|--------|
| `docker-compose.yml` | Add `admin-env-check` service; add `depends_on: admin-env-check` to flower, pgadmin, seq, grafana; remove `:-admin` Grafana fallback |
| `.env.example` | Clarify Seq hash generation command; change `GRAFANA_ADMIN_PASSWORD=changeme` → `change_me_grafana_password`; add "rejected at startup" note to each credential comment |

No new Dockerfiles. No backend Python changes. No migration needed.

---

## Alternatives Considered

### B — Per-service Dockerfile wrappers
Wrapping `dpage/pgadmin4:latest` and `datalust/seq:latest` with custom Dockerfiles to
inject entrypoint checks. Rejected: creates two new Dockerfile maintenance surfaces for
a 3-line shell check per service. Option A achieves the same gate with one shared check
and zero changes to third-party image configuration.

### C — Docker healthcheck overrides
Override each admin service's healthcheck to verify the credential env var. Rejected:
(a) admin containers still *start* and briefly run with bad credentials before being
marked unhealthy; (b) flower, pgadmin, seq have no existing healthcheck to extend,
requiring authoring full healthcheck blocks; (c) no service depends on admin service
health, so `unhealthy` Flower still starts without blocking anything.

### D — Pre-flight script only
A `scripts/check-admin-creds.sh` for operators to run before `docker compose up`.
Rejected: does not satisfy "refuses to boot" — any operator who forgets or skips the
script starts with bad credentials.

---

## Open Questions

- Should the `admin-env-check` service be added to `docker-compose.override.yml` (local
  dev) separately if local dev ever needs to use a different set of env vars? Not needed
  now — the check is environment-agnostic by design.

---

## Assumptions

- All admin ports already bind to `127.0.0.1` (confirmed in current `docker-compose.yml`
  from issue #202 work) — no port binding changes required.
- `alpine:3` is an acceptable new image dependency. It is ~5 MB, already common in
  Docker environments, and requires no authentication to pull.
- The `bcrypt` prefix check for Seq (`$2[aby]$`) covers all variants produced by
  `datalust/seq config hash`. If Seq ever produces a different hash format, the check
  can be relaxed to "non-empty AND non-placeholder" without changing the architecture.
