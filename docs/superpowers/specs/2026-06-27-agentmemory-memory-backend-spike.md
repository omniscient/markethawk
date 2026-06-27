# Memory Backend Spike — Evaluate agentmemory with existing .archon data

**Status:** spike
**Date:** 2026-06-27
**Epic:** #643 (Dark Factory memory system)
**Issue:** #644
**Size:** S (< 1 hour)

> **AVOID under test:** `.archon/memory/architecture.md` entry — "Do not introduce a vector
> database, embedding model, or semantic search service for memory retrieval. At the scale of
> this codebase (< 200 memory entries) flat file reading is faster and more predictable than a
> retrieval pipeline." (`source:refine`, `expires:2026-12-02`)
>
> This spike is the designated input for the 2026-12-02 renewal decision. A negative
> recommendation ("flat files win, AVOID stands") is an equally successful outcome.

## Problem

The current Dark Factory memory system stores entries as plain markdown in `.archon/memory/*.md`
files (five files, ~28 active entries as of 2026-06-27). Phase 1 LOAD in `entrypoint.sh` reads
them with shell `while read` loops, filters by `path:` tags, and skips `[PROVISIONAL]` / `[INVALID]`
entries. This is fast and human-readable, but it lacks structured indexing: querying "all entries
that touch `backend/app/services/`" requires a grep over free-text comment tags rather than an
indexed lookup, and there is no way to run a semantic "find memories similar to X" query.

`rohitg00/agentmemory` is an HTTP memory API that offers exact, semantic, path-scoped, project-scoped,
and role-scoped retrieval. Epic #643 explores whether adopting it would improve the factory's
memory loading latency, retrieval precision, or developer ergonomics — or whether the overhead is
unjustified at the current entry count.

This spike runs the evaluation **without changing any production Dark Factory behavior.** All
five retrieval modes are exercised so the verdict is based on evidence, not assumption.

## Requirements

From Q&A (issues/644 brainstorming):

1. A runnable eval script (`dark-factory/scripts/eval_agentmemory.sh`) that can be re-run to reproduce results.
2. An optional `docker-compose.yml` profile (`agentmemory-spike`) that starts agentmemory without affecting the default stack.
3. At least 5 representative memories imported from `.archon/memory/dark-factory-ops.md` and `codebase-patterns.md`.
4. All five retrieval modes exercised: **exact**, **semantic**, **path-scoped**, **project-scoped**, **role-scoped**.
5. Agent role scoping tested with at least two role IDs (e.g. `refine`, `implement`).
6. Project scope must use `project=markethawk` (stable), not filesystem paths.
7. Outage/unavailable fallback behavior documented — what happens if the agentmemory service is down when a factory run starts.
8. Install/start/health-check commands documented.
9. Latency, startup time, auth method, and developer ergonomics documented.
10. Zero production Dark Factory behavior changes — no edits to `scheduler.sh`, `entrypoint.sh`, `.archon/memory/*.md`, or any factory DAG node.

## Approach

### Compose integration — Profile A (chosen)

Add `agentmemory` as a **profile-gated service** in `docker-compose.yml`:

```yaml
agentmemory:
  image: rohitg00/agentmemory:latest   # confirm tag from upstream repo
  container_name: agentmemory
  profiles: [agentmemory-spike]
  ports:
    - "127.0.0.1:6789:8000"            # confirm internal port from upstream docs
  environment:
    - AGENTMEMORY_PROJECT=markethawk
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/agentmemory/health"]
    interval: 10s
    timeout: 5s
    retries: 3
  networks:
    - stockscanner-network
```

This follows the existing `profiles:` pattern used for `factory`, `scheduler`, `tls`, and
`forecasting` services. The service never starts in a default `docker compose up -d` and adds
no operational overhead.

To start just this service:
```bash
docker compose --profile agentmemory-spike up -d agentmemory
docker compose --profile agentmemory-spike ps agentmemory   # verify running
```

### Why not the alternatives

- **Standalone `docker run`** (Approach B): simpler, but loses compose networking and makes
  the eval less reproducible for other developers who follow the compose-first workflow.
- **Separate `docker-compose.agentmemory.yml`** (Approach C): completely isolated but
  non-standard for this repo; the `profiles:` pattern is the established convention and
  doesn't require a separate file invocation.

## Procedure

