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

## Endpoint Access Control

- [PATTERN] For scrape endpoints consumed by internal Docker-network services (e.g. Prometheus scraping `/metrics` at `backend:8000`), protect via Caddyfile explicit deny rather than app-level auth — the Caddyfile already only forwards `/api/*` to the backend, so `/metrics` is unreachable from outside Caddy. An explicit `handle /metrics { respond 404 }` block in the Caddyfile makes this protection visible. Keep the endpoint in `EXEMPT_PREFIXES` so `AuthMiddleware` does not gate it (Prometheus cannot present a JWT cookie). <!-- issue:#369 date:2026-06-12 expires:2026-12-12 source:refine -->

- [AVOID] Do not add a static bearer-token auth mechanism to the `/metrics` route to "protect" it — long-lived static tokens are a security smell, there is no existing inbound bearer-token auth precedent in the codebase, and the Caddyfile reverse-proxy topology already provides the necessary isolation at the network layer. <!-- issue:#369 date:2026-06-12 expires:2026-12-12 source:refine -->

- [PATTERN] Gate feature-visibility toggles (Swagger/ReDoc/openapi.json) with a dedicated boolean Settings field (e.g. `DOCS_ENABLED: bool = False`) rather than deriving from `ENVIRONMENT`. Dedicated flags are independently overridable, default secure, and avoid coupling to the overloaded `ENVIRONMENT` string. Add the override to `docker-compose.override.yml` alongside `COOKIE_SECURE: "false"` so local dev requires no manual steps. <!-- issue:#369 date:2026-06-12 expires:2026-12-12 source:refine -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
