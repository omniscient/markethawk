# Backend Non-Root appuser — Design

**Date:** 2026-06-12
**Status:** Already implemented — issue can close as resolved

## Overview

Issue #258 filed a defect from scope enforcement on #202: the backend container was running as
root, and a dedicated `appuser` (uid/gid 1000) with `COPY --chown` and `USER appuser` was
needed to harden against privilege escalation.

**Finding:** The defect no longer exists. The implementation is already in `main` and the gate
issue (#266) has been closed confirming correctness. No code changes are required.

## Context

When #258 was filed the comment noted: *"⚠️ Gated by #266 (investigate why non-root setup was
removed) before re-adding appuser."* Issue #266 closed with the finding:

> "The non-root user setup for all three containers (backend: `appuser`, frontend: `node`,
> dark-factory: `factory`) is already correctly in place from prior work."

Two commits on `main` delivered the backend implementation:
- `9b60377` — `feat(security): run backend container as non-root appuser (UID 1000)` — adds
  group/user, `COPY --chown`, and `USER appuser`
- `b1adb7f` — `fix(docker): make prometheus_multiproc dir writable by non-root appuser` — adds
  `mkdir /tmp/prometheus_multiproc && chown appuser:appuser` so the non-tmpfs named volume is
  initialized with the correct ownership

## Requirements

1. Backend container process must not run as root (uid 0).
2. `appuser` must own all application files so no elevated privileges are needed at runtime.
3. Prometheus multiprocess metrics dir (`/tmp/prometheus_multiproc`) must be writable by
   `appuser` — the named Docker volume is initialized with the image's directory ownership, so
   the dir must be pre-created and chowned in the Dockerfile before `USER appuser`.
4. Celery-worker and live-scanner, which share the same image, must also inherit the non-root
   user without additional changes.

## Current Implementation

`backend/Dockerfile` satisfies all four requirements:

```dockerfile
RUN addgroup --system --gid 1000 appuser \
 && adduser --system --uid 1000 --ingroup appuser --no-create-home appuser

RUN mkdir -p /tmp/prometheus_multiproc \
 && chown appuser:appuser /tmp/prometheus_multiproc

COPY --chown=appuser:appuser . .

USER appuser
```

All three services that use this image — `backend`, `celery-worker`, `live-scanner` — inherit
`USER appuser` without further compose-level changes.

## Approach

No code changes. Close issue #258 as "already resolved" after confirming via the verification
checklist below.

## Alternatives Considered

**A. Re-apply the Dockerfile changes** — Produces a no-op or a merge conflict; the lines are
already present. Rejected.

**B. Add broader runtime hardening** (read-only filesystem, `cap_drop`, `no-new-privileges`,
seccomp profiles) — Meaningful hardening, but out of scope for #258 which is specifically
about running as non-root. These belong in separate tickets under epic #272 (Container &
deployment security hardening).

## Verification Checklist

Before closing the issue, confirm the following manually:

```bash
# Confirm backend runs as uid=1000
docker compose run --rm backend id
# Expected: uid=1000(appuser) gid=1000(appuser) groups=1000(appuser)

# Confirm celery-worker runs as uid=1000
docker compose run --rm celery-worker id
# Expected: uid=1000(appuser) gid=1000(appuser) groups=1000(appuser)

# Confirm live-scanner runs as uid=1000
docker compose run --rm live-scanner id
# Expected: uid=1000(appuser) gid=1000(appuser) groups=1000(appuser)
```

## Open Questions

None — the implementation is complete and the gate investigation (issue #266) is closed.

## Assumptions

- The `prometheus_multiproc` named volume is correctly initialized by Docker using the
  directory ownership embedded in the image. This was fixed in `b1adb7f` and validated in the
  #266 investigation.
- `backend/Dockerfile.forecast` intentionally runs as root (HuggingFace cache at
  `/root/.cache/huggingface`); this exception is documented in that file and tracked as a
  separate follow-up under epic #272.
