# Plan: Document Root-User Exception in Dockerfile.forecast (issue #329)

**Date**: 2026-06-20
**Issue**: [#329](https://github.com/omniscient/markethawk/issues/329) — docs(docker): document root-user exception in Dockerfile.forecast
**Spec**: [docs/superpowers/specs/2026-06-12-forecast-dockerfile-root-user-design.md](../specs/2026-06-12-forecast-dockerfile-root-user-design.md)

## Goal

Two-file documentation fix: add an inline comment to `backend/Dockerfile.forecast` explaining the intentional root-user choice, and add a Container Users table to `ARCHITECTURE.md` making the exception explicit to operators and reviewers.

## Architecture

Pure documentation change. No code, no migrations, no tests. The two affected files are:
- `backend/Dockerfile.forecast` — build instruction file for the forecasting Celery worker
- `ARCHITECTURE.md` — top-level architecture reference read by operators and code reviewers

## Tech Stack

N/A — markdown and Dockerfile only.

## File Structure

| File | Change |
|------|--------|
| `backend/Dockerfile.forecast` | Add inline comment explaining root-user rationale |
| `ARCHITECTURE.md` | Add "Container Users" subsection after the Service Topology diagram |

---

## Task 1: Add inline comment to `backend/Dockerfile.forecast`

**Files**: `backend/Dockerfile.forecast`

**Implementation note**: The inline comment was added in commit 72a5cd2 (merged to main), reverted by scope enforcement in `caa6485`, and is being re-added as the subject of this issue. The comment may already be present on the current branch if re-applied prior to this task; verify before writing.

### Steps

1. **Verify current state**

   ```bash
   grep -n "Runs as root" backend/Dockerfile.forecast
   ```

   Expected output (if already present):
   ```
   18:# Runs as root intentionally: HuggingFace model weights (~800 MB) are cached at
   ```

2. **If the comment is absent**, add it before the `CMD` line:

   Insert the following block immediately before the final `CMD` instruction:

   ```dockerfile
   # Runs as root intentionally: HuggingFace model weights (~800 MB) are cached at
   # /root/.cache/huggingface via the timesfm_cache named volume. Converting to a
   # non-root user requires relocating the cache path; tracked in a follow-up issue.
   ```

   Target location: `backend/Dockerfile.forecast`, before the final line:
   ```
   CMD ["celery", "-A", "app.core.celery_app:celery_app", "worker", "-Q", "forecasting", "--concurrency=1", "--loglevel=info"]
   ```

3. **Verify the final Dockerfile looks like**:

   ```dockerfile
   FROM python:3.12-slim

   WORKDIR /app

   RUN apt-get update && apt-get install -y \
       gcc \
       g++ \
       libpq-dev \
       && rm -rf /var/lib/apt/lists/*

   COPY requirements.txt .

   RUN pip install --upgrade pip && \
       pip install --no-cache-dir -r requirements.txt && \
       pip install --no-cache-dir "timesfm[torch]"

   COPY . .

   # Runs as root intentionally: HuggingFace model weights (~800 MB) are cached at
   # /root/.cache/huggingface via the timesfm_cache named volume. Converting to a
   # non-root user requires relocating the cache path; tracked in a follow-up issue.

   CMD ["celery", "-A", "app.core.celery_app:celery_app", "worker", "-Q", "forecasting", "--concurrency=1", "--loglevel=info"]
   ```

4. **Commit** (only if file was modified in this task):

   ```bash
   git add backend/Dockerfile.forecast
   git commit -m "docs(#329): add root-user rationale comment to Dockerfile.forecast"
   ```

   Expected: commit succeeds. If the file was already correct, skip this commit.

---

## Task 2: Add "Container Users" table to `ARCHITECTURE.md`

**Files**: `ARCHITECTURE.md`

**Implementation note**: This section may already be present on the branch (added in commit 57afcc0). Verify before writing.

### Steps

1. **Verify current state**

   ```bash
   grep -n "Container Users" ARCHITECTURE.md
   ```

   Expected output (if already present):
   ```
   84:### Container Users
   ```

2. **If the section is absent**, locate the insertion point — after the closing ` ``` ` of the Service Topology Mermaid diagram and before the `## Scan Execution Flow` heading.

   In `ARCHITECTURE.md`, find this line:
   ```
       forecastworker --> redis
   ```
   Then the closing:
   ````
   ```
   ````
   followed immediately by:
   ```
   ## Scan Execution Flow
   ```

3. **Insert** the following block between the closing ` ``` ` and `## Scan Execution Flow`:

   ```markdown
   ### Container Users

   All containers run as a non-root user except `forecast-worker`:

   | Image | User | Note |
   |-------|------|------|
   | `backend`, `celery-worker`, `celery-beat`, `live-scanner` | `appuser` (UID 1000) | Standard policy |
   | `forecast-worker` | `root` | HuggingFace/TimesFM weights (~800 MB) are cached at `/root/.cache/huggingface` via the `timesfm_cache` named volume; converting to non-root requires relocating the cache path and is tracked as a separate follow-up |
   ```

4. **Verify the section reads correctly**:

   ```bash
   grep -A 8 "### Container Users" ARCHITECTURE.md
   ```

   Expected:
   ```
   ### Container Users

   All containers run as a non-root user except `forecast-worker`:

   | Image | User | Note |
   |-------|------|------|
   | `backend`, `celery-worker`, `celery-beat`, `live-scanner` | `appuser` (UID 1000) | Standard policy |
   | `forecast-worker` | `root` | HuggingFace/TimesFM weights (~800 MB) are cached at `/root/.cache/huggingface` via the `timesfm_cache` named volume; converting to non-root requires relocating the cache path and is tracked as a separate follow-up |
   ```

5. **Commit** (only if file was modified in this task):

   ```bash
   git add ARCHITECTURE.md
   git commit -m "docs(#329): add Container Users table to ARCHITECTURE.md"
   ```

   Expected: commit succeeds. If the file was already correct (section added by commit 57afcc0 on this branch), skip this commit.

---

## Task 3: Validate and finalize

**Files**: none (verification only)

### Steps

1. **Confirm branch state**

   ```bash
   git log --oneline origin/main..HEAD
   ```

   Expected: at least one commit visible (the spec commit or a docs commit from Tasks 1–2).

2. **Confirm no unintended changes**

   ```bash
   git diff origin/main...HEAD --name-only
   ```

   Expected: only `ARCHITECTURE.md`, `backend/Dockerfile.forecast` (if modified), and `docs/superpowers/specs/2026-06-12-forecast-dockerfile-root-user-design.md` (spec file from refine).

   If any backend Python files or frontend files appear in the diff, do NOT proceed — investigate and revert any out-of-scope changes.

3. **Spot-check the Dockerfile comment text exactly**

   The comment must match the spec verbatim (three-line block):
   ```
   # Runs as root intentionally: HuggingFace model weights (~800 MB) are cached at
   # /root/.cache/huggingface via the timesfm_cache named volume. Converting to a
   # non-root user requires relocating the cache path; tracked in a follow-up issue.
   ```

4. **Spot-check the ARCHITECTURE.md table is positioned correctly**

   ```bash
   grep -n "Container Users\|Scan Execution Flow\|forecastworker --> redis" ARCHITECTURE.md
   ```

   Expected order: `forecastworker --> redis` line, then (a few lines later) `Container Users`, then (later) `Scan Execution Flow`. The table must be between the topology diagram and the Scan Execution Flow heading.

5. **No further commits needed.** This is a documentation-only change; there are no tests to run and no backend reload required.
