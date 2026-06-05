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

## CSRF Defense (issue #192)

- [PATTERN] Use a custom-header check (`X-Requested-With: XMLHttpRequest`) for CSRF protection rather than a double-submit cookie. Cross-site forms and navigations cannot set arbitrary headers; preflight enforcement via `CORS_ORIGINS` makes the custom header an unforgeable proof of JavaScript origin. Requires no token generation, cookie management, or per-session state. <!-- issue:#192 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not use the double-submit CSRF cookie pattern in this codebase — it requires generating, setting (non-HttpOnly cookie), and validating a per-session random token. For a single-operator internal tool the overhead adds no meaningful security over the custom-header approach, which the CORS preflight makes equally robust. <!-- issue:#192 date:2026-06-05 expires:2026-12-05 source:refine -->

- [PATTERN] Implement cross-cutting security middleware as a separate pure ASGI class (not by extending `AuthMiddleware` or using FastAPI `Depends`). Register it with `app.add_middleware()` before `AuthMiddleware` so it is innermost (first-added = innermost in Starlette). This ensures auth runs before CSRF in the request pipeline: 401 for missing cookie, then 403 for missing CSRF header. <!-- issue:#192 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not reuse `EXEMPT_PREFIXES` (the auth exempt list) as the CSRF exempt list. The two lists serve different concerns — auth exempts pre-authentication endpoints and infrastructure; CSRF exempts pre-authentication endpoints only. Coupling them conflates security boundaries and breaks if either list changes for unrelated reasons. Use a dedicated `CSRF_EXEMPT_PREFIXES = ("/api/auth/",)`. <!-- issue:#192 date:2026-06-05 expires:2026-12-05 source:refine -->
