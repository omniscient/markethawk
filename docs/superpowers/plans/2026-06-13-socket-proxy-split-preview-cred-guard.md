# Docker Socket Proxy Split + Preview Credential Guard

**Date:** 2026-06-13
**Issue:** #379
**Epic:** #372
**Status:** Plan
**Spec:** [docs/superpowers/specs/2026-06-13-socket-proxy-split-preview-cred-guard-design.md](../specs/2026-06-13-socket-proxy-split-preview-cred-guard-design.md)

---

## Goal

Split the single shared `docker-socket-proxy` into two per-consumer proxy services with separate privilege sets (requirement 1–2), add a machine-enforced grep guard + env var fallback for preview compose credentials (requirements 3–4), extend `close-preview` with a teardown assertion (requirement 5), and add a stale-preview startup warning to the scheduler (requirement 6).

## Architecture

Two `tecnativa/docker-socket-proxy` service instances replace the single shared proxy:
- `docker-socket-proxy-scheduler`: `CONTAINERS=1, IMAGES=1, POST=1` — no BUILD/EXEC/NETWORKS/VOLUMES
- `docker-socket-proxy-factory`: `CONTAINERS=1, IMAGES=1, NETWORKS=1, VOLUMES=1, BUILD=1, POST=1, EXEC=1`

Both run with `no profiles:` key (lifecycle superset of `factory` and `scheduler` profiles; see memory: Service Dependencies pattern). Each consumer wires to its own proxy via `DOCKER_HOST`. The old `docker-socket-proxy` service and `markethawk-docker-socket-proxy` container are removed.

`EXEC=1` on the factory proxy also fixes the pre-existing silent `docker compose exec` fallback bug in the preview-up postgres-probe.

The cred guard is a blocking static grep (`dark-factory/scripts/check_preview_creds.sh`) registered in both `.pre-commit-config.yaml` and `.github/workflows/ci.yml`. Env var fallback is a defence-in-depth layer, never the sole gate.

## Tech Stack

- Docker Compose YAML (infra)
- Bash (shell scripts: `check_preview_creds.sh`, `scheduler.sh`, `archon-dark-factory.yaml` node)
- `.pre-commit-config.yaml` (pre-commit framework hook)
- `.github/workflows/ci.yml` (GitHub Actions)

---

## File Structure

| File | Change |
|---|---|
| `docker-compose.yml` | Replace `docker-socket-proxy` with `docker-socket-proxy-scheduler` + `docker-socket-proxy-factory`; update `dark-factory` and `backlog-scheduler` `depends_on`/`DOCKER_HOST` |
| `dark-factory/scripts/check_preview_creds.sh` | New blocking grep guard |
| `.pre-commit-config.yaml` | Register `check-preview-creds` hook |
| `.github/workflows/ci.yml` | Add `Check preview credentials` lint step |
| `dark-factory/docker-compose.preview.yml` | Env var fallback on all 6 hardcoded credential occurrences |
| `.archon/workflows/archon-dark-factory.yaml` | Post-teardown assertion in `close-preview` node |
| `dark-factory/scheduler.sh` | Stale-preview startup warning after image probe |

---

## Tasks

### Task 1: Split docker-socket-proxy into two per-consumer services

**Goal:** Replace the single `docker-socket-proxy` with `docker-socket-proxy-scheduler` (minimal) and `docker-socket-proxy-factory` (full). Wire each consumer to its own proxy. Remove the old service.

**Files:**
- `docker-compose.yml`

**Memory patterns applied:**
- `[PATTERN] Service Dependencies`: both new proxy services have **no `profiles:` key** — they are lifecycle supersets of the `factory` and `scheduler` profiles. A proxy with `profiles: - factory` would not start with the scheduler profile and vice versa.

**Steps:**

1. **Verify the existing service block to replace (read-only):**
   ```bash
   grep -n "docker-socket-proxy" docker-compose.yml
   # Expected: lines ~453-472 (single service block) and references in dark-factory (~485,490) and backlog-scheduler (~516,518)
   ```

