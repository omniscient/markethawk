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

## WebSocket Authentication (issue #191)

- [PATTERN] WebSocket auth is enforced via a per-handler FastAPI dependency (`get_current_user_ws` in `app/core/auth.py`), not in `AuthMiddleware`. Each WS handler adds `_user: User = Depends(get_current_user_ws)`. FastAPI resolves the dependency before `accept()` is called; if auth fails it raises `WebSocketException(code=1008)`. <!-- issue:#191 date:2026-06-05 expires:2026-12-05 source:refine -->

- [AVOID] Do not extend `AuthMiddleware` to handle WebSocket scopes. The middleware is a deliberately minimal pure-ASGI passthrough (comment at main.py:241-245) that avoids BaseHTTPMiddleware due to GZip/streaming incompatibility. Adding raw ASGI byte-header cookie parsing plus a WebSocket close-frame reject path to it risks subtle ASGI message-ordering bugs. <!-- issue:#191 date:2026-06-05 expires:2026-12-05 source:refine -->

- [PATTERN] WS auth depth must match HTTP auth: JWT decode + DB `is_active` lookup (not JWT-only). Using an identical auth chain for both transports prevents security divergence and avoids subtle bugs where a deactivated user retains WS access. <!-- issue:#191 date:2026-06-05 expires:2026-12-05 source:refine -->

## Agent Memory Design (issue #149)

- [PATTERN] Agent memory is stored as plain markdown files in `.archon/memory/`, committed to the repo. Files are read at Phase 1 load time and updated post-run. This keeps memory human-readable, version-controlled, and accessible to all agents without any extra tooling. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not store agent memory in CLAUDE.md — that file is the primary developer reference and polluting it with machine-generated observations makes it harder to maintain. Memory files are the designated separation. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->
