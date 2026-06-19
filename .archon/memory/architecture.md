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

## Event Detail UI (issue #471)

- [PATTERN] Use a single unified `/signal_brief` endpoint (`ai_signal_brief.v1`) as the sole data source for an event detail drawer — it already embeds `historical_analogs[]`, `outcome_context{}`, and `archetype{}` in one call. Splitting into separate `/analogs` + `/signal_brief` calls adds a second failure mode and timing divergence for no user benefit. <!-- issue:#471 date:2026-06-19 expires:2026-12-19 source:refine -->

- [AVOID] Do not fetch analogs and the signal brief as two separate calls when rendering an event detail drawer — the brief already bundles analogs. Use the dedicated `/analogs` endpoint only for pagination past the brief's top-N or for lightweight widgets that do not need the full brief payload. <!-- issue:#471 date:2026-06-19 expires:2026-12-19 source:refine -->

- [PATTERN] Shared slide-over drawer (right-side, 480px) is the correct pattern for event detail that overlays a data table or list — it preserves the originating row context in view, unlike a centered modal which covers the list. Follow existing Modal.tsx accessibility conventions (Escape key, backdrop click, scroll lock). <!-- issue:#471 date:2026-06-19 expires:2026-12-19 source:refine -->

- [AVOID] Do not build separate detail components for each UI surface (Scanner table vs. Stock Detail list) when both surfaces operate on the same data type keyed by `uuid` — a single shared component wired at the parent level keeps the detail experience consistent and eliminates duplication. <!-- issue:#471 date:2026-06-19 expires:2026-12-19 source:refine -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
