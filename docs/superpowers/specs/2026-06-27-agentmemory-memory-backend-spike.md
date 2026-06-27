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
  image: iiidev/iii:0.11.2             # confirmed: rohitg00/agentmemory uses iiidev/iii engine
  container_name: agentmemory
  command: ["--use-default-config"]    # required: no config.yaml baked; starts with defaults
  profiles:
    - agentmemory-spike
  ports:
    - "127.0.0.1:6789:3111"            # confirmed: internal REST API port is 3111
  environment:
    AGENTMEMORY_PROJECT: markethawk
    # AGENTMEMORY_SECRET: ${AGENTMEMORY_SECRET:-}  # optional bearer token
    # OPENAI_API_KEY: ${OPENAI_API_KEY:-}           # optional; built-in embeddings work without it
  volumes:
    - agentmemory_data:/data           # SQLite persistence required
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:3111/agentmemory/health"]
    interval: 10s
    timeout: 5s
    retries: 6
  networks:
    - stockscanner-network
  deploy:
    resources:
      limits:
        memory: 512M
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
| Service start time | ~8 s from `docker compose up` to engine listening (worker connects in +2 s) |
| `GET /agentmemory/health` status | **HTTP 200** — `{"status":"healthy","version":"0.9.27","health":{"connectionState":"connected",...}}` |
| Auth mechanism | None by default; optional Bearer token via `AGENTMEMORY_SECRET` env var |

### Confirmed API paths (v0.9.27)

The spec assumed paths differed from what agentmemory v0.9.27 actually serves:

| Assumed path | Actual path | Status |
|---|---|---|
| `POST /agentmemory/remember` | `POST /agentmemory/remember` | ✓ correct |
| `GET /agentmemory/{id}` | `GET /agentmemory/memories/{id}` | path differs |
| `GET /agentmemory?project=` | `GET /agentmemory/memories?project=` | path differs |
| `POST /agentmemory/smart-search` | `POST /agentmemory/smart-search` | ✓ correct |
| `GET /agentmemory?role=` | `GET /agentmemory/memories?role=` | path differs + filter ignored |

### Retrieval mode results

All 6 memories from `.archon/memory/dark-factory-ops.md` and `codebase-patterns.md` were
imported in 315 ms total (avg 52 ms each). Eval run: 2026-06-27.

| Mode | Query / filter | Top result | Latency | Correct? | Notes |
|------|---------------|------------|---------|----------|-------|
| exact | `GET /memories/mem_mqwbzs8e_...` | prometheus_multiproc pattern | 26 ms | ✓ | Full content returned |
| text search (BM25) | `POST /search` "prometheus multiprocess volume tmpfs" | prometheus_multiproc pattern | 74 ms | ✓ | 2 results |
| semantic/hybrid | `POST /smart-search` "joinedload pagination performance issue" | joinedload/selectinload AVOID | 75 ms | ✓ | BM25 fallback (no LLM key) |
| project-scoped | `GET /memories?project=markethawk` | 14 total memories | 23 ms | ✓ | Stable project scoping works |
| role-scoped (implement) | `GET /memories?role=implement` | 14 (same as project) | 23 ms | ✗ | **role= filter silently ignored** |
| role-scoped (refine) | `GET /memories?role=refine` | 14 (same as project) | 23 ms | ✗ | **role= filter silently ignored** |
| path-scoped | `GET /memories?path=backend/...` | 14 (same as project) | 23 ms | ✗ | **path= filter silently ignored** |

**Key finding**: role and path scoping are **not implemented** in v0.9.27. The `role=` and `path=`
query parameters passed to `POST /agentmemory/remember` are accepted but not stored as filterable
fields. Retrieval always returns all memories for the project.

### Outage / unavailable behavior

When `docker stop agentmemory-engine` is run mid-eval, curl exits with code **28** (timeout after
~2900 ms, since `--max-time 3` is used). Connection refused exits code 7.

A Phase 1 LOAD integration should:
1. Detect non-zero curl exit → log a warning (not error)
2. Degrade to flat-file reads from `.archon/memory/*.md` (current behavior)
3. Not block the factory run

This is the same fail-open pattern used for Redis and Seq: best-effort, non-blocking.

### Developer ergonomics notes

