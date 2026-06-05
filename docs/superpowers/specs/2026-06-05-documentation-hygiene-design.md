# Documentation Hygiene: Sync/Async Drift, Stale Tables, ADR Numbering, Docs Casing

> Tracking issue: [#201](https://github.com/omniscient/markethawk/issues/201)

## Goal

Fix four documentation-hygiene defects identified in Architecture Quality Report v2 (risks R11 + R13). The primary goal is accuracy: docs that claim the backend uses async SQLAlchemy mislead both human developers and dark-factory agents into writing incorrect code. The secondary goal is completeness: ARCHITECTURE.md's model/router/topology tables are missing 8 models, 2 routers, and 4 infrastructure services.

## Scope

**In scope:**
- Correct all sync/async statements in `CLAUDE.md`, `README.md`, and `ARCHITECTURE.md` to match ADR-0004 and `core/database.py` (synchronous, psycopg2-binary).
- Fix the false `[AVOID]` entry in `.archon/memory/backend-patterns.md` that claims the app uses `AsyncSession throughout`.
- Add 8 missing model rows to the ARCHITECTURE.md model table (read each model file for descriptions).
- Add 2 missing router rows (`alerts.py`, `auto_trading.py`) to the ARCHITECTURE.md router table.
- Update the mermaid topology diagram in ARCHITECTURE.md to include `seq-gelf`, `dark-factory`, `backlog-scheduler`, and `forecast-worker`.
- Verify the two pre-resolved items (ADR numbering, `docs/` casing) with bounded grep checks and close them off.

**Out of scope:**
- Rewriting or restructuring `.archon/memory/backend-patterns.md` beyond the single false entry.
- Updating `docs/adr/` filenames or adding new ADR content (already resolved in prior PRs #171, #172).
- Fixing documentation inside `docs/archive/` or any archived spec/plan files.
- Code changes — this is documentation only; no model files, no migration, no backend logic.

## Architecture / Approach

This is a documentation-only change. All four deliverables touch markdown files and one machine-generated memory file.

### Sync/Async Drift

The backend is synchronous. `backend/app/core/database.py` uses `create_engine`, `sessionmaker`, and `Session` (not `AsyncSession`). The driver is `psycopg2-binary`. ADR-0004 (`docs/adr/0004-synchronous-sqlalchemy.md`) explicitly documents this as a deliberate short-term choice with async migration deferred to issue #103.

**Files to fix:**

| File | Current (wrong) | Correct |
|------|----------------|---------|
| `CLAUDE.md` (Tech Stack line) | `FastAPI + SQLAlchemy 2.0 (async)` | `FastAPI + SQLAlchemy 2.0 (sync)` |
| `README.md` (Backend line) | `SQLAlchemy 2.0 (async)` | `SQLAlchemy 2.0 (sync, psycopg2)` |
| `ARCHITECTURE.md` `database.py` module map entry | `Async SQLAlchemy engine and session factory (AsyncSession). get_db() dependency.` | `Synchronous SQLAlchemy engine and session factory (Session, psycopg2-binary). get_db() dependency.` |
| `.archon/memory/backend-patterns.md` | `[AVOID] Never use synchronous SQLAlchemy patterns … the app uses AsyncSession throughout` | Rewrite to reflect sync reality: `select()` + `session.execute()` is correct; `AsyncSession` / `await` is not used |

**Note for implement agent:** Do not rely on line numbers from the issue body — re-grep the files at implementation time since prior PRs may have shifted them.

### Stale Model Table

8 model files exist in `backend/app/models/` but are absent from the ARCHITECTURE.md model table (lines labeled "Database Models"):

| Model Class | Table | Source file |
|-------------|-------|-------------|
| `AlertRule` | `alert_rules` | `backend/app/models/alert_rule.py` |
| `AlertDeliveryLog` | `alert_delivery_logs` | `backend/app/models/alert_delivery_log.py` |
| `AutoTradeOrder` | `auto_trade_orders` | `backend/app/models/auto_trade_order.py` |
| `TradingStrategy` | `trading_strategies` | `backend/app/models/trading_strategy.py` |
| `PushSubscription` | `push_subscriptions` | `backend/app/models/push_subscription.py` |
| `ScannerOutcomeSnapshot` | `scanner_outcome_snapshots` | `backend/app/models/scanner_outcome_snapshot.py` |
| `ScannerOutcomeSummary` | `scanner_outcome_summaries` | `backend/app/models/scanner_outcome_summary.py` |
| `SystemConfig` | `system_config` | `backend/app/models/system_config.py` |

The implement agent must read each file and write a real one-sentence purpose description matching the existing table style (e.g. compare `SignalReview`'s entry for length and specificity). No TBD placeholders.

### Stale Router Table

2 routers in `backend/app/routers/` are missing from the ARCHITECTURE.md router table:

| File | Source file to read |
|------|---------------------|
| `alerts.py` | `backend/app/routers/alerts.py` |
| `auto_trading.py` | `backend/app/routers/auto_trading.py` |

The existing table format is `| File | Endpoints |` with endpoint paths and brief descriptions. The implement agent should read each router file and follow the same format. The issue body's mention of a `trading.py` label is stale; there is no such row — the fix is purely additive.

### Stale Topology Diagram

The mermaid `graph TD` in ARCHITECTURE.md (the service topology section) omits 4 containers present in `docker-compose.yml`:

| Container name | Compose service | Primary edges |
|---------------|-----------------|---------------|
| `seq-gelf` (stockscanner-seq-gelf) | `seq-input-gelf` image | `seq-gelf --> seq` |
| `dark-factory` (markethawk-dark-factory) | factory image, `factory-network` | Separate subgraph (isolated network, not wired into main `stockscanner-network` mesh) |
| `backlog-scheduler` | same factory image | `backlog-scheduler --> postgres`, `backlog-scheduler --> redis` |
| `forecast-worker` (stockscanner-forecast-worker) | timesfm image | `forecast-worker --> postgres`, `forecast-worker --> redis` |

The implement agent must read the relevant `docker-compose.yml` sections for each service (look at `depends_on`, `networks`) to confirm edges before adding them. The diagram uses conservative edge sets — only add edges that `depends_on` or documented behavior confirms.

### Pre-Resolved Items (Verify Only)

**ADR numbering** — resolved in PR #172 (commit `154b95f`). The directory now has `0010-api-versioning-policy.md` and `0011-dark-factory-gelf-logging.md` with consistent 4-digit padding throughout. `docs/adr/README.md` has a complete 11-row index.

**`docs/` casing** — resolved in PR #171 (commit `3058b22`). No uppercase `Docs/` paths remain in CLAUDE.md, README.md, or ARCHITECTURE.md.

Acceptance criteria for both: run the verification greps listed in the Requirements section. If they pass, no code change is needed for these items.

## Requirements

- **R1** `CLAUDE.md` describes the backend as `SQLAlchemy 2.0 (sync)` (not async).
- **R2** `README.md` describes the backend as `SQLAlchemy 2.0 (sync, psycopg2)` (not async).
- **R3** `ARCHITECTURE.md`'s `database.py` module map entry describes a synchronous `Session` / psycopg2-binary setup, not `AsyncSession`.
- **R4** `.archon/memory/backend-patterns.md` no longer contains the false claim that the app uses `AsyncSession` throughout. The corrected entry reflects the synchronous reality (only the one false AVOID entry is touched; the rest of the file is unchanged).
- **R5** `ARCHITECTURE.md` model table contains rows for all 8 missing models, each with a real one-sentence purpose derived from the model file.
- **R6** `ARCHITECTURE.md` router table contains rows for `alerts.py` and `auto_trading.py` with real endpoint lists matching the existing table style.
- **R7** `ARCHITECTURE.md` topology mermaid diagram contains nodes for `seq-gelf`, `dark-factory`, `backlog-scheduler`, and `forecast-worker` with edges derived from `docker-compose.yml`.
- **R8** `grep -rn "async SQLAlchemy\|AsyncSession" CLAUDE.md README.md ARCHITECTURE.md` returns zero hits on lines that claim the ORM or session factory is async.
- **R9** `grep -rn "Docs/" CLAUDE.md README.md ARCHITECTURE.md` returns zero hits (pre-resolved; verify only).
- **R10** `ls docs/adr/ | grep -v README | grep -v template | wc -l` equals the row count in `docs/adr/README.md`'s index table (pre-resolved; verify only).

## Alternatives Considered

### Partial fix: skip memory file correction
Leave `.archon/memory/backend-patterns.md` for the implement agent that discovers it. Rejected because the memory file is the most dangerous location for this error: unlike human-read docs, it is injected verbatim as agent instructions, causing future dark-factory runs to actively generate broken async code. The refine agent is authorized to fix it as part of the same acceptance criterion ("Correct the sync/async statements to match ADR-0004 + code").

### Defer topology diagram to a separate issue
The four omitted services require reading docker-compose sections, not reverse-engineering inter-service protocols. Each new node is 1–2 lines of mermaid. The issue body explicitly names these four as a defect. Deferral would create a gap between R5 (model table complete) and topology completeness. Rejected.

### Broad audit of all `.md` files for casing and ADR issues
Re-audit all `.md` files, CI scripts, and compose references for `Docs/` and ADR issues. Rejected: both are confirmed resolved in prior PRs; a broad re-audit is over-scoped for a `size: S` issue and reproduces already-landed work. Bounded grep checks are sufficient.

## Assumptions

- `backend/app/core/database.py` will remain synchronous until issue #103 (async migration) lands; this spec does not accelerate or conflict with that work.
- The dark-factory implement agent reads model files directly to craft purpose descriptions rather than guessing from class names alone.
- The mermaid diagram update is additive only; no existing nodes or edges are removed.
- The `.archon/memory/backend-patterns.md` "Do not edit manually" header is advisory and is explicitly overridden by the `ready-for-agent` authorization on this issue; only the one false entry is hand-corrected.
- Line numbers cited in the issue body (`CLAUDE.md:11`, `ARCHITECTURE.md:14,63`, etc.) may be stale; implement agent must re-grep at implementation time.
