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

## Security Settings (issue #202)

- [PATTERN] Decouple security flags (e.g., `COOKIE_SECURE`) from `ENVIRONMENT` via dedicated `bool = True` settings in `config.py`. Default secure-on. Override to `false` in `docker-compose.override.yml` (not `.env`) so the dev escape is automatic, not operator-action. This matches the existing `ENVIRONMENT: str = "production"` secure-by-default posture. <!-- issue:#202 date:2026-06-05 expires:2026-12-05 source:refine -->
- [AVOID] Do not derive the cookie `secure` flag (or any security control) from `ENVIRONMENT`. If `ENVIRONMENT=development` is ever needed for debug traces, it silently disables cookie security as a side-effect. Use an independent `COOKIE_SECURE` setting instead. <!-- issue:#202 date:2026-06-05 expires:2026-12-05 source:refine -->
- [PATTERN] Profile-gate infrastructure-only services (TLS proxy, etc.) in `docker-compose.yml` using `profiles:` (e.g., `profiles: ["tls"]`) so they are absent from local dev but correctly started by `deploy.yml` via `--profile tls`. This is the same pattern used by `factory`, `scheduler`, and `forecasting` services. <!-- issue:#202 date:2026-06-05 expires:2026-12-05 source:refine -->
- [AVOID] Do not add TLS termination as a separate `docker-compose.tls.yml` overlay — `deploy.yml` runs `docker compose up -d` against only `docker-compose.yml` without overlays, so a separate file would never be picked up by the automated deploy workflow. Use profiles in the main file instead. <!-- issue:#202 date:2026-06-05 expires:2026-12-05 source:refine -->