2. **Replace the single proxy with two service definitions.** In `docker-compose.yml`, replace the `docker-socket-proxy:` block (lines ~453-472) with:
   ```yaml
     # Proxy for backlog-scheduler only — no BUILD, EXEC, NETWORKS, VOLUMES
     docker-socket-proxy-scheduler:
       image: tecnativa/docker-socket-proxy:latest
       container_name: markethawk-docker-socket-proxy-scheduler
       restart: unless-stopped
       environment:
         CONTAINERS: 1
         IMAGES: 1
         POST: 1
         BUILD: 0
         EXEC: 0
         NETWORKS: 0
         VOLUMES: 0
         SERVICES: 0
         AUTH: 0
         SECRETS: 0
       volumes:
         - /var/run/docker.sock:/var/run/docker.sock:ro
       networks:
         - factory-network

     # Proxy for dark-factory only — full verb set including BUILD and EXEC
     # EXEC: 1 also fixes the silent postgres-probe fallback (EXEC was previously 0)
     docker-socket-proxy-factory:
       image: tecnativa/docker-socket-proxy:latest
       container_name: markethawk-docker-socket-proxy-factory
       restart: unless-stopped
       environment:
         CONTAINERS: 1
         IMAGES: 1
         NETWORKS: 1
         VOLUMES: 1
         BUILD: 1
         POST: 1
         EXEC: 1
         SERVICES: 0
         AUTH: 0
         SECRETS: 0
       volumes:
         - /var/run/docker.sock:/var/run/docker.sock:ro
       networks:
         - factory-network
   ```

3. **Update `dark-factory` consumer** in `docker-compose.yml` (lines ~485-490). Change:
   ```yaml
       DOCKER_HOST: tcp://docker-socket-proxy:2375
   ```
   to:
   ```yaml
       DOCKER_HOST: tcp://docker-socket-proxy-factory:2375
   ```
   Change `depends_on` from `[docker-socket-proxy]` to `[docker-socket-proxy-factory]`.

4. **Update `backlog-scheduler` consumer** in `docker-compose.yml` (lines ~516-518). Change:
   ```yaml
       DOCKER_HOST: tcp://docker-socket-proxy:2375
   ```
   to:
   ```yaml
       DOCKER_HOST: tcp://docker-socket-proxy-scheduler:2375
   ```
   Change `depends_on` from `[docker-socket-proxy]` to `[docker-socket-proxy-scheduler]`.

5. **Verify YAML is valid:**
   ```bash
   docker compose config --no-interpolate > /dev/null && echo "YAML OK"
   # Expected: YAML OK (no output on error)
   ```
   Verify both new proxy names appear and old name is gone:
   ```bash
   grep "docker-socket-proxy" docker-compose.yml
   # Expected: only docker-socket-proxy-scheduler and docker-socket-proxy-factory lines
   # Must NOT contain: docker-socket-proxy: (without a suffix)
   grep -c "docker-socket-proxy-scheduler\|docker-socket-proxy-factory" docker-compose.yml
   # Expected: ≥ 8 (service keys + container_name + DOCKER_HOST + depends_on refs for each consumer)
   ```

6. **Commit:**
   ```bash
   git add docker-compose.yml
   git commit -m "security(#379): split docker-socket-proxy into per-consumer services

   - docker-socket-proxy-scheduler: CONTAINERS/IMAGES/POST only (no BUILD/EXEC)
   - docker-socket-proxy-factory: full set including EXEC (fixes postgres-probe fallback)
   - removes shared markethawk-docker-socket-proxy container
   - both proxy services have no profiles: key (lifecycle superset of consumers)"
   ```

---

### Task 2: Create preview credentials guard script

**Goal:** Write `dark-factory/scripts/check_preview_creds.sh` — a blocking grep that fails if the literal strings `preview_password` or `preview-only-not-secret` appear in any `docker-compose*.yml` file outside the allowlisted `dark-factory/docker-compose.preview.yml`.

**Files:**
- `dark-factory/scripts/check_preview_creds.sh` (new)

**Steps:**

1. **Verify the scripts directory exists:**
   ```bash
   ls dark-factory/scripts/
   # Expected: existing scripts including scheduler.sh symlinks etc.
   ```