### Step 1 — Verify agentmemory setup

Look up the current `rohitg00/agentmemory` release on GitHub to confirm:
- Docker image name and tag
- Actual internal HTTP port (update the compose snippet above if different from 8000)
- Auth mechanism (API key? None? Header format?)
- Available endpoints (especially health probe and memory CRUD)

Update `docker-compose.yml` with the confirmed values, then:

```bash
docker compose --profile agentmemory-spike up -d agentmemory
curl -s http://localhost:6789/agentmemory/health | python -m json.tool
```

Expected: HTTP 200, some JSON health payload.

### Step 2 — Run the eval script

```bash
bash dark-factory/scripts/eval_agentmemory.sh
```

The script (to be committed as part of this spike):
1. Health-checks the agentmemory service and exits 1 if unhealthy.
2. Imports 5+ representative memories from `.archon/memory/dark-factory-ops.md` and
   `.archon/memory/codebase-patterns.md` using the agentmemory save API.
   - Each memory gets `project=markethawk`, a `role=` tag (e.g. `refine`, `implement`), and
     a `path=` tag where the source markdown entry carries one.
3. Runs all five retrieval modes, prints structured output (JSON or table) to stdout:

   | Mode | Example query / filter |
   |------|------------------------|
   | exact | `GET /agentmemory?id=<uuid>` |
   | semantic | `POST /agentmemory/search` with a free-text query |
   | path-scoped | filter `path=backend/app/services/` |
   | project-scoped | filter `project=markethawk` |
   | role-scoped | filter `role=refine` then `role=implement` separately |

4. Measures and prints: per-query latency (ms), startup time, result count.
5. Tests agentmemory-unavailable fallback: kills the container mid-run and verifies the script
   exits with a documented error code (not silently returns garbage).

Paste the stdout output into the Results table below.

### Step 3 — Document findings

Fill in the Results section below and write the Verdict.

## Results

> **Instructions:** Run `bash dark-factory/scripts/eval_agentmemory.sh` after starting the
> profile, then fill in the table rows from its stdout output.

### Health probe

| Check | Result |
|-------|--------|
| Service start time | _TBD_ |
| `GET /agentmemory/health` status | _TBD_ |
| Auth mechanism | _TBD_ |

### Retrieval mode results

| Mode | Query / filter | Top result(s) | Latency (ms) | Correct? | Notes |
|------|---------------|---------------|--------------|----------|-------|
| exact | _TBD_ | | | | |
| semantic | _TBD_ | | | | |
| path-scoped | `path=backend/app/services/` | | | | |
| project-scoped | `project=markethawk` | | | | |
| role-scoped (refine) | `role=refine` | | | | |
| role-scoped (implement) | `role=implement` | | | | |

### Outage / unavailable behavior

> Describe what happens when the agentmemory service is down at Phase 1 LOAD:

_TBD_ — fill in after running the outage test in Step 2.5 of the eval script.

### Developer ergonomics notes

_TBD_ — e.g. setup friction, memory entry format translation, ongoing maintenance burden.

## Verdict

> Complete this section after filling in the Results table.

**Recommendation:** _TBD_ (one of: "Adopt agentmemory — AVOID should be retired" /
"Adopt with scope limit — AVOID should be amended to allow structured-only retrieval" /
"Do not adopt — AVOID stands and should be renewed at 2026-12-02")

**Reasoning:** _TBD_

**Action on AVOID entry:** _TBD_ (renew / amend / retire at 2026-12-02)

## Open questions (non-blocking)

1. What Docker image tag should be pinned in `docker-compose.yml`? (confirm from upstream)
2. Does agentmemory require persistent volume storage, or is it in-memory only? If persistent,
   a named volume should be added to the compose snippet.
3. Does semantic search require a local embedding model, or does agentmemory call an external
   API (OpenAI, etc.)? If external, a `OPENAI_API_KEY` env var must be added to the spike's
   compose profile (not the main stack).

## Assumptions

- `rohitg00/agentmemory` provides a Docker image usable via `docker compose`.
- The health probe is `GET /agentmemory/health` or equivalent — confirm and update if different.
- "Semantic queries" in the acceptance criteria means free-text similarity search, not just
  keyword filtering; both are exercised in the eval script.
- The spike does **not** wire agentmemory into the actual Phase 1 LOAD path — it only exercises
  the API in isolation.
