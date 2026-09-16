# Plan: ARCHITECTURE.md BuildKit Subgraph Acceptance — Issue #516

**Date:** 2026-06-20
**Goal:** Formally accept the existing ARCHITECTURE.md buildkit service documentation as correct and in-scope, closing the scope-spillover record created when issue #436's OOS excision was skipped.
**Architecture:** No runtime or code changes. Pure verification and formal acceptance.
**Tech Stack:** `ARCHITECTURE.md` (Mermaid diagram), `docker-compose.yml`

---

## Background

During issue #436 (remote BuildKit daemon for factory preview builds), the dark factory added a `buildkit` node and a `darkfactory → buildkit` edge to the factory-network subgraph in `ARCHITECTURE.md`. The OOS gate attempted to excise this documentation change but skipped excision because removing it would have left the branch empty. The changes merged to main. Issue #516 formally validates that documentation as correct and closes the scope-enforcement record.

**No code or documentation changes are required.** The plan's tasks are verification steps that produce a recorded acceptance decision.

---

## File Structure

| File | Change |
|---|---|
| `docs/superpowers/specs/2026-06-20-architecture-buildkit-subgraph-design.md` | Already committed — formal acceptance spec (no edits needed) |
| `ARCHITECTURE.md` | Read-only verification (no edits needed) |
| `docker-compose.yml` | Read-only verification (no edits needed) |

---

## Task 1 — Verify buildkit node in ARCHITECTURE.md factory-network subgraph (R1)

**Files:** `ARCHITECTURE.md` (lines 33–39), `docker-compose.yml` (lines 574–585)

**Verification steps:**

1. Read `ARCHITECTURE.md` lines 33–39 and confirm the factory-network subgraph contains exactly:
   ```
   buildkit["buildkit :1234 (factory/scheduler profiles)"]
   ```
   Expected location: inside `subgraph factory["factory-network"]`.

2. Read `docker-compose.yml` lines 574–585 and confirm the `buildkit` service:
   - Image: `moby/buildkit:v0.31.0@sha256:...`
   - Port binding: `--addr tcp://0.0.0.0:1234`
   - Profiles: `factory`, `scheduler`
   - Network: `factory-network`

3. Confirm the diagram label matches: profile membership (`factory/scheduler`) and port (`:1234`) are accurate.

4. Run:
   ```bash
   grep -n "buildkit" ARCHITECTURE.md
   grep -n "buildkit" docker-compose.yml
   ```
   Expected output from `ARCHITECTURE.md`:
   ```
   38:        buildkit["buildkit :1234 (factory/scheduler profiles)"]
   81:    darkfactory -->|"buildx tcp :1234"| buildkit
   ```
   Expected output from `docker-compose.yml`:
   ```
   570:  # Remote BuildKit daemon...
   574:  buildkit:
   575:    image: moby/buildkit:v0.31.0@sha256:...
   579:    command: --addr tcp://0.0.0.0:1234
   581:      - buildkit_cache:/var/lib/buildkit
   605:      - buildkit
   761:  buildkit_cache:
   ```

5. **Acceptance criterion:** diagram label, port, and profile membership all match `docker-compose.yml`. R1 satisfied.

**Commit:** No commit required — read-only verification.

---

## Task 2 — Verify no `scheduler → buildkit` edge needed (R2)

**Files:** `docker-compose.yml` (`backlog-scheduler` service section, lines ~618–650)

**Verification steps:**

1. Read `docker-compose.yml` `backlog-scheduler` `depends_on` block and confirm it lists only `docker-socket-proxy-scheduler` — **not** `buildkit`.

2. Run:
   ```bash
   grep -A 15 "backlog-scheduler:" docker-compose.yml | grep -E "depends_on|buildkit|docker-socket"
   ```
   Expected output:
   ```
   depends_on:
     - docker-socket-proxy-scheduler
   ```
   No `buildkit` entry should appear.

3. Confirm the rationale: the `backlog-scheduler` container **dispatches** per-issue factory run containers, but the scheduler process itself never opens a connection to the buildkit daemon. Buildkit is included in the `scheduler` profile so the daemon is running when dispatch happens — but this is a startup ordering dependency, not a runtime connection.

4. Confirm `ARCHITECTURE.md` line 82 shows only `scheduler -->|"tcp :2375"| proxyscheduler` (proxy connection), with no `scheduler --> buildkit` edge.

5. **Acceptance criterion:** no `buildkit` in `backlog-scheduler.depends_on`; no `scheduler → buildkit` edge in the diagram. R2 satisfied.

**Commit:** No commit required — read-only verification.

---

## Task 3 — Verify no additional prose section needed in ARCHITECTURE.md (R3)

**Files:** `ARCHITECTURE.md`, `docker-compose.yml` (lines 567–573 comment block)

**Verification steps:**

1. Read `docker-compose.yml` lines 567–573 and confirm the comment already contains the technical rationale:
   ```
   # Remote BuildKit daemon — lets factory preview builds run WITHOUT the docker.sock
   # connection-hijack that the socket-proxy blocks (BuildKit's gRPC build session needs
   # an HTTP upgrade the HAProxy proxy can't forward → 403, see #436). The per-issue run
   # container builds with `docker buildx build --builder remote tcp://buildkit:1234 --load`,
   # which talks to this daemon directly over TCP (never the proxied socket) and then loads
   # the result into dockerd via POST /images/load (allowed: POST:1, IMAGES:1). No host port
   # is published — it is reachable only from inside factory-network.
   ```

2. Confirm `ARCHITECTURE.md` contains no existing buildkit prose section (other than the Mermaid diagram lines).

3. Run:
   ```bash
   grep -c "buildkit" ARCHITECTURE.md
   ```
   Expected output: `2` (the node definition at line 38 and the edge at line 81).

4. **Acceptance criterion:** rationale lives in docker-compose.yml adjacent to the service definition; only topology (node + edge) in `ARCHITECTURE.md`; no duplication. R3 satisfied.

**Commit:** No commit required — read-only verification.

---

## Task 4 — Confirm spec commitment and close issue (R4)

**Files:** `docs/superpowers/specs/2026-06-20-architecture-buildkit-subgraph-design.md`

**Steps:**

1. Confirm the spec file is committed on the current branch:
   ```bash
   git log --oneline main..HEAD
   ```
   Expected output:
   ```
   9608412 docs(spec): ARCHITECTURE.md buildkit subgraph validation — closes #516
   ```

2. Confirm the spec file exists and is tracked:
   ```bash
   git show HEAD --name-only | head -5
   ```
   Expected: `docs/superpowers/specs/2026-06-20-architecture-buildkit-subgraph-design.md` listed.

3. The `closes #516` trailer in the commit message will auto-close the issue when this branch merges to main.

4. **Acceptance criterion:** spec is committed; issue will close on merge. R4 satisfied.

**Commit:** Spec already committed at `9608412`. This plan file to be committed separately.

---

## Summary

All four requirements (R1–R4) are satisfied by the current state of the codebase:
- `ARCHITECTURE.md` already accurately documents the buildkit service and `darkfactory → buildkit` edge.
- No `scheduler → buildkit` edge is needed or present (confirmed by `backlog-scheduler.depends_on`).
- No additional prose is needed (rationale lives in `docker-compose.yml`).
- The spec file is committed with a `closes #516` trailer.

This plan authorizes the existing committed content as in-scope and formally closes the scope-spillover record for issue #436's OOS excision bypass.
