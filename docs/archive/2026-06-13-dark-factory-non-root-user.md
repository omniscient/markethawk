# Dark Factory: Non-Root `factory` User Verification & Publish

**Date:** 2026-06-13
**Issue:** #261
**Epic:** #272 (Container & deployment security hardening)
**Status:** Plan

---

## Goal

Verify the non-root `factory` user setup in the dark-factory image by forcing a clean `--no-cache` rebuild, running smoke tests for both the `dark-factory` and `backlog-scheduler` services, publishing the verified image, and closing the issue.

No new application code is required. All six Dockerfile and entrypoint changes are already committed to `main`. The only code change in this plan is a temporary `no-cache: true` flag in `.github/workflows/ci-publish.yml` (added before the rebuild, reverted after smoke tests pass).

## Architecture

Two-stage workflow:

1. **Automated** (implement agent): Add `no-cache: true` to the `build-dark-factory` CI job. Merge to main triggers the forced rebuild and image publish. After smoke tests pass, revert the flag.
2. **Manual** (human): After CI publishes the new image, pull it and run the smoke checklist against both services on the Docker host.

The self-modification constraint applies: the factory container runs from the baked image it would need to rebuild, so it cannot execute the Docker rebuild or smoke tests itself.

## Tech Stack

- CI: `.github/workflows/ci-publish.yml` — `docker/build-push-action@v6`
- Runtime: `docker compose --profile factory` and `--profile scheduler`
- Image: `ghcr.io/omniscient/markethawk-dark-factory:latest`

## File Structure

| File | Change | Notes |
|---|---|---|
| `.github/workflows/ci-publish.yml` | Temporary: add `no-cache: true` to `build-dark-factory` step | Reverted in Task 5 after smoke tests pass |

---

## Task 1: Add `no-cache: true` to CI Build Job

**Type:** Automated (implement agent)
**Files:** `.github/workflows/ci-publish.yml`

### Steps

1. Confirm `no-cache` is absent from the current `build-dark-factory` step:

   ```bash
   grep -n "no-cache" .github/workflows/ci-publish.yml
   # Expected: no output
   ```

2. Add `no-cache: true` to the `with:` block (`.github/workflows/ci-publish.yml`, lines 95–102):

   ```yaml
   # .github/workflows/ci-publish.yml
   # build-dark-factory job → "Build and push dark-factory image" step

         - name: Build and push dark-factory image
           uses: docker/build-push-action@v6
           with:
             context: .
             file: ./dark-factory/Dockerfile
             push: true
             tags: ${{ steps.meta.outputs.tags }}
             labels: ${{ steps.meta.outputs.labels }}
             no-cache: true  # force clean rebuild to exercise ubuntu-eviction layer
   ```

3. Verify only one occurrence of `no-cache` was added:

   ```bash
   grep -c "no-cache" .github/workflows/ci-publish.yml
   # Expected: 1
   ```

4. Commit:

   ```bash
   git add .github/workflows/ci-publish.yml
   git commit -m "ci: force --no-cache rebuild to verify non-root factory user (issue #261)"
   ```

5. Verify commit:

   ```bash
   git log --oneline -1
   # Expected: ci: force --no-cache rebuild to verify non-root factory user (issue #261)
   ```

---

## Task 2: Trigger CI No-Cache Rebuild (Manual)

**Type:** Manual — requires merging to `main` or triggering `workflow_dispatch` from GitHub
**Files:** None

### Steps

1. After Task 1 merges to `main`, the `build-dark-factory` CI job triggers automatically. To trigger manually via CLI:

   ```bash
   gh workflow run ci-publish.yml --repo omniscient/markethawk --ref main
   ```

   Or navigate to: **Actions → CI Publish → Run workflow → Branch: main**.

2. Monitor until the `build-dark-factory` job completes successfully:

   ```bash
   gh run list --repo omniscient/markethawk --workflow=ci-publish.yml --limit=3
   # Expected: most recent run status = "completed / success" (not "failure" or "in_progress")
   ```

3. Confirm the image was pushed with a fresh timestamp:

   ```bash
   gh api "orgs/omniscient/packages/container/markethawk-dark-factory/versions?per_page=3" \
     --jq '.[].metadata.container.tags, .[].updated_at' 2>/dev/null || \
   docker manifest inspect ghcr.io/omniscient/markethawk-dark-factory:latest \
     | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['schemaVersion'], d.get('mediaType',''))"
   # Expected: manifest resolves without error; image timestamp is within the last ~30 minutes
   ```

---

## Task 3: Smoke-Test `dark-factory` Service (Manual)

**Type:** Manual — requires rebuilt image pulled to Docker host
**Files:** None (verification only)

**Pre-condition:** Task 2 completed successfully; `docker compose pull dark-factory` run on host.

### Steps

1. Pull the rebuilt image:

   ```bash
   docker compose pull dark-factory
   # Expected: "dark-factory Pulled" or "latest: Pulling from omniscient/markethawk-dark-factory"
   ```

