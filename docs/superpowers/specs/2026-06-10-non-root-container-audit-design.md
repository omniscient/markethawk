# Non-Root Container Audit — Design

**Date:** 2026-06-10
**Status:** Ready for implementation
**Author:** Brainstormed with Claude (Opus 4.8)
**Issue:** #266

## Problem

During issue #202 (security cookies), the dark factory implemented non-root user
setup for all three application Dockerfiles as a side-effect of its work, then
the conformance gate excised those changes as out-of-scope. A subsequent "restore"
pass by the same gate re-added the non-root users. The net result is that non-root
users are now correctly in place for `backend`, `frontend`, and `dark-factory` —
but the process surfaced a real unresolved permission gap: the `backlog-scheduler`
service mounts a named volume at `/var/lib/dark-factory` for retry-state persistence,
yet the `dark-factory/Dockerfile` never pre-creates that directory with `factory`
user ownership, causing the scheduler to crash immediately on startup when it tries
to write `scheduler-state.json` under `set -euo pipefail`.

## Goal

1. Fix the `scheduler_state` volume write-permission bug so `backlog-scheduler`
   can start and persist retry state correctly.
2. Document the deliberate root-user exception for `backend/Dockerfile.forecast`
   (the timesfm ML worker) so the decision is explicit and not re-filed as drift.
3. Confirm all containers start with the expected non-root user (manual verification
   checklist on the PR).

## Non-Goals

- Adding Dockerfile-lint or CI guardrails for non-root enforcement (worthwhile
  follow-up, but new tooling exceeds a `direct-to-pr` chore — file separately).
- Converting `Dockerfile.forecast` to non-root (the HuggingFace cache path and
  model-download permissions require a more involved change; left for a dedicated
  issue).
- Changes to `docker-compose.override.yml` bind-mounts (read-only mounts are
  unaffected by user; existing `:ro` flag is correct).

## Root Cause

When Docker mounts a named volume at a path that does **not** exist in the image,
it creates the mountpoint directory owned by `root:root` with mode `0755`
(rwx for owner, r-x for everyone else). The `factory` user (uid 1000) can read
the directory but cannot create files inside it.

The `backend/Dockerfile` already demonstrates the correct pattern for this problem:
```dockerfile
RUN mkdir -p /tmp/prometheus_multiproc \
 && chown appuser:appuser /tmp/prometheus_multiproc
```
When the image contains the target directory pre-owned by the app user, Docker
uses that ownership to initialize the named volume on first mount. Subsequent
container restarts use the already-initialized volume as-is.

## Approach

### 1. Fix `dark-factory/Dockerfile` (primary change)

Add one `RUN` instruction before the `USER factory` switch, immediately after the
existing `/workspace` ownership transfer:

```dockerfile
# Scheduler state dir — named volume (scheduler_state) mounts here.
# Pre-created with factory ownership so Docker initializes the volume writable.
RUN mkdir -p /var/lib/dark-factory \
 && chown factory:factory /var/lib/dark-factory
```

Placement: after `RUN chown -R factory:factory /workspace` (line 85), before
`USER factory` (line 90 currently). This matches the exact pattern used in
`backend/Dockerfile` for `prometheus_multiproc`.

No changes to `docker-compose.yml` or `scheduler.sh` are required — the volume
mount path and the script's `SCHEDULER_STATE_DIR` default are already correct.

### 2. Document `Dockerfile.forecast` root exception

Add a comment to `backend/Dockerfile.forecast` noting the intentional root-user
choice:

```dockerfile
# Runs as root: HuggingFace model weights (~800 MB) are cached at
# /root/.cache/huggingface via the timesfm_cache named volume. Converting to
# a non-root user requires relocating the cache path; tracked in a follow-up issue.
```

This prevents the conformance gate or future reviewers from filing this as drift.

## Alternatives Considered

**Change the volume mount path to `/home/factory/dark-factory-state`** — would avoid
the Dockerfile change by mounting into a directory the factory user already owns.
Rejected: requires coordinated edits to `docker-compose.yml` and `scheduler.sh`,
and moves away from the conventional `/var/lib/<service>` location for service state.

**Use tmpfs instead of a named volume** — the scheduler state is intentionally
durable across restarts (`restart: unless-stopped`). Losing retry counters on
every restart would re-trigger all circuit-breaker logic on restart. Rejected.

## Affected Files

| File | Change |
|------|--------|
| `dark-factory/Dockerfile` | Add `mkdir /var/lib/dark-factory && chown factory` before `USER factory` |
| `backend/Dockerfile.forecast` | Add explanatory comment for root-user exception |

## Assumptions

- The `scheduler_state` named volume has never been initialized correctly (factory
  user crash on first write). If a pre-existing volume exists with root ownership,
  operators should `docker volume rm <project>_scheduler_state` once after deploying
  the fix so Docker re-initializes it from the corrected image.
- `docker-compose.preview.yml` backend services do not use the `scheduler_state`
  volume and are unaffected.

## Open Questions

- Should a follow-up issue be filed to convert `Dockerfile.forecast` to non-root
  when the HuggingFace cache relocation is addressed? (Non-blocking for this PR.)
