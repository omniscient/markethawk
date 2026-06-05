# Architecture Decisions — Accumulated Lessons

This file is maintained automatically by the dark factory refine agent. Do not edit manually.
Entries represent design-time decisions (source:refine). Implement agents may treat source:implement
entries as higher-confidence than source:refine entries when the two conflict.

## State Storage

- [PATTERN] Use PostgreSQL for all durable application state — scanner events, memory, configs. The existing `AsyncSession` infrastructure handles connection pooling, migrations, and transactional safety. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not introduce Redis for durable state — Redis is volatile (data lost on flush/restart) and not committed to git history. Reserve Redis for ephemeral queues and rate-limit counters only. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

## Services Topology

- [PATTERN] Extend existing services rather than adding new Docker containers. The stack already runs postgres, redis, backend, frontend, celery-worker, celery-beat, seq, prometheus, grafana, and jaeger. Each new service adds operational overhead and a new port to document. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not introduce a vector database, embedding model, or semantic search service for memory retrieval. At the scale of this codebase (< 200 memory entries) flat file reading is faster and more predictable than a retrieval pipeline. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

## Agent Memory Design (issue #149)

- [PATTERN] Agent memory is stored as plain markdown files in `.archon/memory/`, committed to the repo. Files are read at Phase 1 load time and updated post-run. This keeps memory human-readable, version-controlled, and accessible to all agents without any extra tooling. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not store agent memory in CLAUDE.md — that file is the primary developer reference and polluting it with machine-generated observations makes it harder to maintain. Memory files are the designated separation. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

## Docker Socket Proxy (issue #203)

- [PATTERN] The docker-socket-proxy sidecar must be always-on (no Docker Compose profile, restart: unless-stopped) because backlog-scheduler lives under the 'scheduler' profile and runs continuously — the proxy's lifecycle must be a superset of both 'scheduler' and 'factory' profiles. <!-- issue:#203 date:2026-06-05 expires:2026-12-05 source:refine -->
- [AVOID] Do not put docker-socket-proxy under the 'factory' or 'scheduler' profile — if the proxy shares a profile, the always-on scheduler loses Docker API access between factory runs, breaking dispatch. <!-- issue:#203 date:2026-06-05 expires:2026-12-05 source:refine -->
- [PATTERN] The minimal tecnativa/docker-socket-proxy allowlist for the dark factory is: CONTAINERS=1, IMAGES=1, NETWORKS=1, VOLUMES=1, BUILD=1, POST=1; SERVICES=0, EXEC=0, AUTH=0, SECRETS=0. POST=1 is required for docker compose run/build/network-create/volume-create to work — without it, all write ops are blocked. <!-- issue:#203 date:2026-06-05 expires:2026-12-05 source:refine -->
- [AVOID] Do not mount /var/run/docker.sock directly into dark-factory or backlog-scheduler. Use DOCKER_HOST=tcp://docker-socket-proxy:2375 and route through the socket proxy. The raw socket mount grants arbitrary host-level access equivalent to root on the host. <!-- issue:#203 date:2026-06-05 expires:2026-12-05 source:refine -->
