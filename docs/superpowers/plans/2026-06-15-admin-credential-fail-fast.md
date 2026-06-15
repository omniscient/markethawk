# Plan: Admin Credential Fail-Fast Validation

**Date:** 2026-06-15
**Issue:** #371
**Spec:** `docs/superpowers/specs/2026-06-13-admin-credential-fail-fast-design.md`
**Branch:** `refine/issue-371--security--f-admin-01--admin-tools--pgad`

---

## Goal

Add a fail-fast credential check that prevents all four admin services (pgAdmin, Flower, Seq, Grafana)
from starting when their credential env vars are empty, match a `change_me*` placeholder, or are a
known-weak default (`admin`, `changeme`). The gate runs as a one-shot `admin-env-check` service;
admin containers declare `depends_on: admin-env-check: condition: service_completed_successfully`
so Compose blocks them until the check passes.

---

## Architecture

**Pattern:** New ephemeral `admin-env-check` service (alpine:3) that runs once, validates all four
admin credentials, and exits 0/1. This matches the project's existing `condition: service_healthy`
dependency pattern for postgres/redis. The brainstorming Q&A explicitly rejected per-service
Dockerfile wrappers (two new Dockerfiles for a 3-line check) and Docker healthcheck overrides
(admin containers still start before being marked unhealthy with no downstream gate).

**Note on architecture.md memory:** The `[PATTERN]` to "extend existing services rather than
adding new Docker containers" is acknowledged. The `admin-env-check` service is ephemeral (restart: "no",
no ports, no volumes) and exits immediately — it does not add operational overhead. The spec considered
and rejected all alternatives (B: Dockerfile wrappers, C: healthcheck overrides, D: pre-flight script).
This plan follows the spec's deliberate choice.

---

## Tech Stack

- Docker Compose (`docker-compose.yml`)
- `alpine:3` image (shell only — no new Dockerfile)
- `.env.example` documentation

---

## File Structure

| File | Change |
|------|--------|
| `docker-compose.yml` | Add `admin-env-check` service; add `depends_on: admin-env-check` to flower, pgadmin, seq, grafana; remove `:-admin` Grafana fallback |
| `.env.example` | Change `GRAFANA_ADMIN_PASSWORD=changeme` → `change_me_grafana_password`; add "rejected at startup" comments to each credential block |

No new Dockerfiles. No backend Python changes. No Alembic migration needed.

---

## Tasks

---

### Task 1 — Add `admin-env-check` service to `docker-compose.yml`

**Files:** `docker-compose.yml`

#### TDD Steps

**Step 1.1 — Write failing test: verify admin-env-check does not yet exist**

```bash
docker compose config --services | grep admin-env-check
# Expected: empty output (service does not exist yet)
```

**Step 1.2 — Implement: add the `admin-env-check` service**

> **Shell escaping note:** The `command: >` YAML form wraps the entire value in `/bin/sh -c "..."` as a Docker CMD string. This means `\$` in the YAML is processed twice: once by Compose (left alone — `\$` is not the `$$` escape), then by the outer shell's double-quote handler which converts `\$` → `$`. As a result, grep receives `^$2[aby]` (POSIX BRE: `^`, then `$` is a literal dollar in a mid-pattern position per POSIX, then `2[aby]` prefix check). The trailing `\$` seen in the spec example is intentionally omitted here — a trailing `\$` would become a trailing `$` in the pattern, which BRE treats as an end-of-line anchor, making the pattern require an exact 4-char match (`$2x$`) that a 60-char bcrypt hash can never satisfy.

In `docker-compose.yml`, insert a new service before the `flower:` block (line ~328).
Place it in the `services:` section after the existing `celery-beat` service.

Add this block:

```yaml
  # Admin credential fail-fast check — exits 0 if all credentials pass, 1 on any failure.
  # All four admin services depend on this completing successfully before they start.
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
          ERRORS=\"$$ERRORS\n  - PGADMIN_DEFAULT_PASSWORD: empty or placeholder (must be a real password)\";
        fi;
        if [ -z \"$$SEQ_ADMIN_PASSWORD_HASH\" ] || ! echo \"$$SEQ_ADMIN_PASSWORD_HASH\" | grep -q '^\$2[aby]'; then
          ERRORS=\"$$ERRORS\n  - SEQ_ADMIN_PASSWORD_HASH: empty or not a bcrypt hash (generate: echo 'YourPassword' | docker run --rm -i datalust/seq config hash)\";
        fi;
        FLOWER_PASS=\$(echo \"$$FLOWER_BASIC_AUTH\" | cut -d: -f2);
        if [ -z \"$$FLOWER_PASS\" ] || echo \"$$FLOWER_PASS\" | grep -qi '^change_me'; then
          ERRORS=\"$$ERRORS\n  - FLOWER_BASIC_AUTH: password portion empty or placeholder (format: user:password)\";
        fi;
        if [ -z \"$$GRAFANA_ADMIN_PASSWORD\" ] || echo \"$$GRAFANA_ADMIN_PASSWORD\" | grep -qiE '^(changeme|admin|change_me.*)$'; then
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

**Step 1.3 — Implement: wire `depends_on` for flower**

Modify the `flower:` service's `depends_on:` block to add the check:

```yaml
  # Before
    depends_on:
      redis:
        condition: service_healthy
      celery-worker:
        condition: service_started

  # After
    depends_on:
      admin-env-check:
        condition: service_completed_successfully
      redis:
        condition: service_healthy
      celery-worker:
        condition: service_started
