# Documentation Hygiene — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four documentation-hygiene defects — sync/async ORM drift, stale model/router/topology tables in `ARCHITECTURE.md`, and one false memory-file entry — to prevent dark-factory agents from generating incorrect async SQLAlchemy code.

**Architecture:** Documentation-only change. No code modifications, no migrations, no model files. All deliverables are Markdown edits and one machine-generated memory-file correction. Pre-resolved items (ADR numbering, `docs/` casing) are verified with bounded grep checks only; no edits needed.

**Tech Stack:** Markdown editing, grep verification

**Spec:** [`docs/superpowers/specs/2026-06-05-documentation-hygiene-design.md`](../specs/2026-06-05-documentation-hygiene-design.md)
**Issue:** [#201](https://github.com/omniscient/markethawk/issues/201)

---

## File Structure

| Path | Change |
|------|--------|
| `CLAUDE.md` | Tech Stack line: `SQLAlchemy 2.0 (async)` → `SQLAlchemy 2.0 (sync)` |
| `README.md` | Backend line: `SQLAlchemy 2.0 (async)` → `SQLAlchemy 2.0 (sync, psycopg2)` |
| `ARCHITECTURE.md` | Fix `database.py` module map entry; add 8 model rows; add 2 router rows; extend topology mermaid |
| `.archon/memory/backend-patterns.md` | Rewrite the one false `[AVOID]` entry (async claim); all other entries unchanged |

---

## Task 1 — Fix sync/async drift in CLAUDE.md, README.md, ARCHITECTURE.md, and backend-patterns.md

**Files:** `CLAUDE.md`, `README.md`, `ARCHITECTURE.md`, `.archon/memory/backend-patterns.md`

### Steps

- [ ] 1.1 Confirm the defect is present (write failing test — all four files should have hits):

  ```bash
  grep -n "async SQLAlchemy\|AsyncSession\|SQLAlchemy 2.0 (async)" CLAUDE.md README.md ARCHITECTURE.md .archon/memory/backend-patterns.md
  ```

  Expected: at least one hit per file (confirms defect exists before editing).

- [ ] 1.2 Fix `CLAUDE.md` Tech Stack line (re-grep first to confirm exact text, as line numbers may have shifted):

  ```bash
  grep -n "SQLAlchemy 2.0" CLAUDE.md
  ```

  Edit: replace
  ```
  **Backend**: FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL + Redis + Celery
  ```
  with:
  ```
  **Backend**: FastAPI + SQLAlchemy 2.0 (sync) + PostgreSQL + Redis + Celery
  ```

- [ ] 1.3 Fix `README.md` backend line (re-grep first):

  ```bash
  grep -n "SQLAlchemy 2.0" README.md
  ```

  Edit: replace
  ```
  **Backend**: FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL 15 · Redis 7 · Celery
  ```
  with:
  ```
  **Backend**: FastAPI · SQLAlchemy 2.0 (sync, psycopg2) · PostgreSQL 15 · Redis 7 · Celery
  ```

- [ ] 1.4 Fix `ARCHITECTURE.md` `database.py` entry in the Core module map table:

  Edit: replace the entire `database.py` row
  ```
  | `database.py` | Async SQLAlchemy engine and session factory (`AsyncSession`). `get_db()` dependency. |
  ```
  with:
  ```
  | `database.py` | Synchronous SQLAlchemy engine and session factory (`Session`, psycopg2-binary). `get_db()` dependency. |
  ```

- [ ] 1.5 Fix `.archon/memory/backend-patterns.md` — rewrite the one false `[AVOID]` entry. Leave all other entries exactly as-is.

  Edit: replace
  ```
  - [AVOID] Never use synchronous SQLAlchemy patterns (`session.query()`, sync `relationship()` lazy loads) — the app uses `AsyncSession` throughout. All queries use `select()` + `await session.execute()`. Sync lazy-loading raises `MissingGreenlet` in asyncpg. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->
  ```
  with:
  ```
  - [AVOID] Never use `AsyncSession`, `await session.execute()`, or asyncpg — the app is fully synchronous. The correct query pattern is synchronous `session.execute(select(Model))` with psycopg2-binary; synchronous `relationship()` lazy-loads are also valid. ADR-0004 documents the deliberate choice to defer async migration to issue #103. <!-- issue:#201 date:2026-06-07 expires:2026-12-07 source:implement -->
  ```

- [ ] 1.6 Verify all four fixes (test passes — zero hits on the false async claims):

  ```bash
  grep -rn "the app uses \`AsyncSession\` throughout\|SQLAlchemy 2.0 (async)\|Async SQLAlchemy engine" CLAUDE.md README.md ARCHITECTURE.md .archon/memory/backend-patterns.md
  ```

  Expected: **zero hits**.

  Also verify the correct sync text is present:

  ```bash
  grep -n "SQLAlchemy 2.0 (sync" CLAUDE.md README.md
  grep -n "psycopg2-binary" ARCHITECTURE.md .archon/memory/backend-patterns.md
  ```

  Expected: one hit per file confirming the corrected text.

- [ ] 1.7 Commit:

  ```bash
  git add CLAUDE.md README.md ARCHITECTURE.md .archon/memory/backend-patterns.md
  git commit -m "docs(#201): correct sync/async ORM drift in CLAUDE.md, README.md, ARCHITECTURE.md, backend-patterns.md"
  ```

---

## Task 2 — Add 8 missing model rows to ARCHITECTURE.md model table

**Files:** `ARCHITECTURE.md`, `backend/app/models/alert_rule.py`, `backend/app/models/alert_delivery_log.py`, `backend/app/models/auto_trade_order.py`, `backend/app/models/trading_strategy.py`, `backend/app/models/push_subscription.py`, `backend/app/models/scanner_outcome_snapshot.py`, `backend/app/models/scanner_outcome_summary.py`, `backend/app/models/system_config.py`

### Steps

- [ ] 2.1 Confirm the 8 models are absent from the model table (write failing test — use the table-row pattern to avoid matching prose mentions):

  ```bash
  grep -n "| \`AlertRule\`\|| \`AlertDeliveryLog\`\|| \`AutoTradeOrder\`\|| \`TradingStrategy\`\|| \`PushSubscription\`\|| \`ScannerOutcomeSnapshot\`\|| \`ScannerOutcomeSummary\`\|| \`SystemConfig\`" ARCHITECTURE.md
  ```

  Expected: zero hits (confirms all 8 table rows are missing; note: these class names appear in prose elsewhere in the file, so scoping to the backtick-quoted table pattern `| \`ClassName\` |` is essential).

- [ ] 2.2 Read each model file to confirm `__tablename__` and purpose before writing descriptions:

  ```bash
  grep -n "__tablename__\|class Alert\|class Auto\|class Trading\|class Push\|class Scanner\|class System" \
    backend/app/models/alert_rule.py \
    backend/app/models/alert_delivery_log.py \
    backend/app/models/auto_trade_order.py \
    backend/app/models/trading_strategy.py \
    backend/app/models/push_subscription.py \
    backend/app/models/scanner_outcome_snapshot.py \
    backend/app/models/scanner_outcome_summary.py \
    backend/app/models/system_config.py
  ```

- [ ] 2.3 In `ARCHITECTURE.md`, find the last row of the `### Database Models` table (the `User` row), and insert 8 new rows immediately after it — before the `## Frontend Architecture` heading.

  Find the `User` row (exact text to anchor the insertion point):
  ```
  | `User` | `users` | Operator account. Fields: `id` (UUID PK), `username` (unique), `password_hash` (bcrypt), `created_at`, `is_active`. First user created via bootstrap endpoint; additional users blocked at the application layer. |
  ```

  Add immediately after:
  ```
  | `AlertRule` | `alert_rules` | User-defined rule that triggers notifications when scanner events match; stores filter criteria (scanner types, severity), channel delivery config, and per-ticker cooldown duration. |
  | `AlertDeliveryLog` | `alert_delivery_logs` | Immutable audit-trail row for every notification attempt (success or failure); FK to `alert_rules` and `scanner_events`. |
  | `AutoTradeOrder` | `auto_trade_orders` | Immutable record of every automated trade decision; tracks the full lifecycle from decision through IBKR submission, fill, and exit. |
  | `TradingStrategy` | `trading_strategies` | Risk/reward parameter set for automated trade execution (capital risk per trade, stop-loss, take-profit, session eligibility); referenced by `AlertRule`. |
  | `PushSubscription` | `push_subscriptions` | Browser Web Push subscription (endpoint URL + ECDH keys) for one device that has granted push-notification permission. |
  | `ScannerOutcomeSnapshot` | `scanner_outcome_snapshots` | Price-action capture at a specific time offset after a scanner signal fires (e.g. +30 min, +1 day); input for outcome backtesting. |
  | `ScannerOutcomeSummary` | `scanner_outcome_summaries` | One-row derived signal-quality summary (MFE, MAE, MFE/MAE ratio) aggregated from a scanner event's outcome snapshots. |
  | `SystemConfig` | `system_config` | Key/value store for system-wide settings (e.g. signal-ranker weights and feature flags) updatable at runtime via the Settings page without redeploy. |
  ```

- [ ] 2.4 Verify all 8 rows now appear (test passes — use the same table-row pattern as 2.1):

  ```bash
  for model in AlertRule AlertDeliveryLog AutoTradeOrder TradingStrategy PushSubscription ScannerOutcomeSnapshot ScannerOutcomeSummary SystemConfig; do
    count=$(grep -c "| \`${model}\`" ARCHITECTURE.md); echo "$model: $count table row(s)"
  done
  ```

  Expected: each model shows exactly **1** table row hit.

- [ ] 2.5 Commit:

  ```bash
  git add ARCHITECTURE.md
  git commit -m "docs(#201): add 8 missing model rows to ARCHITECTURE.md model table"
  ```

---

## Task 3 — Add 2 missing router rows to ARCHITECTURE.md router table

**Files:** `ARCHITECTURE.md`, `backend/app/routers/alerts.py`, `backend/app/routers/auto_trading.py`

### Steps

- [ ] 3.1 Confirm both routers are absent from the router table (write failing test):

  ```bash
  grep -n "alerts\.py\|auto_trading\.py" ARCHITECTURE.md
  ```

  Expected: zero hits.

- [ ] 3.2 Confirm router prefixes and all endpoint paths by reading the files:

  ```bash
  grep -n "^router = APIRouter\|@router\.\(get\|post\|patch\|delete\)" backend/app/routers/alerts.py
  grep -n "^router = APIRouter\|@router\.\(get\|post\|patch\|delete\)" backend/app/routers/auto_trading.py
  ```

- [ ] 3.3 In `ARCHITECTURE.md`, find the last row of the `### Routers` table (the `tweets.py` row) and insert 2 new rows immediately after it.

  Find the `tweets.py` row (anchor text):
  ```
  | `tweets.py` | `GET /api/v1/tweets/recent` — recent TweetSignals (filter by classification/promoted); `WS /api/v1/tweets/feed` — live WebSocket stream of all new tweet signals from Redis `tweet_signals:all` channel |
  ```

  Add immediately after:
  ```
  | `alerts.py` | `GET /api/v1/alerts/stats`, `GET/POST /api/v1/alerts/rules`, `PATCH/DELETE /api/v1/alerts/rules/{id}`, `POST /api/v1/alerts/rules/{id}/test`, `GET /api/v1/alerts/logs`, Web Push CRUD (`/api/v1/alerts/push/*`: VAPID key, subscribe, unsubscribe), `POST /api/v1/alerts/infrastructure` (Grafana webhook) |
  | `auto_trading.py` | `GET/POST /api/v1/trading/strategies`, `GET/PATCH/DELETE /api/v1/trading/strategies/{id}`, `GET /api/v1/trading/orders`, `GET /api/v1/trading/orders/{id}`, `POST /api/v1/trading/orders/{id}/approve\|reject\|cancel`, `GET /api/v1/trading/account`, `GET /api/v1/trading/stats`, `GET/PATCH /api/v1/trading/config` |
  ```

- [ ] 3.4 Verify both rows appear (test passes):

  ```bash
  grep -n "alerts\.py\|auto_trading\.py" ARCHITECTURE.md
  ```

  Expected: **2 hits** — one per router file.

- [ ] 3.5 Commit:

  ```bash
  git add ARCHITECTURE.md
  git commit -m "docs(#201): add alerts.py and auto_trading.py router rows to ARCHITECTURE.md"
  ```

---

## Task 4 — Extend topology mermaid diagram with 4 new services

**Files:** `ARCHITECTURE.md`, `docker-compose.yml`

### Steps

- [ ] 4.1 Confirm the 4 services are absent from the diagram (write failing test):

  ```bash
  grep -n "seqgelf\|seq-gelf\|darkfactory\|dark-factory\|backlogsched\|backlog-scheduler\|forecastworker\|forecast-worker" ARCHITECTURE.md | head -20
  ```

  Expected: zero hits in the mermaid topology block.

- [ ] 4.2 Confirm network membership and `depends_on` for each service in `docker-compose.yml` (derive only edges that `depends_on` or documented behavior confirms):

  ```bash
  grep -A 20 "^  seq-gelf:" docker-compose.yml | grep -E "depends_on|networks|image" | head -10
  grep -A 20 "^  forecast-worker:" docker-compose.yml | grep -E "depends_on|networks" | head -10
  grep -A 20 "^  backlog-scheduler:" docker-compose.yml | grep -E "depends_on|networks" | head -10
  grep -A 20 "^  dark-factory:" docker-compose.yml | grep -E "depends_on|networks" | head -10
  ```

  Confirmed edges (source authority for each):
  - `seq-gelf` → `seq`: `depends_on: seq` in compose (line confirmed by grep above)
  - `forecast-worker` → `postgres`, `forecast-worker` → `redis`: `depends_on: postgres, redis` in compose (confirmed by grep above)
  - `backlog-scheduler` → `postgres`, `backlog-scheduler` → `redis`: no `depends_on` block in compose, but the spec's own topology table (`docs/superpowers/specs/2026-06-05-documentation-hygiene-design.md`, "Stale Topology Diagram" section) explicitly lists these two edges as "Primary edges" — this constitutes the "documented behavior" the spec permits as an alternative to `depends_on`
  - `dark-factory`: no `depends_on` in compose and no explicit edges in spec table; place in separate `factory-network` subgraph with no edge lines to draw

- [ ] 4.3 Edit `ARCHITECTURE.md`: inside the `subgraph net["stockscanner-network"]` block, add `seqgelf` and `forecastworker` nodes immediately before the closing `end`.

  Find (preserve the 4-space indentation on both lines to match the surrounding mermaid):
  ```
      jaeger["jaeger :16686/:4317"]
      end
  ```

  Replace with:
  ```
      jaeger["jaeger :16686/:4317"]
      seqgelf["seq-gelf (GELF input)"]
      forecastworker["forecast-worker (TimesFM)"]
      end
  ```

  Note: `end` closes the `subgraph net` block. The actual file uses **8-space** indentation for all nodes inside this subgraph (confirmed: `        jaeger[...]` at 8 spaces). Re-read the exact whitespace of the `jaeger` and `end` lines before editing, and use 8-space indentation for the two new nodes as well.

- [ ] 4.4 Add the `factory-network` subgraph and all new edges. Append after the last existing edge block in the mermaid diagram (after the `jaeger -->|OTLP| beat` line):

  Find:
  ```
      jaeger -->|OTLP| celery
      jaeger -->|OTLP| beat
  ```

  Replace with:
  ```
      jaeger -->|OTLP| celery
      jaeger -->|OTLP| beat

  subgraph factory["factory-network"]
      darkfactory["dark-factory"]
      backlogsched["backlog-scheduler"]
  end

  seqgelf -->|"GELF forward"| seq
  forecastworker --> postgres
  forecastworker --> redis
  backlogsched --> postgres
  backlogsched --> redis
  ```

- [ ] 4.5 Verify all 4 new services appear in the diagram (test passes):

  ```bash
  grep -n "seqgelf\|darkfactory\|backlogsched\|forecastworker" ARCHITECTURE.md
  ```

  Expected: at least 4 hits (node definitions + edge lines will each match).

- [ ] 4.6 Commit:

  ```bash
  git add ARCHITECTURE.md
  git commit -m "docs(#201): add seq-gelf, dark-factory, backlog-scheduler, forecast-worker to topology mermaid"
  ```

---

## Task 5 — Verify pre-resolved items and run full acceptance check

**Files:** `docs/adr/`, `CLAUDE.md`, `README.md`, `ARCHITECTURE.md`

### Steps

- [ ] 5.1 Verify ADR numbering (R10 — pre-resolved in PR #172, commit `154b95f`):

  ```bash
  ls docs/adr/ | grep -v README | grep -v template | wc -l
  ```

  ```bash
  grep -cE "^\| \[[0-9]" docs/adr/README.md
  ```

  Note: ADR index rows are formatted `| [0001]...`, so the pattern must match `[` after the pipe-space. Expected: both counts equal 11 (or the same non-zero count). No edit needed — confirm only.

- [ ] 5.2 Verify `docs/` casing (R9 — pre-resolved in PR #171, commit `3058b22`):

  ```bash
  grep -rn "Docs/" CLAUDE.md README.md ARCHITECTURE.md
  ```

  Expected: **zero hits**.

- [ ] 5.3 Run R8 acceptance grep — async SQLAlchemy drift fully eliminated:

  ```bash
  grep -rn "async SQLAlchemy\|AsyncSession" CLAUDE.md README.md ARCHITECTURE.md
  ```

  Expected: **zero hits** (any remaining `AsyncSession` mention must be in a "do not use" context — but the spec requires zero hits here, so flag any match).

- [ ] 5.4 Confirm R5 — all 8 new model rows present:

  ```bash
  for model in AlertRule AlertDeliveryLog AutoTradeOrder TradingStrategy PushSubscription ScannerOutcomeSnapshot ScannerOutcomeSummary SystemConfig; do
    count=$(grep -c "$model" ARCHITECTURE.md); echo "$model: $count hits"
  done
  ```

  Expected: each model name shows ≥ 1 hit.

- [ ] 5.5 Confirm R6 — both new router rows present:

  ```bash
  grep -n "alerts\.py\|auto_trading\.py" ARCHITECTURE.md
  ```

  Expected: 2 hits.

- [ ] 5.6 Confirm R7 — all 4 topology nodes present:

  ```bash
  grep -n "seqgelf\|darkfactory\|backlogsched\|forecastworker" ARCHITECTURE.md | wc -l
  ```

  Expected: ≥ 4 (node definitions + edges each match).

- [ ] 5.7 Confirm no uncommitted changes remain:

  ```bash
  git status
  ```

  Expected: clean working tree (all edits from Tasks 1–4 are committed).
