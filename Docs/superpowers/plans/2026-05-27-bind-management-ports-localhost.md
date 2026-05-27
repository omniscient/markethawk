# Implementation Plan: Bind Management Service Ports to Localhost (Issue #86)

**Goal**: Harden the MarketHawk Docker stack by binding six management/infrastructure service ports to `127.0.0.1` (preventing LAN exposure), add Flower basic authentication, and mark the deployment checklist complete.

**Architecture**: Config-only change — no new code, no migrations, no new models. Touches four files: `docker-compose.yml`, `.env.example`, `ENV_VARIABLES.md`, `deployment-guide.md`.

**Tech Stack**: Docker Compose YAML; validated with `docker compose config`.

---

## File Structure

| File | Change |
|------|--------|
| `docker-compose.yml` | Prefix host bindings for postgres, redis, flower, pgadmin, seq, tweet-monitor with `127.0.0.1:`; add `FLOWER_BASIC_AUTH` to flower `environment:` block |
| `.env.example` | Add `FLOWER_BASIC_AUTH` section after `SEQ_ADMIN_PASSWORD_HASH` |
| `ENV_VARIABLES.md` | Add `FLOWER_BASIC_AUTH` row to the Required Variables table |
| `deployment-guide.md` | Check two `[ ]` items under Network Exposure (lines 26, 34); line 33 ("reverse proxy") is explicitly out of scope for this PR |

---

## Tasks

### Task 1 — Bind management service ports to localhost and add Flower auth

**Files**: `docker-compose.yml`

**1. Verify current state**
```bash
grep -n '"5432:5432"\|"6379:6379"\|"5555:5555"\|"5050:80"\|"5380:80"\|"5341:5341"\|"8001:8000"' docker-compose.yml
```
Expected (all without `127.0.0.1:` prefix):
```
13:      - "5432:5432"
30:      - "6379:6379"
241:      - "5555:5555"
259:      - "5050:80"
276:      - "5380:80"
277:      - "5341:5341"
352:      - "8001:8000"
```

**2. Apply changes to `docker-compose.yml`**

**postgres** — line 13:
```yaml
# Before
    ports:
      - "5432:5432"
# After
    ports:
      - "127.0.0.1:5432:5432"
```

**redis** — line 30:
```yaml
# Before
    ports:
      - "6379:6379"
# After
    ports:
      - "127.0.0.1:6379:6379"
```

**flower** — lines 238–241 (add env var and update port):
```yaml
# Before
    environment:
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
    ports:
      - "5555:5555"

# After
    environment:
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
      FLOWER_BASIC_AUTH: ${FLOWER_BASIC_AUTH}
    ports:
      - "127.0.0.1:5555:5555"
```

**pgadmin** — line 259:
```yaml
# Before
    ports:
      - "5050:80"
# After
    ports:
      - "127.0.0.1:5050:80"
```

**seq** — lines 276–277:
```yaml
# Before
    ports:
      - "5380:80"        # UI Port (Web Interface)
      - "5341:5341"      # Ingestion Port (API)
# After
    ports:
      - "127.0.0.1:5380:80"        # UI Port (Web Interface)
      - "127.0.0.1:5341:5341"      # Ingestion Port (API)
```

**tweet-monitor** — line 352:
```yaml
# Before
    ports:
      - "8001:8000"
# After
    ports:
      - "127.0.0.1:8001:8000"
```

**3. Verify YAML is valid and ports are correct**
```bash
docker compose config --quiet && echo "YAML: OK"
```
Expected: `YAML: OK`

Confirm management ports now have the `127.0.0.1:` prefix and public-facing services do not:
```bash
grep -E '"[^"]+:[0-9]+:[0-9]+"' docker-compose.yml
```
Expected:
- `"127.0.0.1:5432:5432"`, `"127.0.0.1:6379:6379"`, `"127.0.0.1:5555:5555"`, `"127.0.0.1:5050:80"`, `"127.0.0.1:5380:80"`, `"127.0.0.1:5341:5341"`, `"127.0.0.1:8001:8000"` — management services
- `"8000:8000"`, `"3333:3333"` — public services, unchanged
- `"4004:4004"`, `"4003:4003"` — ib-gateway, out of scope, unchanged

