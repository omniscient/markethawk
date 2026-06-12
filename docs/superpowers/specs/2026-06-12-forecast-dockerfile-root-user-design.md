# Forecast Dockerfile Root-User Exception — Design (issue #329)

**Date**: 2026-06-12
**Issue**: [#329](https://github.com/omniscient/markethawk/issues/329) — docs(docker): document root-user exception in Dockerfile.forecast

## Problem

The `forecast-worker` container (`backend/Dockerfile.forecast`) runs as root intentionally: HuggingFace/TimesFM model weights (~800 MB) are cached at `/root/.cache/huggingface` via the `timesfm_cache` named volume. This was an undocumented exception to the project's non-root container policy (the main `backend/Dockerfile` runs as `appuser` UID 1000).

The documentation gap was noticed during issue #276 implementation. The inline comment was added in commit 72a5cd2, reverted by scope enforcement (`caa6485`), and is tracked here as issue #329.

## Requirements

1. An inline comment in `backend/Dockerfile.forecast` explains why root is required, names the cache path and volume, and notes that a non-root migration is deferred.
2. `ARCHITECTURE.md` acknowledges the exception in the Service Topology section so operators and reviewers know the root-running container is intentional.
3. No changes to `DEVELOPMENT.md` or `deployment-guide.md` — the root-user choice has no developer-workflow or production-ops implications.

## Approach

### 1. Inline comment in `backend/Dockerfile.forecast`

```dockerfile
# Runs as root intentionally: HuggingFace model weights (~800 MB) are cached at
# /root/.cache/huggingface via the timesfm_cache named volume. Converting to a
# non-root user requires relocating the cache path; tracked in a follow-up issue.
```

Already present on this branch.

### 2. Container users note in `ARCHITECTURE.md`

Add a "Container Users" subsection after the Service Topology diagram, before the Scan Execution Flow section. A small table lists each image and its user, with a footnote on the forecast-worker exception.

## Alternatives Considered

**Inline comment only** — rejected. The architecture review flags root-running containers as a Docker Security concern (2/5); making the exception explicit in `ARCHITECTURE.md` turns an apparent oversight into a documented design choice.

**Full doc sweep (DEVELOPMENT.md + deployment-guide.md)** — rejected. The root-user choice has no developer-workflow or production-ops implications; notes in those files would be noise.

**Migrate forecast-worker to non-root immediately** — out of scope. Migrating requires setting `HF_HOME` to a non-root path and validating TimesFM model loading. That is a separate effort and tracked as a follow-up.

## Open Questions

None blocking.

## Assumptions

- "Tracked in a follow-up issue" in the Dockerfile comment refers to a future non-root migration issue, not this issue (which is documentation-only).
- The architecture review's Docker Security score (2/5) is not expected to improve from this change alone; the root exception itself is not being remediated here.