2. **Create the script:**
   ```bash
   # dark-factory/scripts/check_preview_creds.sh
   ```
   File content:
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   ALLOWLIST="dark-factory/docker-compose.preview.yml"
   DANGEROUS=("preview_password" "preview-only-not-secret")
   FAILED=0
   for pattern in "${DANGEROUS[@]}"; do
     hits=$(grep -rl "$pattern" . --include="docker-compose*.yml" 2>/dev/null \
            | grep -v "$ALLOWLIST" || true)
     if [ -n "$hits" ]; then
       echo "ERROR: preview credential '$pattern' found outside allowlisted file:" >&2
       echo "$hits" >&2
       FAILED=1
     fi
   done
   exit $FAILED
   ```

3. **Make executable:**
   ```bash
   chmod +x dark-factory/scripts/check_preview_creds.sh
   ```

4. **Self-test — should pass (allowlisted file only has preview creds):**
   ```bash
   bash dark-factory/scripts/check_preview_creds.sh
   # Expected: exit 0, no output
   ```

5. **Self-test — should fail when cred leaks into another file:**
   ```bash
   # Write a temp compose file with a preview cred
   echo "POSTGRES_PASSWORD: preview_password" > /tmp/docker-compose.test.yml
   cp /tmp/docker-compose.test.yml ./docker-compose.test.yml
   bash dark-factory/scripts/check_preview_creds.sh && echo "UNEXPECTED PASS" || echo "BLOCKED as expected"
   rm ./docker-compose.test.yml
   # Expected: "BLOCKED as expected"
   ```

6. **Commit:**
   ```bash
   git add dark-factory/scripts/check_preview_creds.sh
   git commit -m "security(#379): add check_preview_creds.sh guard script

   Blocks commits if preview_password or preview-only-not-secret appear
   in any docker-compose*.yml outside dark-factory/docker-compose.preview.yml"
   ```

---

### Task 3: Register credential guard in pre-commit and CI

**Goal:** Wire `check_preview_creds.sh` as a blocking pre-commit hook and a CI lint step.

**Files:**
- `.pre-commit-config.yaml`
- `.github/workflows/ci.yml`

**Steps:**

1. **Add hook to `.pre-commit-config.yaml`** — append a new `local` repo block after the existing ones:
   ```yaml
   - repo: local
     hooks:
       - id: check-preview-creds
         name: No preview credentials in compose files
         entry: bash dark-factory/scripts/check_preview_creds.sh
         language: system
         pass_filenames: false
         files: 'docker-compose.*\.yml$'
   ```

2. **Verify pre-commit hook fires (dry-run):**
   ```bash
   pre-commit run check-preview-creds --all-files
   # Expected: Passed (exit 0, no violations in current state)
   ```

3. **Add CI step to `.github/workflows/ci.yml`** in the `test` job, after the `Lint (ruff)` step (after line ~40):
   ```yaml
         - name: Check preview credentials
           run: bash dark-factory/scripts/check_preview_creds.sh
   ```

4. **Verify CI YAML is valid:**
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo "YAML OK"
   # Expected: YAML OK
   ```

5. **Commit:**
   ```bash
   git add .pre-commit-config.yaml .github/workflows/ci.yml
   git commit -m "security(#379): register check-preview-creds in pre-commit and CI

   Blocks any commit or PR where preview_password / preview-only-not-secret
   appear outside the allowlisted dark-factory/docker-compose.preview.yml"
   ```

---

### Task 4: Update preview compose credentials to use env var fallbacks

**Goal:** Replace all 5 hardcoded credential occurrences in `dark-factory/docker-compose.preview.yml` with env var fallbacks, so a non-ephemeral host can override weak defaults.

**Files:**
- `dark-factory/docker-compose.preview.yml`

**Memory patterns applied:**
- `[AVOID] Preview Stack`: Env var fallback alone is insufficient — the static grep guard (Task 2–3) is the actual gate; fallback is defence-in-depth. Both are required.

**Steps:**

1. **Enumerate all occurrences to change:**
   ```bash
   grep -n "preview_password\|preview-only-not-secret" dark-factory/docker-compose.preview.yml
   # Expected:
   # 14:      POSTGRES_PASSWORD: preview_password
   # 46:      DATABASE_URL: postgresql://postgres:preview_password@postgres:5432/stockscanner
   # 53:      JWT_SECRET_KEY: preview-only-not-secret-0123456789abcdef
   # 89:      DATABASE_URL: postgresql://postgres:preview_password@postgres:5432/stockscanner
   # 95:      JWT_SECRET_KEY: preview-only-not-secret-0123456789abcdef
   # 112:    PGPASSWORD=preview_password
   ```