```

**Step 1.4 — Implement: wire `depends_on` for pgadmin**

Modify the `pgadmin:` service's `depends_on:` block:

```yaml
  # Before
    depends_on:
      postgres:
        condition: service_healthy

  # After
    depends_on:
      admin-env-check:
        condition: service_completed_successfully
      postgres:
        condition: service_healthy
```

**Step 1.5 — Implement: wire `depends_on` for seq**

The `seq:` service currently has no `depends_on:`. Add one:

```yaml
  # Before (no depends_on in seq block)
    networks:
      - stockscanner-network
    deploy:
      resources:
        limits:
          memory: 1G

  # After
    depends_on:
      admin-env-check:
        condition: service_completed_successfully
    networks:
      - stockscanner-network
    deploy:
      resources:
        limits:
          memory: 1G
```

**Step 1.6 — Implement: wire `depends_on` for grafana AND remove `:-admin` fallback**

Modify the `grafana:` service:

```yaml
  # Before
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-admin}
      GF_USERS_ALLOW_SIGN_UP: "false"
    ...
    depends_on:
      - prometheus

  # After
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}
      GF_USERS_ALLOW_SIGN_UP: "false"
    ...
    depends_on:
      admin-env-check:
        condition: service_completed_successfully
      prometheus:
        condition: service_started
```

Note: `prometheus` has no healthcheck, so its condition changes from the shorthand `- prometheus`
to the explicit `condition: service_started`.

**Step 1.7 — Verify: service appears in config**

```bash
docker compose config --services | grep admin-env-check
# Expected: admin-env-check
```

**Step 1.8 — Verify: check exits 1 with weak credentials**

```bash
PGADMIN_DEFAULT_PASSWORD=change_me_test \
SEQ_ADMIN_PASSWORD_HASH="" \
FLOWER_BASIC_AUTH="admin:change_me_flower_password" \
GRAFANA_ADMIN_PASSWORD=admin \
docker compose run --rm --no-deps admin-env-check
# Expected: exit code 1, error message listing all failing vars
echo "Exit: $?"
```

**Step 1.9 — Verify: check exits 0 with valid credentials**

To get a valid Seq bcrypt hash for testing:

```bash
SEQ_HASH=$(echo 'TestPassword123!' | docker run --rm -i datalust/seq config hash 2>/dev/null | tr -d '\n' || echo '$2b$12$fakehashforlocaltestingonly.fakeseqhash12345678')
```

Then run with passing values:

```bash
PGADMIN_DEFAULT_PASSWORD=my_secure_pgadmin_pw \
SEQ_ADMIN_PASSWORD_HASH="$SEQ_HASH" \
FLOWER_BASIC_AUTH="admin:my_secure_flower_pw" \
GRAFANA_ADMIN_PASSWORD=my_secure_grafana_pw \
docker compose run --rm --no-deps admin-env-check
# Expected: exit code 0, prints "Admin credential check passed."
echo "Exit: $?"
```

**Step 1.10 — Verify: `docker compose config` is valid YAML**

```bash
docker compose config > /dev/null
echo "Exit: $?"
# Expected: exit 0 (no YAML parse errors)
```

**Step 1.11 — Commit**

```bash
git add docker-compose.yml
git commit -m "feat(security): add admin-env-check service to block startup on weak credentials (#371)

Adds a one-shot admin-env-check alpine:3 service that validates
PGADMIN_DEFAULT_PASSWORD, SEQ_ADMIN_PASSWORD_HASH, FLOWER_BASIC_AUTH, and
GRAFANA_ADMIN_PASSWORD before any admin service starts. All four admin services
depend on this check completing successfully. Removes the :-admin Grafana fallback.

Closes part of #371."
```

---

### Task 2 — Update `.env.example` credential documentation

**Files:** `.env.example`

#### TDD Steps

**Step 2.1 — Write failing test: verify old Grafana placeholder exists**

```bash
grep -c 'GRAFANA_ADMIN_PASSWORD=changeme' .env.example
# Expected: 1 (old placeholder present — test will fail after our change)
```

**Step 2.2 — Implement: update `.env.example`**

**(a) Update the pgAdmin section** — add "rejected at startup" note to the comment:

```bash
# Before (lines ~63-67):
# =============================================================================
# REQUIRED: pgAdmin Credentials
# =============================================================================
# Admin login for the pgAdmin web UI (http://localhost:5050).
PGADMIN_DEFAULT_EMAIL=admin@example.com
PGADMIN_DEFAULT_PASSWORD=change_me_pgadmin_password

