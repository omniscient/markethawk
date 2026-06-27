# Architecture Decisions — Accumulated Lessons

This file is maintained automatically by the dark factory refine agent. Do not edit manually.
Entries represent design-time decisions (source:refine). Implement agents may treat source:implement
entries as higher-confidence than source:refine entries when the two conflict.

## State Storage

- [PATTERN] Use PostgreSQL for all durable application state — scanner events, memory, configs. The existing `AsyncSession` infrastructure handles connection pooling, migrations, and transactional safety. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not introduce Redis for durable state — Redis is volatile (data lost on flush/restart) and not committed to git history. Reserve Redis for ephemeral queues and rate-limit counters only. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

## Services Topology

- [PATTERN] Extend existing services rather than adding new Docker containers. The stack already runs postgres, redis, backend, frontend, celery-worker, celery-beat, seq, prometheus, grafana, and jaeger. Each new service adds operational overhead and a new port to document. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [INVALID: overridden by #643 owner decision — sqlite-vec + semantic search are now permitted for Dark Factory memory; see sqlite-vec PATTERN below] Do not introduce a vector database, embedding model, or semantic search service for memory retrieval. At the scale of this codebase (< 200 memory entries) flat file reading is faster and more predictable than a retrieval pipeline. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

## Agent Memory Design (issue #149)

- [PATTERN] Agent memory is stored as plain markdown files in `.archon/memory/`, committed to the repo. Files are read at Phase 1 load time and updated post-run. This keeps memory human-readable, version-controlled, and accessible to all agents without any extra tooling. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not store agent memory in CLAUDE.md — that file is the primary developer reference and polluting it with machine-generated observations makes it harder to maintain. Memory files are the designated separation. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
- [AVOID] Do not commit `.archon/memory/index.jsonl` — it is a generated projection of the markdown files; committing it causes merge collisions in parallel factory worktrees (same root cause as the codeindex.json #343 merge-conflict issue). Add it to .gitignore and regenerate at Phase 1 LOAD. <!-- issue:#643 date:2026-06-26 expires:2026-12-26 source:refine -->
- [PATTERN] For the Dark Factory memory retriever (memory_retrieve.py), use 3-factor deterministic scoring (kind_weight × path_score × recency_factor) over existing metadata tags only. Do NOT wire usage-counter-based scoring or evidence-count scoring until Phase 3 (write-path replacement) lands — those signals require new write-path state that gate_lib.sh does not currently emit. <!-- issue:#643 date:2026-06-26 expires:2026-12-26 source:refine -->

## Dark Factory Memory System (issue #643)

- [PATTERN] Use sqlite-vec (pip package) for vector storage in the Dark Factory memory system — zero new Docker services, zero DB-connectivity coupling, regenerated alongside index.jsonl. sqlite-vec ships as a loadable SQLite extension (Python ), so no new service dependencies. <!-- issue:#643 date:2026-06-27 expires:2026-12-24 source:refine -->

- [AVOID] Do not use pgvector (PostgreSQL extension) for Dark Factory memory vector storage — the factory container runs in isolation during startup passes (before the application stack is up), making a live DB connection requirement a reliability hazard for a tool that must always work. <!-- issue:#643 date:2026-06-27 expires:2026-12-24 source:refine -->

- [AVOID] Do not install sentence-transformers + a local embedding model in the dark-factory Dockerfile — adds ~500MB to the image for a ~200-entry corpus; the Dockerfile is deliberately lean. Use API-generated embeddings (cached by content-hash) instead. <!-- issue:#643 date:2026-06-27 expires:2026-12-24 source:refine -->

- [PATTERN] For Dark Factory memory retrieval (memory_retrieve.py), use hybrid scoring: deterministic 3-factor (kind × path-match × recency) as a first-pass filter and offline fallback (α=1.0); semantic similarity from sqlite-vec ANN as additive re-rank (α=0.5 when available). Deterministic scoring must remain fully functional without embeddings. <!-- issue:#643 date:2026-06-27 expires:2026-12-24 source:refine -->

- [PATTERN] Phase 3 write-path: make gate_lib.sh::write_memory_entry() and route_memory_file() thin shell wrappers that delegate to memory_write.py with the same 5-arg contract. Gate command files (dark-factory-conformance.md, dark-factory-code-review.md) continue calling the same shell functions unchanged — zero blast radius on the gate commands. <!-- issue:#643 date:2026-06-27 expires:2026-12-24 source:refine -->

- [AVOID] Do not run parallel write paths (old gate_lib.sh + new memory_write.py) simultaneously — entries written by the old path miss index.jsonl and vectors.db until the next full reindex, creating silent consistency gaps that this memory upgrade specifically exists to close. <!-- issue:#643 date:2026-06-27 expires:2026-12-24 source:refine -->

- [PATTERN] Dark Factory memory maintenance (Phase 4): split by cost — inline (at write time) handles cheap ops (exact dedup, 30-entry cap, expiry cleanup); post-run Archon DAG terminal node handles expensive ops (semantic dedup via sqlite-vec ≥0.92 cosine, PROVISIONAL→PATTERN promotion). Scope the DAG node to the touched-scope file set, never a full-corpus sweep. <!-- issue:#643 date:2026-06-27 expires:2026-12-24 source:refine -->
- [AVOID] Do not use rohitg00/agentmemory (or any REST/NPX-launched memory service) as the Dark Factory memory backend — it requires a runtime service (port 3111 / Node process) that breaks factory isolation during startup passes and in per-issue worktrees where no auxiliary services run. Revisit when: (a) corpus exceeds ~2,000 entries and graph retrieval pays off, or (b) a future ticket introduces concurrent multi-agent writes to a shared (non-per-worktree) store. <!-- issue:#643 date:2026-06-27 expires:2026-12-27 source:refine -->