2. **Apply all substitutions in `dark-factory/docker-compose.preview.yml`:**

   Line 14 — postgres `POSTGRES_PASSWORD`:
   ```yaml
         POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-preview_password}
   ```

   Line 46 — backend `DATABASE_URL`:
   ```yaml
         DATABASE_URL: postgresql://postgres:${POSTGRES_PASSWORD:-preview_password}@postgres:5432/stockscanner
   ```

   Line 53 — backend `JWT_SECRET_KEY`:
   ```yaml
         JWT_SECRET_KEY: ${JWT_SECRET_KEY:-preview-only-not-secret-0123456789abcdef}
   ```

   Line 89 — celery-worker `DATABASE_URL`:
   ```yaml
         DATABASE_URL: postgresql://postgres:${POSTGRES_PASSWORD:-preview_password}@postgres:5432/stockscanner
   ```

   Line 95 — celery-worker `JWT_SECRET_KEY`:
   ```yaml
         JWT_SECRET_KEY: ${JWT_SECRET_KEY:-preview-only-not-secret-0123456789abcdef}
   ```

   Line 112 — seed container `PGPASSWORD` in entrypoint:
   ```yaml
         PGPASSWORD=${POSTGRES_PASSWORD:-preview_password} psql -h postgres -U postgres -d stockscanner -f "$$f";
   ```

3. **Verify the guard script still passes (allowlisted file, so OK):**
   ```bash
   bash dark-factory/scripts/check_preview_creds.sh
   # Expected: exit 0 (allowlisted file is exempt)
   ```

4. **Verify the compose YAML is still valid:**
   ```bash
   docker compose -f dark-factory/docker-compose.preview.yml config --no-interpolate > /dev/null && echo "YAML OK"
   # Expected: YAML OK
   ```

5. **Commit:**
   ```bash
   git add dark-factory/docker-compose.preview.yml
   git commit -m "security(#379): preview compose credentials use env var fallbacks

   All 5 hardcoded occurrences of preview_password / preview-only-not-secret
   now use \${VAR:-default} so non-ephemeral hosts can override.
   Static grep guard (Task 2-3) remains the actual blocking gate."
   ```

---

### Task 5: Add teardown assertion to close-preview DAG node

**Goal:** After `docker compose ... down -v` in the `close-preview` node, verify that no `mh-preview-${ISSUE}` containers remain. Fail the node (non-zero exit) if they do.

**Files:**
- `.archon/workflows/archon-dark-factory.yaml`

**Steps:**

1. **Locate the teardown line in `close-preview`:**
   ```bash
   grep -n "down -v\|mh-preview" .archon/workflows/archon-dark-factory.yaml | head -10
   # Expected: close-preview node around line 174; down -v line ~180
   ```

2. **Add teardown assertion immediately after the `docker compose ... down -v` line** in `close-preview`'s `bash:` block — this must be inserted directly after the `down -v` line (~line 180 in the workflow file) and **before** the `gh pr list` PR-discovery block. Inserting it after the merge logic would gate teardown verification on merge success, which is not the intent.
   ```bash
   # The existing teardown line (do NOT modify it):
   docker compose -p "mh-preview-${ISSUE}" down -v 2>/dev/null || echo "No preview stack found"

   # Insert this block immediately after (before the PR-discovery / merge logic):
   REMAINING=$(docker ps -a --filter "name=mh-preview-${ISSUE}" --format '{{.Names}}' 2>/dev/null || true)
   if [ -n "$REMAINING" ]; then
     echo "ERROR: preview containers still running after teardown: $REMAINING" >&2
     exit 1
   fi
   echo "Teardown verified — no mh-preview-${ISSUE} containers remain."
   ```