Confirm `FLOWER_BASIC_AUTH` is in the flower environment:
```bash
docker compose config | grep -A 15 "flower:" | grep FLOWER_BASIC_AUTH
```
Expected: a line containing `FLOWER_BASIC_AUTH:`

**4. Commit**
```bash
git add docker-compose.yml
git commit -m "security: bind management service ports to 127.0.0.1

Binds postgres, redis, flower, pgadmin, seq, and tweet-monitor host
ports to 127.0.0.1. Frontend (:3333) and backend (:8000) remain on
all interfaces. Adds FLOWER_BASIC_AUTH env var wiring to flower service.

Addresses Risk R06 from the Architecture & Quality Report."
```

---

### Task 2 — Add FLOWER_BASIC_AUTH to .env.example

**Files**: `.env.example`

**1. Verify FLOWER_BASIC_AUTH is not yet present**
```bash
grep "FLOWER_BASIC_AUTH" .env.example && echo "ALREADY PRESENT" || echo "NOT PRESENT"
```
Expected: `NOT PRESENT`

**2. Locate insertion point**
```bash
grep -n "SEQ_ADMIN_PASSWORD_HASH" .env.example
```
Expected: `58:SEQ_ADMIN_PASSWORD_HASH=`

Insert the following block immediately after `SEQ_ADMIN_PASSWORD_HASH=` (after line 58):
```bash
# =============================================================================
# REQUIRED: Flower Basic Auth
# =============================================================================
# Protects the Celery monitoring UI (http://localhost:5555).
# Format: user:password
FLOWER_BASIC_AUTH=admin:change_me_flower_password
```

**3. Verify**
```bash
grep "FLOWER_BASIC_AUTH" .env.example
```
Expected: `FLOWER_BASIC_AUTH=admin:change_me_flower_password`

Confirm the `change_me_` pattern is consistent with neighbouring credentials:
```bash
grep "change_me_" .env.example
```
Expected output (4 lines — `DATABASE_URL` also contains `change_me_db_password`):
```
POSTGRES_PASSWORD=change_me_db_password
DATABASE_URL=postgresql://postgres:change_me_db_password@postgres:5432/stockscanner
PGADMIN_DEFAULT_PASSWORD=change_me_pgadmin_password
FLOWER_BASIC_AUTH=admin:change_me_flower_password
```
Note: the spec lists `admin:changeme_flower_password` (no underscore). The plan uses `change_me_flower_password` (with underscore) to match the `change_me_db_password` / `change_me_pgadmin_password` pattern already established in the file.

**4. Commit**
```bash
git add .env.example
git commit -m "config: add FLOWER_BASIC_AUTH placeholder to .env.example"
```

---

### Task 3 — Document FLOWER_BASIC_AUTH in ENV_VARIABLES.md

**Files**: `ENV_VARIABLES.md`

**1. Verify the Required Variables table ends with SEQ_ADMIN_PASSWORD_HASH**
```bash
grep -n "SEQ_ADMIN_PASSWORD_HASH" ENV_VARIABLES.md
```
Expected: a row in the Required Variables table around line 25.

**2. Add `FLOWER_BASIC_AUTH` row to the Required Variables table**

