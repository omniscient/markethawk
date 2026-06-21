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

- [AVOID] Do not store agent memory in CLAUDE.md — that file is the primary developer reference and polluting it with machine-generated observations makes it couldn't to maintain. Memory files are the designated separation. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

## Replay Engine Design (issue #487)

- [PATTERN] In the replay engine, compute `data_hash` inside the `run_signal_replay` Celery task after bars and signals are materialised — not in `ManifestResolver` at manifest-create time. `ManifestResolver` freezes only the determinism *parameters* (config snapshot, universe, range); the task computes the *content fingerprint* over actual OHLCV + split-adj version + minute-bar count. A rerun that produces a different hash must surface the divergence. <!-- issue:#487 date:2026-06-21 expires:2026-12-21 source:refine -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->

- [PROVISIONAL] `ScannerEvent` has no FK or column linking it to the `ScannerConfig` that produced it (only `scanner_type` + JSONB `indicators`/`criteria_met`). Per-event config provenance verification is therefore not implementable from existing columns. Designs relying on "verify each event was produced under the current config" must either add a `config_fingerprint` to `ScannerEvent`, or fall back to scanner_type-only matching and full regeneration for strict consistency. <!-- evidence:model-read issue:#487 date:2026-06-21 expires:2026-12-21 source:refine -->
