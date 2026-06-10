# Scoring Rubric (FROZEN)

This rubric is identical to the one used in v1 (2026-05-26) and v2 (2026-06-03). Do not modify
dimensions, anchors, or formulas — comparability across reviews is the entire point. New kinds of
analysis belong in unscored evidence sections (SECTIONS.md §11–§13), not here.

## Headline formulas

| Number | Formula |
|---|---|
| **Weighted Scorecard (0–5)** | Equal-weight mean of the 16 scorecard dimensions, reported to 2 decimals (historical reports truncated: 2.875 → "2.8") |
| **Overall Quality (0–100)** | `round(scorecard_mean × 62 / 2.8)` — calibrated so v1's 2.8 → 62. (v2 check: 3.75 → 83 ✓) |
| **Architecture Quality (0–5)** | Mean of the 11 §3.x scores, reported to 1 decimal. (Historical: v1 reported 3.2; v2 3.9) |

## Score → badge mapping (used everywhere)

| Score | Badge | Color |
|---|---|---|
| 5 | Excellent | green |
| 4 | Good | green (light) |
| 3 | Acceptable | yellow |
| 2 | Weak | orange |
| 0–1 | Poor / Not present | red |

## Calibration history

| Review | Overall /100 | Architecture /5 | Scorecard /5 |
|---|---|---|---|
| v1 (2026-05-26) | 62 | 3.2 | 2.8 |
| v2 (2026-06-03) | 83 | 3.9 | 3.75 |

## The 16 scorecard dimensions

Score each 0–5 against the anchors. The anchor describes what earns that score; interpolate for in-between states. Always cite the evidence that caps the score.

1. **Architecture Clarity** — 1: no discernible structure. 3: layers exist but are frequently violated. 5: explicit, documented layering that the code actually follows.
2. **Modularity** — 1: god modules everywhere. 3: modules exist but several files >800 lines carry mixed concerns. 5: focused modules, protocol/interface seams, no god files.
3. **Separation of Concerns** — 1: HTTP/business/persistence interleaved. 3: boundary exists but thick routers/pages mix concerns. 5: routers/pages are thin dispatchers; logic lives in services/hooks.
4. **Maintainability** — 1: inconsistent naming/organization, dead code. 3: consistent but with notable duplication or drift. 5: consistent conventions, low duplication, active refactoring hygiene.
5. **Testability** — 1: untestable without full stack. 3: good infra on one tier, gaps on the other. 5: both tiers testable in isolation with solid fixtures/harnesses.
6. **Code Coverage Maturity** — 1: no coverage measurement. 3: thresholds exist but with large exclusions or gameable includes. 5: honest, enforced coverage across all tiers incl. async/task code.
7. **Reliability** — 1: no error handling strategy. 3: retries/health checks present; no circuit breakers/timeouts/backpressure. 5: full resilience toolkit with graceful degradation.
8. **Security Posture** — 1: no auth, wildcard CORS, exposed admin surfaces. 3: auth + rate limiting + restricted CORS, with known gaps (CSRF, WS, secrets validation). 5: defense-in-depth, validated secrets, RBAC, TLS, scanning that blocks.
9. **Observability** — 1: print statements. 3: structured logs + health endpoints, no metrics/tracing. 5: metrics + tracing + dashboards + alert rules, all pipelines verified end-to-end.
10. **Performance Readiness** — 1: no attention to performance. 3: some optimizations; pooling/caching gaps. 5: pooling, caching, eager loading, payload optimization, measured baselines.
11. **Scalability Readiness** — 1: cannot scale beyond one process. 3: workers scale horizontally; API/DB single-instance. 5: horizontally scalable tiers, read replicas, session-affinity story.
12. **Deployment Readiness** — 1: manual, undocumented. 3: compose with healthchecks; no TLS/limits/registry. 5: registry, CI/CD with scanning, resource limits, TLS, prod/dev separation.
13. **Developer Experience** — 1: multi-day setup. 3: one-command start, gaps in linting/types/CI feedback. 5: fast setup, enforced lint/format/type gates, rich debugging.
14. **Documentation** — 1: none/wrong. 3: good guides with drift or missing referenced files. 5: accurate, complete, ADRs capture decisions, no doc/reality drift.
15. **Dependency Hygiene** — 1: unpinned, unaudited. 3: pinned one tier, audits advisory-only. 5: pinned/locked, automated blocking scans, update cadence.
16. **Operational Readiness** — 1: no backups/runbooks/alerting. 3: some of backups/alerts/runbooks present. 5: automated verified backups, runbooks, alerting, incident process.

## The 11 architecture assessment areas (§3.1–§3.11)

Same 0–5 scale and badges. Each gets a card with: Score, badge, Δ pill, meter bar, **Evidence**, **Finding**, **Risk** (if any), **Recommendation** (if any). In re-assessments, lead with **Change** (what moved since the prior review).

- **3.1 Separation of Concerns** — router/service/page boundaries in practice.
- **3.2 Module Boundaries** — package seams, protocol interfaces, cross-layer leaks (e.g. HTTPException raised from services).
- **3.3 Dependency Direction** — does everything flow inward; registry/string-name couplings.
- **3.4 Coupling and Cohesion** — service-to-service imports, mixed-responsibility modules, orchestration coupling.
- **3.5 API Design** — REST conventions, status codes, schemas, versioning, WebSocket design.
- **3.6 Data Access Patterns** — ORM usage, transactions, eager loading/N+1, JSONB tradeoffs, pagination correctness.
- **3.7 Error Handling Architecture** — exception hierarchy, retryability semantics, error IDs, trace exposure gating.
- **3.8 Configuration Management** — validated settings, fail-fast on required fields, validators on security-critical fields.
- **3.9 Observability Architecture** — metrics/tracing/log pipelines and whether they actually deliver end-to-end.
- **3.10 Security Architecture** — authn/authz, CORS, rate limiting, CSRF, secrets, container security.
- **3.11 Deployment Architecture** — compose/orchestration, limits, TLS, registry, CI/CD, environment separation.

## Severity & priority scales (risk register, findings)

- **Severity**: Critical (exploitable/data-loss now) · High (likely material impact) · Medium (real but bounded) · Low (hygiene).
- **Priority**: P0 (before anything else) · P1 (this cycle) · P2 (next cycle) · P3 (opportunistic).
- **Effort**: S (≤½ day) · M (≤3 days) · L (≤2 weeks) · XL (multi-week).
- **Ticket outcome badges** (traceability matrix): Done (green) · Partial / has-gap (yellow) · Declined w/ ADR (blue) · Broken/fictional (red).

## Supplementary tracked metrics (unscored, but reported every review for trend)

These never enter the headline formulas but must appear each review so trends are visible:

- God-module line counts: `services/scanner.py`, `services/futures_data.py`, `providers/ibkr.py`, largest router, largest frontend module/component (table with vN-1 → vN deltas).
- LOC by tier, test file/function counts, model/migration/router/service counts, Docker service count, ADR count, commit count.
- Complexity top-10 and duplication top-8 tables (see SECTIONS.md §11).
- DORA four + delivery extras (see SECTIONS.md §12).
