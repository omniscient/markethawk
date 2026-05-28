# ADRs for Key Architectural Decisions

**Date:** 2026-05-27
**Issue:** #99

## Overview

MarketHawk has exactly one Architecture Decision Record (ADR-001, covering the Polygon.io data provider choice). Seven additional significant architectural decisions are currently implicit — visible only by reading code and config — making it hard for new contributors to understand *why* the stack looks the way it does. This spec covers the creation of an ADR template and seven new ADRs documenting those decisions.

## Requirements

1. A reusable ADR template file is added to `Docs/adr/` using a lightweight format: `Status:` is the only mandatory field; Context / Decision / Consequences sections are organizational suggestions for longer ADRs, not required scaffolding.
2. ADR-002 through ADR-008 are written as individual files in `Docs/adr/`, numbered sequentially.
3. ADR-002 (authentication strategy) is written as a **Pending stub** because the decision depends on issue #84, which has not yet shipped. The stub reserves the slot and forward-references #84.
4. ADRs 003–008 are written as complete, accurate records of decisions already made and visible in the codebase.
5. ADR-003 explicitly acknowledges the inconsistency between the current sync ORM and the partially-async codebase, and includes a forward pointer to the planned async migration issue.
6. ARCHITECTURE.md's service topology diagram currently shows `asyncpg` as the ORM transport; ADR-003 notes this inaccuracy. The diagram correction itself is a separate follow-up change.
7. ADR-001's informal paragraph style is compatible with the format (adding a `Status: Accepted` line would be sufficient to bring it into compliance). Whether to add that line is left to the implementer; retroactive reformatting is not required.

## Approach

### Format: Status Line + Free-Form Prose

All new ADRs include a `Status:` line at the top. This is the only mandatory structural element.

ADR-001 is not "wrong" — it contains what was decided, why, and what the trade-offs were. The one thing it lacks is a `Status:` field, which makes it impossible to tell from the file whether the decision is still in force, superseded, or under review. The full four-section scaffold (Context / Decision / Consequences) adds discoverability for long, dense ADRs but is overhead for brief decisions.

Template structure:
```
# <title>

**Date:** YYYY-MM-DD
**Status:** <Accepted | Proposed | Pending | Superseded by ADR-NNN>

## Context
<Why did this decision need to be made? What forces were at play?>
(Optional for short ADRs — may be folded into prose below)

## Decision
<What was decided? Be specific.>

## Consequences
<What are the known trade-offs, follow-on work, or risks?>
```

The template note: sections are organizational suggestions. Short decisions (1–2 paragraphs) may use continuous prose with just the `Status:` header. Longer ADRs (003, 005, 006, 007) benefit from explicit sections due to content density.

### ADR Content Summary

**ADR-002 — Authentication and Authorization Strategy** (Status: Pending)
- Context: No auth exists; issue #84 will implement it. Slot reserved.
- Decision: Pending — will be recorded when #84 ships.
- Consequences: N/A until decision is made. See #84.

