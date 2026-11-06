# Portfolio — Accounts, Positions, Constraints, Allocation — Design Spec

**Issue:** #907
**Date:** 2026-11-06
**Status:** Proposed — pending implementation plan

## 1. Overview / Problem Statement

Epic #902 (Long-term ETF investing) needs a place to record what is actually held — across
several manually-entered brokerage accounts, in more than one currency — and constraints on
how that should be allocated by ticker, segment, tag, and cash. This is slice 4 of the epic's
5-slice serial rollout: it depends on the roster (`lt_etf`), static universe, FX
(`fx_rate_daily`), and MCP server sidecar built in slices 1–3 (#904, #905, #906), which this
spec assumes are merged by the time this is implemented.

Scope is epic §4.4 (Portfolio models) minus `lt_target_allocation`/`lt_proposal`, §4.6 (REST,
minus proposals), §4.7 (the non-proposal subset of the MCP tool list, plus the two roster-write
tools — see §3.2), and §4.8 (Portfolio tab only, not Proposals). Targets, proposals, and drift
are explicitly out of scope (slice 5, #908+).

## 2. Requirements (from Q&A)

1. Models: `lt_account`, `lt_position` (upsert keyed on `(account_id, ticker)`, cash
   pseudo-tickers `CASH:USD`/`CASH:CAD`, `source` manual|agent), `lt_constraint` (`kind`
   max_pct|min_pct; `scope` segment|tag|ticker|cash). Single-tenant, no `user_id`.
2. Reporting-currency setting in `SystemConfig`, default `CAD`.
3. `LongTermPortfolioService.get_allocation()`: market value = quantity × latest close,
   converted to the reporting currency via `fx_rate_daily`; grouped by ticker, segment, tag,
   cash. Shared by REST and MCP so they never disagree.
4. `evaluate_constraints(allocation)`: per-constraint current exposure and pass/fail.
5. `add_roster_etf`/`deactivate_roster_etf` MCP tools (and matching REST endpoints) ship in
   this slice, even though they touch the `lt_etf` roster model from #904 — see §3.2 for why.
6. `lt_position.currency` is authoritative per position (not inherited from `lt_account`); an
   account can hold positions in more than one currency. `upsert_positions` validates/fills it
   from the roster's listing currency or the cash pseudo-ticker's suffix — it never accepts an
   arbitrary value.
7. A position priced against a roster ticker with no `StockAggregate` row yet (or no FX rate)
   must not fail `get_allocation`, be valued at $0, or fall back to `avg_cost` — it is excluded
   from valued totals and surfaced explicitly (§3.4).
8. Frontend Portfolio tab: accounts, positions with inline edit, allocation donut by segment,
   constraint bars (current exposure vs. cap/floor).
9. Done when: an agent can `upsert_positions` for two accounts in different currencies and
   `get_allocation` returns correct percentages in CAD with constraint pass/fail.

## 3. Architecture / Approach

### 3.1 Models (`backend/app/models/long_term.py`, new Alembic migration)

Following the existing `Integer` PK + `utc_now` timestamp convention
(`backend/app/models/alert_rule.py`, `stock_universe.py`) and unparameterized `Numeric` for
money columns (`futures_aggregate.py` open/high/low/close, `scanner_event.py`
previous_close/opening_price/closing_price — `Float` is reserved for computed ratios like
`stock_metric.py`'s `sma_50`/`atr_14`, not money):

```python
class LtAccount(Base):
    __tablename__ = "lt_accounts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    broker = Column(String(100), nullable=True)
    currency = Column(String(3), nullable=False)  # primary/display currency only — see §3.3
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

class LtPosition(Base):
    __tablename__ = "lt_positions"
    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("lt_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker = Column(String(20), nullable=False)  # roster ticker or CASH:USD / CASH:CAD
    quantity = Column(Numeric, nullable=False)
    avg_cost = Column(Numeric, nullable=True)
    currency = Column(String(3), nullable=False)  # authoritative — see §3.3
    as_of = Column(Date, nullable=False)
    source = Column(String(10), nullable=False)  # "manual" | "agent"
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    __table_args__ = (UniqueConstraint("account_id", "ticker", name="uq_lt_position_account_ticker"),)

class LtConstraint(Base):
    __tablename__ = "lt_constraints"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    kind = Column(String(10), nullable=False)      # "max_pct" | "min_pct"
    scope = Column(String(10), nullable=False)     # "segment" | "tag" | "ticker" | "cash"
    scope_value = Column(String(50), nullable=True)  # NULL for scope="cash" (single bucket)
    threshold_pct = Column(Numeric, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
```

`uq_lt_position_account_ticker` backs the `(account_id, ticker)` upsert directly — no existing
model in this repo has this exact composite-upsert shape (`StockUniverseTicker` is a plain join
row with no conflict semantics), so `upsert_positions` uses SQLAlchemy's
`insert(...).on_conflict_do_update(index_elements=["account_id", "ticker"], ...)` (Postgres
dialect, already available via the existing `psycopg`/SQLAlchemy 2.0 stack).

`scope_value` validation differs by `scope` (epic §4.1 is the source for segment/tag
semantics): `segment` must match one of the fixed roster segments (closed set, e.g. query
distinct `lt_etf.segment`); `tag` is intentionally free-form, matching the roster's "sub-segment
tags are free-form labels" design so constraints can group across countries (e.g. `energy` =
`XLE` + `XEG.TO`); `ticker` must resolve to an active roster ticker or a cash pseudo-ticker;
`cash` has no `scope_value` (reject if one is supplied).

Add `LtAccount`/`LtPosition`/`LtConstraint` to `backend/app/models/__init__.py` per the
CLAUDE.md "New Models" rule, then `python -m alembic revision --autogenerate -m
"add_lt_account_lt_position_lt_constraint"` and `alembic upgrade head`.

### 3.2 Roster-write tools land in this slice (not #904, not a later slice)

`add_roster_etf`/`deactivate_roster_etf` operate on the `lt_etf` model `#904` owns, but #904's
own scope explicitly excludes "portfolio, MCP" and epic §4.1 states the roster "is editable
from the page and through the MCP server (add, deactivate, re-segment)" — this is the first
slice with MCP write tools, so these two land here. Add `add_etf(...)`/`deactivate_etf(ticker)`
to `services/long_term/roster.py` (the module #904 creates) so REST, MCP, and any future
roster-editing UI share one code path:

- `add_etf`: validates the ticker isn't already in the roster and that required fields
  (segment, country, listing currency, exchange, `data_source`, tags) are present; does not
  backfill bars/dividends itself — that happens on the next nightly sync against the rebuilt
  static universe.
- `deactivate_etf`: soft delete (`is_active=False`). Existing `lt_position`/`lt_constraint`
  rows referencing the ticker are left as-is (a deactivated ticker can still be held/priced;
  it just drops out of new allocation/constraint scope-value validation and the static
  universe's next `/refresh`).
- REST: `POST /api/v1/long-term/roster`, `POST /api/v1/long-term/roster/{ticker}/deactivate`
  — added for consistency with §4.6's "endpoints mirror MCP tools one for one" rule. No
  roster-editing UI in this slice (the issue's frontend bullet covers only the Portfolio tab);
  "re-segment" is not among the tools this issue names and stays out of scope.

### 3.3 Position currency is authoritative, independent of account currency

A single `lt_account` can hold positions in more than one currency (e.g. a Canadian brokerage
account holding both a USD-listed ETF and a `CASH:CAD` balance) — `lt_account.currency` is only
the account's primary/display currency. `lt_position.currency` is therefore not a free-text
field on the upsert payload: `upsert_positions` resolves the expected value — the roster row's
listing `currency` for an ETF ticker, or the pseudo-ticker's suffix for cash (`CASH:USD` →
`USD`) — fills it in when omitted, and rejects the write (422, not a silent correction) when a
supplied value disagrees. `LongTermPortfolioService` never compares position currency to
account currency; it only uses position currency to pick the `fx_rate_daily` conversion.

### 3.4 `LongTermPortfolioService` (`services/long_term/portfolio.py`)

```
get_allocation() -> AllocationResult:
    for each active account's active positions:
        if ticker is a cash pseudo-ticker:
            market_value = quantity  (already a currency amount, no price lookup)
        else:
            look up latest StockAggregate.close for ticker
            if missing -> add to unpriced_positions (reason="no_price"), skip from totals
        look up fx_rate_daily rate for position.currency -> reporting currency
        if missing -> add to unpriced_positions (reason="no_fx_rate"), skip from totals
        else convert market_value to reporting currency; stamp price_date used
    aggregate converted market values by ticker / segment / tag / cash -> percentages
    return AllocationResult(allocations=..., unpriced_positions=[...], complete=bool(not unpriced_positions))

evaluate_constraints(allocation) -> ConstraintReport:
    for each active lt_constraint:
        current_exposure = allocation lookup by (scope, scope_value)
        pass = current_exposure <= threshold_pct (max_pct) or >= threshold_pct (min_pct)
    constraint_report.complete = allocation.complete  # propagate partial-data flag
```

This mirrors the existing precedent for data gaps rather than inventing a new one:
`DataReadinessService` (`backend/app/services/data_readiness.py`) attaches structured warnings
(`stale_data`, `missing_required_timespan`) and lets the caller proceed rather than failing the
request. Excluding, zeroing, or faking a valuation would each silently distort every
constraint's pass/fail; surfacing `unpriced_positions` + `complete: bool` lets the agent and the
page both know a constraint "pass" was computed over partial data. This is the direct
precedent for a newly-`add_roster_etf`'d ticker that hasn't had its first nightly sync yet.

Shared by both callers so they can't disagree: the REST router and the MCP tools both call
`LongTermPortfolioService.get_allocation()`/`evaluate_constraints()` directly — neither
reimplements the aggregation.

### 3.5 REST API (`backend/app/routers/long_term.py`, prefix `/api/v1/long-term`)

Same cookie auth as every other router (registered in `app/main.py` alongside the existing
`include_router(...)` calls). Pydantic schemas in `backend/app/schemas/long_term.py`; CRUD
shape follows the existing `universe.py` router's resource-scoped route style:

- `POST /accounts`, `GET /accounts`, `PUT /accounts/{id}`, `DELETE /accounts/{id}` (soft
  delete via `is_active=False`, consistent with `lt_etf`/other soft-delete models in this
  codebase — no hard delete, so historical positions never dangle).
- `GET /positions?account_id=`, `POST /positions/upsert` (body: list of positions; delegates to
  the `(account_id, ticker)` upsert in §3.1).
- `POST /constraints`, `GET /constraints`, `PUT /constraints/{id}`, `DELETE /constraints/{id}`
  (soft delete).
- `GET /allocation` → `AllocationResult` + `ConstraintReport` (both computed together so the
  page never has to reconcile two calls).
- `POST /roster`, `POST /roster/{ticker}/deactivate` (§3.2).

### 3.6 MCP tools (`backend/mcp_server/`, introduced by #906)

Added to the tool set #906 scaffolds, importing `app.services.long_term.*` directly (no REST
round-trip, per epic §4.7): `list_accounts()`, `list_positions(account_id?)`,
`get_allocation()`, `upsert_positions(account_id, positions[], as_of, source)` (validates
tickers against the roster and currency per §3.3), `list_constraints()`,
`upsert_constraint(...)`, `deactivate_constraint(id)`, `add_roster_etf(...)`,
`deactivate_roster_etf(ticker)`. No tool for constraints to be bypassed silently — every write
tool routes through the same service functions the REST router calls.

### 3.7 Frontend — Portfolio tab (`frontend/src/pages/LongTerm/`)

Tab within the `/long-term` page scaffolded by the signals/page slice (#905); this issue adds
the Portfolio tab's content, not the page shell. API module additions in
`frontend/src/api/longTerm.ts`, React Query for all server state (accounts, positions,
constraints, allocation).

- **Accounts:** simple list/form (name, broker, currency, notes, active toggle) — no new
  pattern needed, follows existing modal-form conventions (`UniverseFormModal.tsx`).
- **Positions, inline edit:** follows the existing click-to-edit-cell pattern in
  `frontend/src/pages/ActiveWatchlist/WatchlistTable.tsx` (local `isEditing` state per row,
  Enter commits via a React Query mutation hook, Escape cancels) rather than inventing a new
  one — quantity/avg_cost/as_of editable inline, currency read-only (derived, per §3.3).
- **Allocation donut by segment:** Recharts, following the `dataviz` skill (read before
  writing chart code) and the project's existing chart color conventions.
- **Constraint bars:** current exposure vs. cap/floor per active constraint; a bar whose
  constraint is currently failing is visually flagged. When `get_allocation` returns
  `complete: false`, the tab shows a warning banner listing the unpriced positions and renders
  "no price" instead of a dollar value on the affected rows, rather than silently omitting
  them.

## 4. Alternatives Considered

1. **Drop `add_roster_etf`/`deactivate_roster_etf` from this issue, leave them for #904 or a
   later slice.** Rejected: #904's own scope explicitly excludes MCP/portfolio work, so they
   would have nowhere to land before this slice; the issue body names them explicitly as this
   slice's responsibility.
2. **Treat `lt_position.currency` as redundant with `lt_account.currency`, derive it instead
   of storing it.** Rejected: a single account can legitimately hold multi-currency
   positions (a USD ETF plus CAD cash in one Canadian brokerage account); collapsing the two
   fields would make that combination unrepresentable.
3. **Fail `get_allocation`/the Portfolio tab outright when any held ticker lacks a price.**
   Rejected: this would make the page and every MCP read tool unusable the moment a freshly
   `add_roster_etf`'d ticker hasn't completed its first nightly sync — a transient, expected
   state, not an error. Chosen instead: exclude-and-surface (§3.4), matching the codebase's
   existing `DataReadinessService` precedent.

## 5. Open Questions (non-blocking)

- Exact segment enum source for `lt_constraint.scope_value` validation (query distinct
  `lt_etf.segment` live vs. a hardcoded list mirrored from epic §4.1's table) — either works;
  left to the implementation plan since `lt_etf` doesn't exist in this checkout yet.
- Whether `lt_account`/`lt_constraint` deletes should be hard or soft; this spec assumes soft
  (`is_active=False`) for consistency with the rest of the codebase's delete conventions, but
  it wasn't asked explicitly in Q&A.

## 6. Assumptions (flagged)

- `#904` (roster, `lt_etf`, static universe, `fx_rate_daily`) and `#906` (MCP server sidecar,
  `backend/mcp_server/`, bearer-token auth) are merged into `main` by the time this issue is
  implemented. Neither exists in this checkout today; this spec is written against that
  assumed end state, consistent with the epic's serial rollout ordering.
- `#905` (signals + read-only `/long-term` page) has scaffolded the page shell and tab
  structure this issue's Portfolio tab plugs into.
- Postgres `ON CONFLICT` upsert is available and preferred over a read-then-write
  check-and-update for `(account_id, ticker)`, consistent with the existing SQLAlchemy 2.0 +
  `psycopg` stack.