3. **Verify the workflow YAML is still valid:**
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml'))" && echo "YAML OK"
   # Expected: YAML OK
   ```

   Run the full CI YAML + DAG check:
   ```bash
   python3 -c "
   import glob, sys, yaml
   for path in sorted(glob.glob('.archon/workflows/*.yaml')):
       yaml.safe_load(open(path))
   print('YAML OK')
   sys.path.insert(0, 'dark-factory/scripts')
   from check_workflow_dag import check as dag_check
   errs = dag_check('.archon/workflows/archon-dark-factory.yaml')
   if errs:
       print('DAG errors:', errs); sys.exit(1)
   print('DAG OK')
   "
   # Expected: YAML OK, DAG OK
   ```

4. **Commit:**
   ```bash
   git add .archon/workflows/archon-dark-factory.yaml
   git commit -m "security(#379): assert no containers remain after close-preview teardown

   Adds post-teardown docker ps check; node fails with non-zero exit
   if any mh-preview-\${ISSUE} container still exists after down -v"
   ```

---

### Task 6: Add stale preview startup warning to scheduler

**Goal:** After the existing image-check probe in `dark-factory/scheduler.sh`, emit a non-blocking `WARNING` if stale `mh-preview-*` containers exceed `STALE_PREVIEW_WARN_COUNT` (default: 3).

**Files:**
- `dark-factory/scheduler.sh`

**Memory patterns applied:**
- `[PATTERN] Scheduler Dispatch`: Any code touching `scheduler.sh` must not introduce bare `dispatch` calls under `set -e`. The stale-preview warning must be advisory-only (no exit on detection, no dispatch call).

**Steps:**

1. **Locate the insertion point** (after image probe, before `while true` loop):
   ```bash
   grep -n "probe=image_ok\|probe=image_pulled\|Main loop\|while true" dark-factory/scheduler.sh
   # Expected: probe lines ~737-751, "Main loop" echo ~754, while true ~757
   ```

2. **Add the `STALE_PREVIEW_WARN_COUNT` variable declaration** in the configuration block at the top of the file (with the other env var defaults, around line ~30):
   ```bash
   STALE_PREVIEW_WARN_COUNT="${STALE_PREVIEW_WARN_COUNT:-3}"
   ```

3. **Insert the stale-preview warning block** in `scheduler.sh` immediately after the image probe block (after the `probe=image_ok` / `probe=image_pulled` echo, before the `# --- Main loop ---` comment):
   ```bash
   # --- Startup check: warn if stale preview containers exist ---
   STALE=$(docker ps -a --filter "name=mh-preview" --format '{{.Names}}' 2>/dev/null | wc -l || echo 0)
   if [ "$STALE" -gt "$STALE_PREVIEW_WARN_COUNT" ]; then
     echo "[$(date -u +%FT%TZ)] WARNING: ${STALE} stale mh-preview-* containers found (threshold: ${STALE_PREVIEW_WARN_COUNT}). Run 'Close issue #N' for each." >&2
   fi
   ```

4. **Syntax-check the modified script:**
   ```bash
   bash -n dark-factory/scheduler.sh && echo "SYNTAX OK"
   # Expected: SYNTAX OK
   ```

5. **Commit:**
   ```bash
   git add dark-factory/scheduler.sh
   git commit -m "security(#379): add stale preview container startup warning to scheduler

   Emits a non-blocking WARNING if mh-preview-* containers exceed
   STALE_PREVIEW_WARN_COUNT (default: 3) at scheduler startup.
   Advisory only — does not exit or trigger restart loops."
   ```

---

## Verification Checklist

After all tasks are committed:

```bash
# 1. docker-compose.yml: new proxies present, old proxy gone
grep "docker-socket-proxy" docker-compose.yml
# Must show: docker-socket-proxy-scheduler, docker-socket-proxy-factory
# Must NOT show: bare "docker-socket-proxy:" (old service)

# 2. YAML validity
docker compose config --no-interpolate > /dev/null && echo "COMPOSE OK"

# 3. Credential guard passes cleanly (no violations in current repo)
bash dark-factory/scripts/check_preview_creds.sh && echo "CRED GUARD OK"

# 4. Pre-commit hook registered
grep "check-preview-creds" .pre-commit-config.yaml

# 5. CI step registered
grep "Check preview credentials" .github/workflows/ci.yml

# 6. Preview compose uses env var fallbacks
grep "preview_password" dark-factory/docker-compose.preview.yml
# All occurrences must be inside ${...:-preview_password} (not bare)

# 7. Teardown assertion present
grep "Teardown verified" .archon/workflows/archon-dark-factory.yaml

# 8. Scheduler warning present
grep "STALE_PREVIEW_WARN_COUNT" dark-factory/scheduler.sh

# 9. Scheduler syntax
bash -n dark-factory/scheduler.sh && echo "SCHEDULER OK"

# 10. Workflow YAML valid + DAG check
python3 -c "
import yaml, sys
yaml.safe_load(open('.archon/workflows/archon-dark-factory.yaml'))
sys.path.insert(0, 'dark-factory/scripts')
from check_workflow_dag import check as dag_check
errs = dag_check('.archon/workflows/archon-dark-factory.yaml')
sys.exit(1) if errs else print('WORKFLOW OK')
"
```