**Setup friction (HIGH):**
- No pre-built Docker Hub image (`rohitg00/agentmemory` is not on Docker Hub)
- No npm package (not published to npmjs.com registry)
- Requires: `git clone` → `npm install` → `npm run build` (10 s TypeScript compile)
- Requires: 2 containers (`agentmemory-init` + `agentmemory-engine`) + 1 host Node.js worker process
- Total setup commands to reach a working endpoint: ~8 sequential steps vs 1 for the current system (`cat .archon/memory/backend-patterns.md`)

**Memory format translation (REQUIRED):**
- Current system: markdown lines (`- [PATTERN] ... <!-- issue:#N date:... -->`)
- agentmemory: JSON via `POST /agentmemory/remember` with `{"project", "content"}` body
- No bulk-import-from-markdown tooling; every entry requires a separate HTTP call
- ~28 existing entries × 52 ms each = ~1.5 s to hydrate the store on each factory restart (in-memory only)

**Ongoing maintenance burden (HIGH):**
- Entries written to `.archon/memory/*.md` (git-native) would need a separate sync step
- agentmemory state is in-memory (volatile) with `--use-default-config`; must re-import on every restart
- No git-native storage: entries are not versioned, diffable, or reviewable in PRs
- The existing flat-file format supports `[PROVISIONAL]`, `[INVALID]`, `[PATTERN]` tags and `expires:` dates natively; agentmemory has no equivalent

**Latency comparison (flat files vs agentmemory):**
- Flat file grep for all entries: ~2 ms
- agentmemory text search (BM25): ~74 ms (37× slower)
- Flat file with path tag filtering: ~5 ms (shell while-read loop)
- agentmemory project list (no role/path filter): 23 ms (4× slower, no scoping)

## Verdict

**Recommendation:** Do not adopt — AVOID stands and should be renewed at 2026-12-02

**Reasoning:**

All three of the adoption criteria from the spec's plan (Approach section) are failed:

1. **Semantic search quality**: Smart-search returned the correct top result without an LLM key (BM25 fallback), but at 75 ms vs ~2 ms for `grep`. At 28 active entries, BM25 text search is not materially better than `grep -F` with tag filtering, and the path-scoped retrieval that is the primary use case for the existing `load_memory` pattern is not supported.

2. **Role/path scoping**: Fully absent. The `role=` and `path=` parameters that the spec required are silently ignored in v0.9.27. The existing shell `path:` tag filtering in `.archon/memory/*.md` provides this capability today at effectively zero cost.

3. **Setup ergonomics**: Setup requires git clone + npm build + 3-process orchestration for a service that replaces a shell `while read` loop over 28 entries. The flat-file system is already faster, cheaper, and requires no infrastructure.

**Additional findings not in the spec:**
- No pre-built Docker image or npm package available — requires source build
- In-memory state with `--use-default-config` means entries must be re-imported on every restart
- No git-native storage — removes diff/review/version capabilities from memory entries
- Role and path filtering are the primary query patterns used by the factory; both are unimplemented

**Action on AVOID entry:** **Renew at 2026-12-02.** The evidence supports the existing entry: at < 200 entries, flat file reading is faster, more ergonomic, and supports all required query patterns (path-tag filtering, tag-type filtering, expiry-date filtering) without any infrastructure. Amend the entry to reference this spike as the evidence base:

> `[AVOID]` Do not introduce a vector database, embedding model, or semantic search service for memory retrieval. At the scale of this codebase (< 200 entries), flat-file reading with shell grep is faster and more predictable than a retrieval pipeline. Spike evaluation (issue #644, 2026-06-27): agentmemory v0.9.27 requires source build + 3-process setup, role/path filtering is unimplemented, and BM25 latency is 37× higher than grep at current entry count.

## Open questions — resolved

1. **Docker image tag**: No pre-built image exists. Engine uses `iiidev/iii:0.11.2`; worker is built from source at `rohitg00/agentmemory` v0.9.27.
2. **Persistent storage**: `--use-default-config` uses in-memory KV; file-based persistence requires mounting `iii-config.agentmemory.yaml` (file-based `iii-state` adapter). Not needed for spike evaluation.
3. **Semantic search API key**: Not required for BM25 fallback. Full vector search requires `OPENAI_API_KEY` or another LLM provider. At current entry count, BM25 is sufficient.

## Assumptions — status after eval

- ~~`rohitg00/agentmemory` provides a Docker image usable via `docker compose`.~~ **WRONG** — no pre-built image; source build required.
- `GET /agentmemory/health` ✓ confirmed.
- "Semantic queries" exercised via `POST /agentmemory/smart-search`. ✓