# After:
# =============================================================================
# REQUIRED: pgAdmin Credentials
# =============================================================================
# Admin login for the pgAdmin web UI (http://localhost:5050).
# MUST be changed — empty or change_me_* values are rejected at startup.
PGADMIN_DEFAULT_EMAIL=admin@example.com
PGADMIN_DEFAULT_PASSWORD=change_me_pgadmin_password
```

**(b) Update the Seq section** — add "rejected at startup" note:

```bash
# Before (lines ~69-76):
# =============================================================================
# REQUIRED: Seq Admin Password Hash
# =============================================================================
# Seq (http://localhost:5380) requires a bcrypt hash for the initial admin
# password so it starts with authentication enabled.
# Generate with:  echo 'YourPassword' | docker run --rm -i datalust/seq config hash
# Then paste the full hash string (begins with $2a$) as the value below.
SEQ_ADMIN_PASSWORD_HASH=

# After:
# =============================================================================
# REQUIRED: Seq Admin Password Hash
# =============================================================================
# Seq (http://localhost:5380) requires a bcrypt hash for the initial admin
# password so it starts with authentication enabled.
# MUST be set — empty or non-bcrypt values are rejected at startup.
# Generate with:  echo 'YourPassword' | docker run --rm -i datalust/seq config hash
# Then paste the full hash string (begins with $2a$, $2b$, or $2y$) as the value below.
SEQ_ADMIN_PASSWORD_HASH=
```

**(c) Update the Flower section** — add "rejected at startup" note:

```bash
# Before (lines ~78-84):
# =============================================================================
# REQUIRED: Flower Basic Auth
# =============================================================================
# Basic auth credentials for the Flower Celery monitoring UI (http://localhost:5555).
# Flower reads FLOWER_BASIC_AUTH automatically from the environment.
# Format: user:password
FLOWER_BASIC_AUTH=admin:change_me_flower_password

# After:
# =============================================================================
# REQUIRED: Flower Basic Auth
# =============================================================================
# Basic auth credentials for the Flower Celery monitoring UI (http://localhost:5555).
# Flower reads FLOWER_BASIC_AUTH automatically from the environment.
# MUST be changed — empty password or change_me_* password rejected at startup.
# Format: user:password
FLOWER_BASIC_AUTH=admin:change_me_flower_password
```

**(d) Update the Grafana section** — change placeholder from `changeme` to `change_me_grafana_password`,
update comment text, and remove the "defaults to admin" language:

```bash
# Before (lines ~176-181):
# =============================================================================
# Monitoring (Grafana)
# =============================================================================
# Admin password for the Grafana UI (http://localhost:3001, login: admin).
# If not set, defaults to "admin" (change this in production).
GRAFANA_ADMIN_PASSWORD=changeme

# After:
# =============================================================================
# REQUIRED: Grafana Admin Password
# =============================================================================
# Admin password for the Grafana UI (http://localhost:3001, login: admin).
# MUST be changed — 'admin', 'changeme', and change_me_* values are rejected at startup.
GRAFANA_ADMIN_PASSWORD=change_me_grafana_password
```

**Step 2.3 — Verify: old Grafana placeholder is gone**

```bash
grep -c 'GRAFANA_ADMIN_PASSWORD=changeme$' .env.example
# Expected: 0
```

**Step 2.4 — Verify: new placeholder is present**

```bash
grep 'GRAFANA_ADMIN_PASSWORD=change_me_grafana_password' .env.example
# Expected: match found
```

**Step 2.5 — Verify: all four "rejected at startup" notes are present**

```bash
grep -c 'rejected at startup' .env.example
# Expected: 4 (one per admin credential block)
```

**Step 2.6 — Commit**

```bash
git add .env.example
git commit -m "fix(security): update .env.example — Grafana placeholder + rejected-at-startup notes (#371)

Changes GRAFANA_ADMIN_PASSWORD from 'changeme' to 'change_me_grafana_password'
so it is caught by the uniform change_me* prefix rule. Adds 'rejected at startup'
comments to all four admin credential blocks to make the fail-fast behaviour
discoverable. Removes the outdated 'defaults to admin' note from the Grafana entry."
```

---

## Verification Checklist

After both tasks are committed, verify the full integration:

```bash
# 1. Compose config parses without errors
docker compose config > /dev/null && echo "OK: YAML valid"

# 2. admin-env-check exits 1 with default .env.example values
#    (FLOWER_BASIC_AUTH=admin:change_me_flower_password, GRAFANA_ADMIN_PASSWORD=change_me_grafana_password, etc.)
docker compose run --rm --no-deps admin-env-check
echo "Exit $? (expected: 1)"

# 3. Seq, pgadmin, flower, grafana all declare admin-env-check dependency
docker compose config | grep -A8 "flower:" | grep "admin-env-check"
docker compose config | grep -A8 "pgadmin:" | grep "admin-env-check"
docker compose config | grep -A8 "seq:" | grep "admin-env-check"
docker compose config | grep -A8 "grafana:" | grep "admin-env-check"

# 4. Grafana fallback removed
docker compose config | grep "GF_SECURITY_ADMIN_PASSWORD" | grep -v ':-admin'
```
