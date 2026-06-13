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

## Observability / Alerting

- [PATTERN] All alert rules live in `grafana/provisioning/alerting/rules.yaml` as Grafana-managed alerts (Grafana's native alerting engine). `monitoring/prometheus/prometheus.yml` has NO `rule_files:` or `alerting:` block — do not add them for individual features. Every rule follows the two-refId pattern: one Prometheus datasource refId for the metric query, one `-- Grafana --` math expression refId for the threshold condition. <!-- issue:#391 date:2026-06-13 expires:2026-12-13 source:refine -->

- [AVOID] Do not add Prometheus recording rules or `rule_files:` infrastructure for new alert rules — this would introduce a parallel alerting path and break the single-source-of-truth in `grafana/provisioning/alerting/rules.yaml`. All thresholds and alert routing belong in the Grafana provisioning layer. <!-- issue:#391 date:2026-06-13 expires:2026-12-13 source:refine -->

- [PATTERN] Prometheus metrics in `backend/app/core/metrics.py` use no application prefix (e.g. `scan_duration_seconds`, not `markethawk_scan_duration_seconds`). Follow this convention for all new metrics. The `markethawk_` prefix appears in issue bodies as illustrative naming only — it is not an established convention. <!-- issue:#391 date:2026-06-13 expires:2026-12-13 source:refine -->

## Agent Memory Design (issue #149)

- [PATTERN] Agent memory is stored as plain markdown files in `.archon/memory/`, committed to the repo. Files are read at Phase 1 load time and updated post-run. This keeps memory human-readable, version-controlled, and accessible to all agents without any extra tooling. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

- [AVOID] Do not store agent memory in CLAUDE.md — that file is the primary developer reference and polluting it with machine-generated observations makes it harder to maintain. Memory files are the designated separation. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:refine -->

---
<!-- PROVISIONAL — entries below are from a single observed run; unverified.
     Do not rely on these as authoritative guidance. They are excluded from
     plan/implement prompt injection except as advisory context.
     Each will be promoted to [PATTERN] on second-run confirmation (different issue number) or dropped at TTL. -->
