# Frontend Container — Non-Root Node User

**Date:** 2026-06-12  
**Status:** Draft  
**Issue:** #259

## Problem

Issue #259 was filed as a scope-spillover from #202: the `frontend/Dockerfile` was believed
to run as root and needed `chown -R node:node /app` + `USER node` added after the build step.
A human comment gated this ticket on #266 (audit why non-root was removed across all containers).

## Finding

Issue #266 completed and confirmed: `frontend/Dockerfile` **already has the non-root fix in
place**. The current file (lines 13–15) contains:

```dockerfile
RUN chown -R node:node /app
USER node
```

The fix landed in `main` independently before #266 audited — which is why #266's implementation
listed `frontend/Dockerfile` under "Files NOT changed (already fixed in main)".

## Decision

No code changes are required. The implementation step is:

1. **Verify** that the running frontend container confirms non-root:
   ```bash
   docker compose exec frontend id
   # expected: uid=1000(node) gid=1000(node) groups=1000(node)
   ```
2. **Document** the confirmation in a comment on the issue.
3. **Close** the issue as already resolved.

## Requirements

- No `frontend/Dockerfile` changes.
- No `docker-compose.yml` changes.
- Verification command above must confirm uid=node, not uid=root (0).
- No additional hardening (capability-drop, read-only rootfs, healthcheck) — those belong
  to Epic #272, not this narrowly-scoped ticket.

## Alternatives Considered

**Add a CI dockerfile-lint check (hadolint DL3002).** This would prevent future non-root
regressions across all Dockerfiles. Worthwhile, but it affects all Dockerfiles in the repo
(backend, backend/Dockerfile.forecast, dark-factory, services/) and should be its own issue
under Epic #272 rather than bolted here. Recommendation: file separately.

**Add `security_opt: [no-new-privileges:true]` and `cap_drop: [ALL]` to the frontend compose
service.** Valid additional hardening, but out of scope for a ticket whose only stated defect
was "container runs as root". File under #272.

## Open Questions

None blocking.

## Assumptions

- The `docker compose exec frontend id` check will confirm uid=1000(node). If it returns
  uid=0(root), the compose stack is running a stale image — `docker compose build frontend`
  and re-run.