Insert after the `SEQ_ADMIN_PASSWORD_HASH` row:
```markdown
| `FLOWER_BASIC_AUTH` | Basic auth credentials for the Flower Celery monitoring UI (`http://localhost:5555`). Format: `user:password`. Flower reads this automatically via env var mapping. | `admin:change_me_flower_password` |
```

**3. Verify**
```bash
grep "FLOWER_BASIC_AUTH" ENV_VARIABLES.md
```
Expected: one matching line in the Required Variables table.

**4. Commit**
```bash
git add ENV_VARIABLES.md
git commit -m "docs: add FLOWER_BASIC_AUTH to ENV_VARIABLES.md"
```

---

### Task 4 — Mark deployment-guide.md checklist items as complete

**Files**: `deployment-guide.md`

**1. Verify the three Network Exposure items and their scope**

The Network Exposure section has three unchecked items:
- Line 26: `- [ ] Bind management service ports to 127.0.0.1` — **check it** (handled by Task 1)
- Line 33: `- [ ] Only expose port 3000 (frontend) and 8000 (backend API) to the network or a reverse proxy.` — **leave unchecked** (out of scope: refers to reverse proxy setup, not port binding; also the port number 3000 is stale — actual frontend port is 3333)
- Line 34: `- [ ] Add authentication to Flower` — **check it** (handled by Task 1)

```bash
grep -n "\[ \]" deployment-guide.md | head -10
```
Expected to include lines 26, 33, and 34 with `[ ]`.

**2. Apply changes to `deployment-guide.md`**

Line 26 — change `[ ]` to `[x]`:
```markdown
# Before
- [ ] Bind management service ports to `127.0.0.1` in `docker-compose.yml` to prevent external access:

# After
- [x] Bind management service ports to `127.0.0.1` in `docker-compose.yml` to prevent external access:
```

Line 34 — change `[ ]` to `[x]` and update wording from "Flower command" to "Flower environment" (env var approach, not a CLI flag):
```markdown
# Before
- [ ] Add authentication to Flower: set `FLOWER_BASIC_AUTH=user:password` and add it to the Flower command in `docker-compose.yml`.

# After
- [x] Add authentication to Flower: set `FLOWER_BASIC_AUTH=user:password` and add it to the Flower environment in `docker-compose.yml`.
```

Line 33 — **do not change**. Leave as `[ ]`; the reverse proxy item is out of scope for this PR.

**3. Verify**
```bash
grep -n "\[x\]" deployment-guide.md
```
Expected: exactly 2 lines with `[x]` — lines 26 and 34.

```bash
grep -c "\[ \].*127.0.0.1\|\[ \].*Flower" deployment-guide.md
```
Expected: `0` (neither the port-binding item nor the Flower item remains unchecked)

```bash
grep "\[ \].*reverse proxy\|\[ \].*Only expose" deployment-guide.md
```
Expected: 1 line (line 33) — this one stays unchecked intentionally.

**4. Commit**
```bash
git add deployment-guide.md
git commit -m "docs: mark network hardening checklist items as complete in deployment-guide"
```

---

### Task 5 — End-to-end validation

**Files**: none (validation only)

**1. Final YAML validation**
```bash
docker compose config --quiet && echo "YAML: OK"
```
Expected: `YAML: OK`

**2. Confirm public services remain on all interfaces**
```bash
grep -E '"(8000|3333):[0-9]+"' docker-compose.yml
```
Expected:
```
      - "8000:8000"
      - "3333:3333"
```
(no `127.0.0.1:` prefix — these must be reachable on LAN)

**3. Confirm all six management services are localhost-only**
```bash
grep -E '"127\.0\.0\.1:(5432|6379|5555|5050|5380|5341|8001):' docker-compose.yml | wc -l
```
Expected: `7` (5432, 6379, 5555, 5050, 5380, 5341, 8001 — seven bindings total since seq has two ports)

**4. Confirm FLOWER_BASIC_AUTH is documented in all three places**
```bash
grep -l "FLOWER_BASIC_AUTH" docker-compose.yml .env.example ENV_VARIABLES.md | wc -l
```
Expected: `3`

**5. Confirm the two in-scope checklist items are checked; line 33 remains unchecked**
```bash
sed -n '/### Network Exposure/,/### IB Gateway/p' deployment-guide.md | grep "\[.\]"
```
Expected output (3 items — two checked, one unchecked):
```
- [x] Bind management service ports to `127.0.0.1` in `docker-compose.yml` to prevent external access:
- [ ] Only expose port 3000 (frontend) and 8000 (backend API) to the network or a reverse proxy.
- [x] Add authentication to Flower: set `FLOWER_BASIC_AUTH=user:password` and add it to the Flower environment in `docker-compose.yml`.
```
