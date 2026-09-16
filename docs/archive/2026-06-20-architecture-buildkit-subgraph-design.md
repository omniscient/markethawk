# ARCHITECTURE.md Buildkit Subgraph — Scope Validation

Date: 2026-06-20

## Overview

During issue #436 (remote BuildKit daemon for factory preview builds), the dark factory added a
`buildkit` node and a `darkfactory → buildkit` edge to the factory-network subgraph in
`ARCHITECTURE.md`. The OOS gate tried to excise the change but skipped excision because the branch
would have been left empty. The changes merged to main. Issue #516 formally validates that
documentation as correct and in-scope.

## Problem Statement

The scope-spillover tracker requires a spec + triage decision for every OOS excision that was
skipped rather than applied. Without this ticket the excision is ambiguous — it is unclear whether
the documentation change is intentionally accepted or merely leaked through enforcement.

## Selected Approach

Accept the existing documentation as-is. No edits to `ARCHITECTURE.md` are needed.

The current factory subgraph already reflects the correct topology:

```
buildkit["buildkit :1234 (factory/scheduler profiles)"]
darkfactory -->|"buildx tcp :1234"| buildkit
```

This matches `docker-compose.yml` exactly: the `buildkit` service runs under the `factory` and
`scheduler` profiles, and the only container that directly connects to it is `dark-factory` (via
`depends_on: buildkit` and `docker buildx build --builder remote tcp://buildkit:1234`).

## Requirements

- R1: Confirm `ARCHITECTURE.md` factory-network subgraph accurately documents the buildkit service.
- R2: Confirm no `scheduler → buildkit` edge is needed.
- R3: Confirm no additional prose section about buildkit is needed in `ARCHITECTURE.md`.
- R4: Close issue #516 by committing this spec and publishing the refinement comment.

## Architecture / Approach

No code or documentation changes are required. The spec exists solely to provide the formal
acceptance record that the scope-enforcement pipeline requires when an OOS excision is skipped.

**Why no `scheduler → buildkit` edge**: The `backlog-scheduler` container's `depends_on` is
`[docker-socket-proxy-scheduler]` only. It does not open a connection to buildkit. Buildkit is
included in the `scheduler` profile so the daemon is alive when the scheduler starts (the scheduler
dispatches per-issue factory run containers that need it), but the scheduler process itself never
talks to buildkit. Adding a `scheduler → buildkit` edge would misrepresent the actual runtime
topology by implying a connection that does not exist.

**Why no prose section**: The docker-compose.yml service comment (lines 567–573) already explains
the technical rationale: "Remote BuildKit daemon — lets factory preview builds run WITHOUT the
docker.sock connection-hijack that the socket-proxy blocks (BuildKit's gRPC build session needs
an HTTP upgrade the HAProxy proxy can't forward → 403, see #436)." Duplicating this in
`ARCHITECTURE.md` would add no information for a reader of the architecture doc.

## Alternatives Considered

**Add `scheduler → buildkit` edge** — Rejected. The scheduler does not directly connect to
buildkit; adding the edge would be factually incorrect.

**Add a prose explanation of buildkit in ARCHITECTURE.md** — Rejected. The rationale already lives
in docker-compose.yml where it belongs (adjacent to the service definition). Architecture docs
document topology, not implementation rationale.

**Revert the documentation changes from main** — Rejected. The documentation is correct. Reverting
accurate, already-merged docs would reduce the quality of ARCHITECTURE.md for no benefit.

## Open Questions

None. The Q&A confirmed all three sub-questions are resolved by the current state of main.

## Assumptions

- The buildkit service definition in `docker-compose.yml` will not change profile membership or
  port in a way that invalidates the ARCHITECTURE.md diagram before this ticket closes.
- The OOS scope-enforcement pipeline considers a spec + refinement comment sufficient to formally
  close a skipped-excision spillover ticket.
