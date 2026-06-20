# dark-factory-ops.md — BuildKit/Preview Memory Entries (Scope Spillover from #436) — Design

**Date:** 2026-06-20
**Status:** Approved (design) — pending implementation verification
**Author:** Brainstormed with Claude (Sonnet 4.6)
**Closes:** #517

## Problem

During implementation of issue #436 (fixing the BuildKit 403 / EXEC:0 double-wall that
blocked all preview stacks), the factory's standard memory-upkeep phase wrote three new
`[PATTERN]` entries to `.archon/memory/dark-factory-ops.md` and dropped three stale entries.
The #436 issue body did not list memory upkeep as an explicit deliverable.

The OOS gate detected the diff as out-of-scope relative to #436's spec and attempted
excision, but skipped it because the memory commit was the only change on the recovery branch
— excising would have produced an empty branch and lost the lessons permanently. Issue #517
was filed automatically to retroactively spec these changes.

## Goal

Produce a formal spec that:
1. Acknowledges the three BuildKit/preview patterns added during #436 as correct, expected
   factory memory-phase output.
2. Documents the three stale entries that were dropped.
3. Sets expectations for the implement agent: verify, do not modify.

## Non-Goals

- Adding any new entries to `dark-factory-ops.md` (the work is already on `main`).
- Changing the memory file structure, header, or provisional section.
- Modifying any implementation files in the factory pipeline.
- Prescribing future memory-upkeep process changes (out of scope for this ticket).

## Current State (as merged in PR #519)

The three BuildKit/preview `[PATTERN]` entries are already present in
`.archon/memory/dark-factory-ops.md` under the `## Preview Stack` heading:

### Added entries (issue:#436, date:2026-06-14, expires:2026-12-14)

1. **BuildKit build path**: Preview builds must use
   `docker buildx build --builder remote tcp://buildkit:1234 --load` (not
   `compose up --build`). The HAProxy socket proxy cannot forward BuildKit's gRPC HTTP
   connection-hijack → 403 on any `--build` over the proxy. A dedicated `moby/buildkit`
   sidecar on `factory-network` exposed over plain TCP is the only proxy-compatible build
   path. `--load` imports via `POST /images/load` (allowed: `POST:1 IMAGES:1`).

2. **Migrate service entrypoint override**: The preview `migrate` service must override
   the backend entrypoint (`entrypoint: ["python","-m","alembic","upgrade","head"]`) because
   `backend/entrypoint.sh` runs `alembic check` under `set -e` and fails on an unmigrated DB.
   `backend` and `celery-worker` must declare
   `depends_on: { migrate: { condition: service_completed_successfully } }` to avoid
   crash-looping before the schema exists.

3. **Health polling via docker inspect**: Poll preview backend health via
   `docker inspect --format '{{.State.Health.Status}}' <container>` (allowed: `CONTAINERS:1`)
   instead of `docker exec` (`EXEC:0` on the socket proxy). Switch from `compose exec` for
   any health/bootstrap check inside the factory preview stack.

### Dropped entries (stale/duplicate, removed in same commit)

1. `[AVOID]` "Do not embed data directly in Alembic migration files…" — bootstrap entry,
   had already expired (expiry: 2026-06-02).

2. `[PATTERN]` "When an out-of-scope defect is noticed during implementation, write it to
   `$ARTIFACTS_DIR/out-of-scope.md`…" — from issue #206, under a now-removed
   `## Scope Enforcement` heading; superseded by the gate_lib.sh approach.

3. `[PATTERN]` "When a refinement plan specifies exact line numbers or file counts…" — from
   issue #171, under a now-removed `## Plan Drift` heading; low-signal, not referenced
   since initial write.

## Approach

**Documentation only — no code changes.**

The implement agent must:
1. Confirm the three `[PATTERN]` entries are present in
   `.archon/memory/dark-factory-ops.md` with correct `issue:#436 date:2026-06-14
   expires:2026-12-14 source:implement` metadata.
2. Confirm the three stale entries are absent.
3. Make no modifications to the memory file (it is marked "Do not edit manually" in its
   header and is maintained by implement agents through the standard memory phase, not by
   direct hand-editing during a separate ticket).
4. Confirm the `[INVALID]` entry referencing issue #379 (the old factory proxy / `EXEC:1`
   note) is **not** one of the three dropped entries and must not be touched.
5. If all four checks pass, close the ticket with no commits.

## Alternatives Considered

**A. Re-write the memory entries as part of this ticket**
Rejected. The entries are already on `main` and correct. Re-writing them would create a
confusing history and risk introducing drift from the actual implementation in #436.

**B. Retroactively update the #436 spec to list memory upkeep**
Rejected. The #436 spec is a historical artifact; retroactive edits to merged specs reduce
traceability. The scope-spillover ticket (#517) is the correct mechanism for this.

**C. Treat this as a process issue and add a spec guard requiring future issues to list memory upkeep**
Out of scope for v1 — a separate improvement ticket if desired.

## Open Questions

None blocking.

## Assumptions

- PR #519 (commit `92207ab`, "memory: lessons from issue #436") is confirmed merged to
  `main`. The implement agent should verify `git log main --oneline --grep="#436"` or check
  for the three entries directly in the file.
- The `[INVALID]` entry at the bottom of `dark-factory-ops.md` (factory proxy / #379) is
  unrelated to this ticket and was present before #436.
