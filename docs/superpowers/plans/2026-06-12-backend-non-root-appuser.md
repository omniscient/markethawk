# Backend Non-Root appuser — Verification and Closure Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify that issue #258 (backend container running as non-root `appuser`) is fully resolved by confirming the four requirements in the spec are met by existing code, then close the issue.

**Architecture:** No code changes. The implementation already lives in `backend/Dockerfile` from commits `9b60377` and `b1adb7f` on `main`. The "implementation" is verification and issue closure.

**Tech Stack:** Dockerfile, `docker compose`, `gh` CLI.

**Spec:** `docs/superpowers/specs/2026-06-12-backend-non-root-appuser-design.md`

---

### Task 1: Verify Dockerfile satisfies all four requirements

**Files:**
- Read: `backend/Dockerfile`

- [ ] **Step 1: Confirm Requirement 1 — process does not run as root**

  Read `backend/Dockerfile` and confirm the file contains:

  ```dockerfile
  USER appuser
  ```

  Expected: the `USER appuser` directive is present and is the last `USER` directive before `EXPOSE`.

- [ ] **Step 2: Confirm Requirement 2 — appuser owns all application files**

  In `backend/Dockerfile`, confirm:

  ```dockerfile
  COPY --chown=appuser:appuser . .
  ```

  Expected: `COPY --chown=appuser:appuser` transfers ownership of all app files to `appuser` so no elevated privileges are needed at runtime.

- [ ] **Step 3: Confirm Requirement 3 — prometheus_multiproc dir is writable by appuser**

  In `backend/Dockerfile`, confirm:

  ```dockerfile
  RUN mkdir -p /tmp/prometheus_multiproc \
   && chown appuser:appuser /tmp/prometheus_multiproc
  ```

  Expected: the directory is created and chowned *before* the `USER appuser` directive so the named Docker volume is initialized with the correct ownership on first mount.

- [ ] **Step 4: Confirm Requirement 4 — celery-worker and live-scanner inherit the non-root user**

  Confirm that `docker-compose.yml` shows `celery-worker` and `live-scanner` use the same `image:` or `build:` context as `backend` (i.e., `backend/Dockerfile`). Since `USER appuser` is in the Dockerfile, all three services inherit it automatically.

  ```bash
  grep -A5 'celery-worker:' docker-compose.yml | grep -E 'image:|build:'
  grep -A5 'live-scanner:' docker-compose.yml | grep -E 'image:|build:'
  ```

  Expected: both services reference the same backend image/build context.

- [ ] **Step 5: Run docker verification commands**

  ```bash
  docker compose run --rm backend id
  ```
  Expected output: `uid=1000(appuser) gid=1000(appuser) groups=1000(appuser)`

  ```bash
  docker compose run --rm celery-worker id
  ```
  Expected output: `uid=1000(appuser) gid=1000(appuser) groups=1000(appuser)`

  ```bash
  docker compose run --rm live-scanner id
  ```
  Expected output: `uid=1000(appuser) gid=1000(appuser) groups=1000(appuser)`

  If the docker socket is unavailable in the factory environment (socket proxy blocks `exec`), record this step as skipped with a note and proceed — the Dockerfile static analysis in Steps 1–4 is the authoritative verification.

- [ ] **Step 6: Commit the verification record**

  All four requirements are satisfied by the existing Dockerfile. No files to change. Skip the commit (nothing to stage).

---

### Task 2: Close issue #258 as resolved

**Files:**
- None (gh CLI operation only)

- [ ] **Step 1: Close the issue with a resolution comment**

  ```bash
  gh issue comment 258 --repo omniscient/markethawk --body "$(cat <<'EOF'
  ## Verification Complete — Issue Resolved

  All four requirements from the spec are satisfied by commits \`9b60377\` and \`b1adb7f\` already on \`main\`:

  | Requirement | Status | Evidence |
  |---|---|---|
  | Process does not run as root (uid 0) | ✅ Met | \`USER appuser\` in \`backend/Dockerfile\` |
  | \`appuser\` owns all application files | ✅ Met | \`COPY --chown=appuser:appuser . .\` in Dockerfile |
  | \`prometheus_multiproc\` dir writable by \`appuser\` | ✅ Met | \`mkdir -p /tmp/prometheus_multiproc && chown appuser:appuser\` before \`USER appuser\` |
  | \`celery-worker\` and \`live-scanner\` inherit non-root user | ✅ Met | Both services use the same backend Dockerfile |

  Closing as resolved.
  EOF
  )"
  ```

- [ ] **Step 2: Close the issue**

  ```bash
  gh issue close 258 --repo omniscient/markethawk --reason completed
  ```

  Expected: issue #258 moves to closed/completed state.