2. Verify container identity — must be `factory`, not `root`:

   ```bash
   docker compose --profile factory run --rm dark-factory whoami
   # Expected: factory

   docker compose --profile factory run --rm dark-factory id
   # Expected: uid=1000(factory) gid=1000(factory) groups=1000(factory)
   ```

3. Verify all tools accessible on PATH as `factory` user (no `command not found`):

   ```bash
   docker compose --profile factory run --rm dark-factory sh -c \
     "bun --version && archon --version && claude --version && gh --version && docker version --format '{{.Client.Version}}'"
   # Expected: version strings for each of the five tools, exit 0
   ```

4. Verify `$HOME` resolves to `/home/factory` (not `/root`), so `ARTIFACTS_DIR` is correct:

   ```bash
   docker compose --profile factory run --rm dark-factory sh -c \
     "echo HOME=\$HOME; ls /home/factory/"
   # Expected: HOME=/home/factory; directory listing shows no permission errors
   ```

5. Verify `/workspace` is writable as `factory`:

   ```bash
   docker compose --profile factory run --rm dark-factory sh -c \
     "touch /workspace/.smoke-test && rm /workspace/.smoke-test && echo OK"
   # Expected: OK
   ```

6. Verify `/opt/dark-factory` is writable (scheduler provisions `.archon/.env` here at startup):

   ```bash
   docker compose --profile factory run --rm dark-factory sh -c \
     "touch /opt/dark-factory/.smoke-test && rm /opt/dark-factory/.smoke-test && echo OK"
   # Expected: OK
   ```

**Checkpoint:** All six commands must exit 0 before continuing. If any fail, stop and investigate the Dockerfile layer before proceeding to Task 4.

---

## Task 4: Smoke-Test `backlog-scheduler` Service (Manual)

**Type:** Manual — requires rebuilt image and Docker host access
**Files:** None (verification only)

**Pre-condition:** All Task 3 smoke checks passed.

### Steps

1. Start the backlog-scheduler service in the background:

   ```bash
   docker compose --profile scheduler up -d backlog-scheduler
   ```

2. Wait 5 seconds, then verify it has not crashed:

   ```bash
   sleep 5
   docker compose --profile scheduler ps backlog-scheduler
   # Expected: status = "running" (not "exited")

   docker compose --profile scheduler logs backlog-scheduler | head -20
   # Expected: scheduler initializes, provisions .archon/.env, enters dispatch loop
   # No "Permission denied", "No such file or directory", or "exec format error" lines
   ```

3. Verify scheduler runs as `factory` user (not `root`):

   ```bash
   docker compose --profile scheduler exec backlog-scheduler whoami
   # Expected: factory
   ```

4. Verify `/var/lib/dark-factory` is writable (scheduler_state named volume):

   ```bash
   docker compose --profile scheduler exec backlog-scheduler sh -c \
     "touch /var/lib/dark-factory/.smoke-test && rm /var/lib/dark-factory/.smoke-test && echo OK"
   # Expected: OK
   ```

**Checkpoint:** All four commands must pass before proceeding to Task 5.

---

## Task 5: Pull Image on Host and Revert CI Flag

**Type:** Split — pull is manual (host side); CI revert is automated (implement agent)
**Files:** `.github/workflows/ci-publish.yml`

### Steps

1. (Manual) Pull the rebuilt image for any profile not yet updated:

   ```bash
   docker compose pull dark-factory
   docker compose pull backlog-scheduler
   # Expected: both services confirm "latest" or print "Image is up to date"
   ```

2. Remove the temporary `no-cache: true` line from the CI workflow, restoring the original step (`.github/workflows/ci-publish.yml`, lines 95–102):

   ```yaml
   # .github/workflows/ci-publish.yml
   # build-dark-factory job — restore: remove the no-cache line

         - name: Build and push dark-factory image
           uses: docker/build-push-action@v6
           with:
             context: .
             file: ./dark-factory/Dockerfile
             push: true
             tags: ${{ steps.meta.outputs.tags }}
             labels: ${{ steps.meta.outputs.labels }}
   ```

3. Confirm the `no-cache` line is gone:

   ```bash
   grep -n "no-cache" .github/workflows/ci-publish.yml
   # Expected: no output
   ```

4. Commit the revert:

   ```bash
   git add .github/workflows/ci-publish.yml
   git commit -m "ci: revert no-cache flag after verified factory user rebuild (closes #261)

   Smoke tests passed: factory user uid=1000, all tools on PATH, /workspace and
   /opt/dark-factory writable, backlog-scheduler starts as factory and writes to
   /var/lib/dark-factory."
   ```

5. Verify final state:

   ```bash
   git log --oneline -2
   # Expected: the revert commit + the earlier no-cache add commit

   grep -n "no-cache" .github/workflows/ci-publish.yml
   # Expected: no output (clean revert)
   ```