**ADR-003 — Synchronous SQLAlchemy ORM** (Status: Accepted)
- Context: FastAPI and the Polygon batch-fetch path already use `asyncio.gather()` / `asyncio.Semaphore`. `asyncpg` is installed. The live-scanner container is a full asyncio process. Despite this, the SQLAlchemy ORM (`SessionLocal`, `create_engine`) is synchronous, using the psycopg2 driver.
- Decision: Start with synchronous SQLAlchemy for development velocity. The ORM is the slowest-moving part to migrate and the async ecosystem (SQLAlchemy 2.0 async) was less battle-tested at the time the project was scaffolded.
- Consequences: FastAPI route handlers that call `get_db()` block the event loop under DB load. `asyncpg` is installed but not yet used by the ORM (it is used by the async Redis client). A migration to async SQLAlchemy is planned (see #101 / #103 — issue number to be confirmed). This ADR will be superseded when that migration lands. **Note**: the service topology diagram in ARCHITECTURE.md incorrectly shows `asyncpg` as the ORM transport; that diagram should be corrected to reflect psycopg2 as a follow-up.

**ADR-004 — JSONB for Scanner Event Metadata** (Status: Accepted)
- Context: `ScannerEvent` stores scanner-specific indicator values, criteria flags, and enrichment metadata. These payloads differ across scanner types (pre-market volume spike vs. oversold bounce vs. liquidity hunt), and new scanners are added frequently.
- Decision: Store scanner-specific payloads as JSONB columns (`indicators`, `criteria_met`, `metadata_`) on the `scanner_events` table rather than normalizing into per-scanner-type tables.
- Consequences: Queries against individual indicators require JSONB operators (`->>`, `@>`), which are less ergonomic than column predicates. Adding a new scanner type requires no schema migration. PostgreSQL JSONB supports GIN indexing for containment queries. The tradeoff favors schema flexibility over query ergonomics, which is appropriate given the pace of scanner iteration.

**ADR-005 — Celery + Redis for Background Tasks** (Status: Accepted)
- Context: MarketHawk requires scheduled jobs (pre-market scan, news polling, nightly sync), one-off async tasks triggered by API endpoints (manual scan runs), and a result backend for task tracking via Flower.
- Decision: Use Celery with Redis as both broker and result backend. Celery Beat handles scheduled tasks. Flower provides a monitoring UI.
- Consequences: Redis serves dual duty (Celery broker/backend and pub/sub for live data). A Redis failure takes down both task scheduling and live updates. FastAPI background tasks (`BackgroundTasks`) were considered but rejected: they lack persistent scheduling, retry logic, and distributed worker support. Airflow and Prefect were considered but rejected as over-engineered for a single-service deployment with fewer than 10 task types.

**ADR-006 — Live Scanner as a Separate Service** (Status: Accepted)
- Context: Real-time price monitoring via IBKR (Interactive Brokers) requires a persistent asyncio event loop consuming `reqRealTimeBars` and `reqMktData` streams. Embedding this in the FastAPI process would conflict with FastAPI's own event loop and IBKR's connection management. The live scanner also needs its own IBKR client ID to avoid conflicts.
- Decision: Extract the live scanner into a standalone container (`live-scanner` service in `docker-compose.yml`) that runs `python -m live_scanner.main`. It communicates outbound via Redis pub/sub channels (publishes bar/quote events). The FastAPI backend subscribes via WebSocket connections managed by `websocket_manager.py`.
- Consequences: Two separate processes must maintain IBKR connections (the backend for historical data, the live scanner for streaming). Redis becomes a required runtime dependency for live updates (if Redis is down, live WebSocket updates stop). The live scanner's synchronous `SessionLocal` pattern is an acknowledged inconsistency with the asyncio runtime (see ADR-003).

**ADR-007 — Dark Factory Autonomous Development Model** (Status: Accepted)
- Context: Running Claude Code agents on GitHub issues requires access to Docker (to spin up preview environments), to the repository (to push branches), and to the host machine. The trust model question: how much isolation is required?
- Decision: Run the Dark Factory agent inside an ephemeral Docker container. Docker socket access is mediated through a `tecnativa/docker-socket-proxy` that restricts the API surface (containers, images, networks, volumes — no exec, no Swarm). The agent clones the repo from GitHub rather than bind-mounting the host. Preview stacks are created on deterministic ports (`1{NN}33` / `1{NN}80` per issue number).
- Consequences: The docker-socket-proxy does not natively support label-based filtering; the agent can technically see all containers via the Docker API. Mitigation is by convention: the entrypoint and workflows only operate on `mh-preview-*` prefixed resources. This is a known, accepted risk documented in the dark factory design spec (`Docs/superpowers/specs/2026-05-02-dark-factory-design.md`). Stronger isolation (custom proxy, Docker API auth plugin) is deferred as a future hardening option.

**ADR-008 — Naive UTC Timestamps** (Status: Accepted)
- Context: PostgreSQL's `TIMESTAMP WITHOUT TIME ZONE` column type stores timestamps without timezone metadata. Python's `datetime` objects can be timezone-aware (carry `tzinfo`) or naive (no `tzinfo`). SQLAlchemy emits a warning when a timezone-aware datetime is stored in a `TIMESTAMP WITHOUT TIME ZONE` column.
- Decision: All timestamps are stored as naive UTC datetimes. UTC is computed via `datetime.now(timezone.utc)` and then stripped with `.replace(tzinfo=None)` before persistence (visible in all `created_at` / `updated_at` column defaults). The application convention is: all datetimes in the system are UTC; timezone-awareness is only applied at API response serialization boundaries if needed.
- Consequences: The convention requires discipline — any datetime passed into the ORM must be naive UTC. A naive datetime that is actually local time would be silently stored incorrectly. The pattern is consistently applied across all models. Moving to timezone-aware columns (`TIMESTAMP WITH TIME ZONE`) is a future option but would require a migration and updating every column default.

## Alternatives Considered

### A: All 7 ADRs as complete documents (including ADR-002)
Write ADR-002 with a "Proposed" status guessing at the auth approach before #84 ships. **Rejected**: encodes a pre-decision that the #84 implementer may not follow, creating a potentially misleading record. The issue's own annotation — "#84 will make this decision; record the rationale" — signals intent to document after the fact.

### B: Template only, all 7 ADRs as empty stubs
Reserve all slots but write no content. **Rejected**: very low value delivery; the decisions for ADRs 003–008 are already made and fully visible in the codebase.

### C: Full Nygard four-section scaffold for every ADR (mandatory Context / Decision / Consequences sections)
Enforce the full structured format on all ADRs including short ones. **Rejected** based on owner feedback: ADR-001's informal paragraph format is not wrong — it lacks only a Status field. Mandatory sections add overhead for brief decisions without improving their quality. The template should guide, not constrain.

### D (chosen): Status line required + free-form prose + optional sections
Mandates the one field that matters for ADR lifecycle tracking (Status), leaves structure flexible for the implementer. Short ADRs can use prose; long ones use sections. ADR-001 is compatible with a one-line addition.

## Open Questions

- The issue body references issue #103 for the async SQLAlchemy migration; the issue comments reference #101. The ADR notes both numbers. The correct issue number should be verified before merging.
- ADR-002 content: the stub is intentionally empty. A follow-up task should be created to fill it in after #84 ships.
- Adding `Status: Accepted` to ADR-001 is optional but harmless; implementer should decide.

## Assumptions

- The `Docs/adr/` directory (uppercase D) is the canonical location; `docs/adr/` (lowercase) referenced in some internal docs is a discrepancy in documentation, not a second directory.
- ADR-001's content is accurate and does not need reformatting — at most, a `Status: Accepted` line addition.
- The ARCHITECTURE.md diagram correction (asyncpg vs psycopg2) is out of scope for this issue and should be a separate PR.
