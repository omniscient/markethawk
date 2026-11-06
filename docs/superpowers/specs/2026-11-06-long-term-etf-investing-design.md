# Long-Term ETF Investing — Design

**Date:** 2026-11-06
**Status:** Draft, builder-checked, pending owner approval. Epic: https://github.com/omniscient/markethawk/issues/902
**Owner:** Frank

## 1. Intent

Add a long-term investing surface to MarketHawk, separate from the intraday
scanner, that follows a fixed roster of major ETFs covering every market segment
in the US and Canada. The purpose is to see, at a glance and on demand, which
segments are cheap relative to their own history, and to let an AI agent propose
buy-and-rebalance moves that respect allocation constraints, with the goal of
beating the S&P 500 over a multi-year horizon.

The feature is **AI-first**. The frontend page matters, but the primary
consumer is an agent connected through an MCP server. Every signal the page
shows must be available to the agent, pre-computed, through well-described
tools, and the agent must be able to read holdings, read constraints, and write
positions and proposals through the same server.

### Why now

Frank holds long-term positions across several brokerage accounts and today has
no single view of relative cheapness across segments, no machine-readable record
of holdings and constraints, and no way for an agent to propose a rebalance
against real data. MarketHawk already has daily-bar storage, a universe sync
job, charting, and an IBKR connection, so most of the plumbing exists.

## 2. Goals, non-goals, anti-goals

### Goals

1. A curated roster of about 65 US and Canadian ETFs with 5 years of daily
   history, kept current by the existing nightly sync.
2. A nightly signal table per ETF per day: trend (vs. 50/200-day SMA),
   drawdown from highs, price percentile within 1y and 5y lookbacks, returns
   over standard windows, volatility, and a transparent "on sale" score.
3. A **Long-Term** page: dashboard of what is on sale, what is moving, and
   above/below-SMA50 splits, plus a roster table and a per-ETF detail view
   reusing the existing chart with its SuperTrend ATR overlay.
4. Holdings across several manually-entered accounts, with allocation by
   ticker and by segment in one reporting currency.
5. Allocation constraints (caps and floors on segments, tickers, custom
   groups) that are visible on the page, editable there, and enforced on
   proposals.
6. Rebalance proposals written by agents, recorded in MarketHawk, shown with
   a constraint check and a diff against current allocation, accepted or
   rejected by a human.
7. An MCP server exposing all of the above as tools, authenticated, running as
   a sidecar in the compose stack.

### Non-goals (for this design)

- No order execution of any kind. Accepted proposals are executed by hand in
  the brokerages.
- No broker synchronisation of holdings. Positions are entered manually or by
  an agent reading a screenshot.
- No portfolio optimiser (mean-variance, risk parity). The agent reasons; the
  system records, checks, and displays.
- No tax-lot tracking, no dividend accounting, no performance attribution.
  Cost basis is stored but not used for anything beyond display.
- No intraday data. Daily close is the resolution.
- No backtest of the strategy. That can layer on the existing backtest epic
  later.

### Anti-goals (would make this a failure even if it works)

- An agent that can accept its own proposal, or any path by which a proposal
  changes holdings or targets without a human decision.
- An MCP server reachable on the Docker network or host without a credential.
- Constraints that are advisory only. A proposal that violates a constraint
  must be visibly blocked from acceptance.
- Signals the agent cannot explain. Every derived number must map to a
  documented formula; no opaque composite.
- Canadian ETFs treated as second-class (missing bars, missing FX) so the
  Canadian half of the portfolio is silently wrong.

## 3. Constraints and facts from recon

- Stock bars come from the Massive (Polygon) client with the ticker passed
  through raw (`backend/app/providers/massive.py:173`). Nothing in the repo
  handles `.TO` or any exchange suffix. Whether Polygon serves TSX symbols is
  unknown.
- The IBKR provider fetches historical bars for futures only; `get_bars` for
  stocks returns an empty list (`backend/app/providers/ibkr.py:176`). The
  chunked historical fetch and pacing limiter (55 requests per 10 minutes)
  exist and can be reused. The only stock contract in the repo hardcodes
  `Stock(symbol, "SMART", "USD")`.
- `StockAggregate.ticker` is `String(10)`; `StockUniverseTicker.ticker` is
  `String(50)`. There is no currency or exchange column on bars.
- There is no FX handling anywhere in the backend.
- Universes are filled by the screener on `/refresh`
  (`services/universe_orchestrator.py:34`), which wipes and recreates members.
  The nightly job `sync_universe_aggregates_nightly` (01:30 UTC, Tue–Sat)
  tops up only timespan/multiplier combinations already present for a
  universe's tickers. Backfill is manual via `POST /{id}/sync-aggregates`,
  capped at 1830 days per request.
- Existing indicator code: SMA 20/50/200 and ATR14 in
  `services/trend_pullback_scan.py`, ATR10 percentile rank in
  `services/pre_market_scan.py`. No drawdown, 52-week high, or price
  percentile code exists. The chart ATR overlay is the frontend SuperTrend
  computed in `frontend/src/utils/indicators.ts` and toggled in
  `StockChart`'s `showDoubleSuperTrend` prop.
- `Trade`, `TradeExecution`, `JournalEntry` are day-trade records. Nothing
  resembles holdings, accounts, targets, or allocation. New models are needed.
- Auth is a global ASGI middleware reading a JWT from the `access_token`
  cookie only, with CSRF on writes. No bearer tokens or API keys exist.
- Sidecars (`live-scanner`) reuse the backend image, run `python -m
  <package>.main` from `backend/<package>/`, and import `app.*` directly with
  their own DB session. The MCP server follows that pattern.
- Frontend routes are registered in `frontend/src/App.tsx` and the sidebar in
  `frontend/src/components/Layout.tsx` (`navigation` array).
- No `mcp`/`fastmcp` dependency exists yet.

## 4. Decisions

### 4.1 Roster

The seed roster is stored in a new table and seeded by migration. Segments
are the grouping unit for allocation and constraints. Every ETF carries:
ticker (app-wide form, `.TO` suffix for TSX), name, segment, country (`US` or
`CA`), listing currency, exchange, data source (`massive` or `ibkr`),
inception date, and an active flag.

| Segment | US | Canada |
|---|---|---|
| Broad market | SPY (benchmark), QQQ, DIA, IWM, VTI | XIU.TO, XIC.TO, VFV.TO |
| Style & size | VTV, VUG, VBR, MTUM, QUAL, SCHD | — |
| Sectors | XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC | XEG.TO, XFN.TO, ZEB.TO, XIT.TO, XMA.TO, XGD.TO, ZUT.TO, XRE.TO, ZPR.TO |
| Bonds & rates | BND, TLT, IEF, SHY, LQD, HYG, TIP | XBB.TO, XSB.TO, ZFL.TO |
| Commodities & miners | GLD, SLV, USO, DBC, GDX | — |
| International | VEA, VWO, EWJ, EWZ | XEF.TO, XEC.TO |
| Crypto | IBIT, ETHA | BTCC.TO, ETHX.TO |
| Tech themes | SMH, BOTZ, AIQ, CIBR, CLOU, ARKK | — |

Decisions made by the designer: leveraged and inverse funds are excluded;
Canadian health care and consumer sectors are covered by the US funds because
no liquid Canadian ETF exists; SKYY is dropped as a duplicate of CLOU. SPY is
flagged `is_benchmark`. The roster is editable from the page and through the
MCP server (add, deactivate, re-segment). Sub-segment tags (e.g. `energy`,
`gold`) are free-form labels on each ETF so constraints can group across
countries ("energy" = XLE + XEG.TO + USO).

### 4.2 Data path

**Universe.** One `StockUniverse` named `Long-Term ETFs` with a new
`kind = "static"` column (default `"screened"` for existing rows). For static
universes, `/refresh` rebuilds `StockUniverseTicker` and `MonitoredStock` from
the active roster rows instead of running the screener. This keeps the nightly
aggregate top-up working unchanged. The feature's roster table is the source
of truth; the universe is a mirror.

**Resolution.** Daily bars only: `timespan="day"`, `multiplier=1`. A one-time
backfill of 1830 days at daily resolution seeds history; the nightly job
tops it up from there.

**US tickers** use the existing Massive path unchanged for bars.

**Canadian tickers.** Polygon does not serve TSX, and the IBKR account's
Canadian market-data entitlement is unknown (decided with Frank: do not
depend on it). A new provider `backend/app/providers/yfinance_provider.py`
wraps the `yfinance` package and serves daily bars for roster rows with
`data_source="yfinance"`. It implements the same base-provider `get_bars`
contract, requests `auto_adjust=False` so stored closes are raw (consistent
with Massive), and maps the app ticker `XIU.TO` straight through, since
Yahoo uses the same suffix. The sync task routes by the roster row's data
source. The IBKR provider is not touched by this feature.

Known risk: `yfinance` is an unofficial client and can break on Yahoo-side
changes. Mitigations: pin the version, wrap calls in the existing provider
circuit-breaker pattern, and have the universe data-health check flag any
roster ticker whose latest bar is older than two trading days.

**Dividends (total return).** Decided with Frank: signals use total return.
A new table `lt_dividend` (`ticker`, `ex_date`, `cash_amount`, `currency`,
`source`) is filled nightly: US from the Polygon dividends reference
endpoint (`/v3/reference/dividends`), Canada from the yfinance provider's
dividend history. Backfilled for the same 1830 days. The signal task builds a
total-return close series per ticker by applying the standard adjustment
factor `(close_prev_ex - dividend) / close_prev_ex` cumulatively backwards
from the latest close, in memory, from raw closes plus dividend rows. Raw
closes stay in `StockAggregate`; the adjusted series is never stored, so a
corrected dividend record is picked up on the next run.

**Schema widening.** `StockAggregate.ticker` becomes `String(20)` to leave
room. Bars stay in listing currency; currency lives on the roster row, not the
bar.

**FX.** A new `fx_rate_daily` table (`pair`, `date`, `rate`). One pair for
now, `USDCAD`, fetched nightly from the yfinance provider (`CAD=X`), with
Polygon forex `C:USDCAD` as the fallback if the primary fails. Backfilled for
the same 1830 days. The reporting currency is a single system setting
(existing `SystemConfig` key/value store), default `CAD` (designer's call,
see §7). Allocation math converts every position's market value into the
reporting currency at the latest stored rate.

### 4.3 Signals

A new table `etf_signal_daily`, one row per active roster ticker per trading
day, computed by a Celery task that runs after the nightly aggregate sync.
It also recomputes the latest row on demand (endpoint and MCP tool) after a
manual backfill. All return, SMA, high, drawdown and percentile formulas use
the **total-return close series** built in memory from raw closes plus
dividend rows (§4.2). ATR and RSI use raw closes. The page and the tool
descriptions state that returns are total return.

| Column | Definition |
|---|---|
| `close`, `date` | latest close and its date |
| `ret_1d`, `ret_1w`, `ret_1m`, `ret_3m`, `ret_6m`, `ret_1y` | simple return over the window, by calendar offset |
| `sma_50`, `sma_200` | simple moving averages of close |
| `pct_from_sma_50`, `pct_from_sma_200` | `(close / sma - 1) * 100` |
| `above_sma_50`, `above_sma_200` | booleans |
| `golden_cross` | `sma_50 > sma_200` |
| `high_52w`, `drawdown_52w_pct` | highest close in 252 bars and `(close / high - 1) * 100` |
| `high_5y`, `drawdown_5y_pct` | same over all stored history, up to 1260 bars |
| `pctile_1y`, `pctile_5y` | percentile rank of today's close among closes in the window (0 = cheapest) |
| `atr_14_pct` | Wilder ATR14 as a percent of close |
| `rsi_14` | standard RSI |
| `rel_ret_1y_vs_benchmark` | `ret_1y - benchmark.ret_1y`, benchmark = SPY, computed in listing currency |
| `history_days` | count of stored daily bars |
| `short_history` | `history_days < 756` (about 3 years); the agent is told to discount long-lookback signals |
| `on_sale_score` | see below |

**On-sale score (v1 heuristic, expected to iterate).**
`on_sale_score = 100 - mean(pctile_1y, pctile_5y, clamp(50 + pct_from_sma_200, 0, 100))`.
Higher means cheaper relative to its own history. When `short_history` is
true, `pctile_5y` is dropped from the mean. The formula is documented on the
page and in the MCP tool description so the agent can reason about it rather
than trust it. The builder keeps it in one function so it can be swapped.

**Movers** on the dashboard are the top and bottom N by `ret_1w` and
`ret_1m`. **Trend split** is the above/below `sma_50` partition.

### 4.4 Portfolio models

New SQLAlchemy models, all under a `lt_` naming prefix in the DB.

**Tenancy (designer's call):** single-tenant. No `lt_*` table carries a
`user_id`; any logged-in user sees and decides on the one portfolio. This
matches every other model in the repo today. Per-user ownership is deferred
to the authorization epic #373, which will retrofit these tables with the
rest.

- `lt_account`: `id`, `name`, `broker`, `currency`, `notes`, `is_active`.
- `lt_position`: `account_id`, `ticker` (must exist in roster, or be a
  cash pseudo-ticker `CASH:USD` / `CASH:CAD`), `quantity`, `avg_cost`,
  `currency`, `as_of` (date the snapshot was taken), `source`
  (`manual` | `agent`), `updated_at`. Upsert keyed on `(account_id, ticker)`.
  Market value is computed, not stored: `quantity * latest_close`, converted
  to the reporting currency.
- `lt_constraint`: `id`, `name`, `kind` (`max_pct` | `min_pct`), `scope`
  (`segment` | `tag` | `ticker` | `cash`), `scope_value`, `threshold_pct`,
  `is_active`, `notes`. Example: `max_pct` / `tag` / `energy` / `15`.
- `lt_target_allocation`: `id`, `created_at`, `source_proposal_id`
  (nullable), `is_current`. Lines in `lt_target_allocation_line` (`ticker`,
  `target_pct`). Exactly one current target at a time; accepting a proposal
  creates a new one and flips `is_current`.
- `lt_proposal`: `id`, `created_at`, `created_by` (free-text agent or user
  identity string), `status` (`pending` | `accepted` | `rejected`),
  `rationale` (markdown), `constraint_report` (JSON: per constraint, current
  exposure, proposed exposure, pass/fail), `decided_at`, `decision_note`,
  `has_violations`. Lines in `lt_proposal_line` (`ticker`, `target_pct`,
  `action` `buy` | `sell` | `hold`, `est_amount` in reporting currency,
  `account_id` nullable, `note`).

**Proposal semantics (designer's call):** a proposal is a **complete**
portfolio-wide target. Any ticker currently held but absent from the lines
is treated as target 0% and the server adds an implied `sell` line for it,
so the diff, the constraint report and the resulting target allocation are
always complete. `check_allocation` returns those implied sells so the agent
sees them before writing. Targets are portfolio-wide percentages, not
per-account; `account_id` on a line is an optional execution hint ("buy
VFV.TO in the CAD account") that the page shows and nothing else uses.

**Allocation computation** (`LongTermPortfolioService`): sum position market
values in the reporting currency across active accounts; group by ticker,
segment, tag, and cash; return percentages. The same function evaluates a
proposed allocation against active constraints and produces the
`constraint_report`. Used by both the page and the MCP server so they never
disagree.

### 4.5 Proposal flow

1. Agent (or user) calls `check_allocation` with a proposed set of
   `ticker -> target_pct` and gets the constraint report back. Optional but
   expected.
2. Agent calls `create_proposal` with lines and rationale. The server
   computes and stores the constraint report, the diff against the current
   allocation, and estimated amounts. Proposals with violations are **stored**
   (so the human sees what the agent wanted) but marked `has_violations`.
3. The page lists pending proposals with the diff, the rationale, and the
   constraint report. **Accept** is disabled while any violation exists.
   Reject takes an optional note.
4. Accept creates a new current target allocation. Holdings are untouched.
5. Positions change only through `upsert_positions` (page form or agent from
   a screenshot), which is the same flow as the initial entry. The page shows
   drift between current allocation and the current target.
6. Agents cannot accept or reject. The MCP server has no tool for it; the
   REST endpoint for decisions requires the browser session.

### 4.6 REST API

New router `backend/app/routers/long_term.py`, prefix `/api/v1/long-term`,
same cookie auth as everything else. Endpoints mirror the MCP tools one for
one (roster, signals, accounts, positions, constraints, targets, proposals,
plus `POST /proposals/{id}/accept|reject` which is browser-only). Pydantic
schemas in `schemas/long_term.py`. Services in `services/long_term/`
(`roster.py`, `signals.py`, `portfolio.py`, `proposals.py`).

### 4.7 MCP server

- Package `backend/mcp_server/`, run as compose service `mcp-server` with
  `command: python -m mcp_server.main`, copying the `live-scanner` service
  block (image, env, depends_on, network, memory limit, `volumes: []` with the
  bind-mount restored in the override file).
- **Exposure (decided with Frank):** the agent runs on the Docker host
  (Claude Code or Desktop). The service publishes `127.0.0.1:8010:8010` only,
  plain HTTP. No Caddy route, no public exposure. Remote access, if ever
  wanted, is a separate change with its own security review.
- Library: the official `mcp` Python package (FastMCP API), transport
  streamable HTTP. Added to `backend/requirements.txt`.
- **Auth:** a static bearer token from env `MCP_API_TOKEN` (required,
  minimum 32 characters, validated at startup like `JWT_SECRET_KEY`).
  Requests without it get 401. Added to `ENV_VARIABLES.md`, root `.env`
  example, and the preview-env contract.
- The server imports `app.services.long_term.*` and uses its own DB session.
  It does not call the REST API.
- Tools (names final, descriptions written for an agent reader, each with the
  on-sale formula and the `short_history` caveat where relevant):
  - `list_roster(segment?, country?)` → roster rows with latest signals
  - `get_etf(ticker, history_days?)` → roster row, latest signals, daily
    closes and SMA series for charting or reasoning
  - `get_market_overview()` → on-sale top N, movers, trend split counts by
    segment, benchmark signals; the "open the page" summary in one call
  - `refresh_signals(tickers?)` → recompute latest signal rows
  - `list_accounts()`, `list_positions(account_id?)`
  - `get_allocation()` → current allocation by ticker / segment / tag / cash,
    in the reporting currency, with the current target and drift
  - `upsert_positions(account_id, positions[], as_of, source)` → write
    positions; validates tickers against the roster
  - `list_constraints()`, `upsert_constraint(...)`, `deactivate_constraint(id)`
  - `check_allocation(lines[])` → constraint report
  - `create_proposal(lines[], rationale, created_by)` → proposal id and
    constraint report
  - `list_proposals(status?)`, `get_proposal(id)`
  - `add_roster_etf(...)`, `deactivate_roster_etf(ticker)`
- Resources: `longterm://overview` (same payload as `get_market_overview`)
  and `longterm://signals/{ticker}`.
- No tool accepts or rejects proposals.
- Structured logging to Seq like the other sidecars; one Prometheus counter
  per tool call.

### 4.8 Frontend

New route `/long-term`, page `frontend/src/pages/LongTerm/`, sidebar entry
"Long-Term" with a lucide `TrendingUp`-style icon. React Query for all data;
API module `frontend/src/api/longTerm.ts`.

Layout, top to bottom:

1. **Header strip:** reporting currency, last signal date, benchmark (SPY)
   1y return, "signals stale" warning if the latest date is older than the
   last trading day.
2. **On sale now:** cards for the top 8 by `on_sale_score`, each showing
   segment, score, drawdown from 52w high, distance from SMA200, and a
   `short history` badge when applicable.
3. **Movers:** two short lists, best and worst over 1 week and 1 month.
4. **Trend split:** above / below SMA50, grouped by segment, as a compact
   two-column list.
5. **Roster table:** all ETFs, filter by segment / country, sortable on
   every signal column, click opens the detail drawer.
6. **Detail drawer:** existing `StockChart` in daily mode with the
   `showDoubleSuperTrend` toggle, SMA50/200 price lines via the `priceLines`
   prop, and the full signal row.

Tabs on the same page: **Portfolio** (accounts, positions with inline edit,
allocation donut by segment, constraint bars showing current exposure vs. cap)
and **Proposals** (pending first; each with rationale, diff table, constraint
report, Accept / Reject buttons; history below).

The chart and donut follow the project's existing chart conventions. The
builder reads the `dataviz` skill before writing chart code.

### 4.9 Rollout slices

Each slice is a shippable PR and a GitHub issue; later slices depend on
earlier ones in this order.

1. **Roster + data path.** Roster model and seed, static universe kind,
   yfinance provider for Canadian bars, dividend table and nightly fetch for
   both markets, ticker column widening, FX table and nightly fetch, backfill.
   Done when every roster ticker has 5 years of daily bars and dividends and
   the nightly sync keeps them current.
2. **Signals + read-only page.** Signal table and task, REST read endpoints,
   the Long-Term page with overview, roster table, and detail drawer.
3. **MCP server, read tools.** Sidecar, auth, roster/signal/overview tools.
   Done when an external agent can call `get_market_overview` with the token.
4. **Portfolio.** Accounts, positions, constraints, allocation service,
   Portfolio tab, MCP write tools for positions and constraints.
5. **Proposals.** Proposal and target models, check and create tools,
   Proposals tab with accept/reject, drift display.

## 5. Left to the builder

- Exact Pydantic shapes, pagination, and error codes.
- Whether the signal task runs as one Celery task per ticker or one batch.
- The indicator implementation (pandas vs. plain lists); reusing the SMA and
  ATR helpers from `trend_pullback_scan.py` is encouraged but not required.
- Chart colours and card styling within the existing Tailwind system.
- Test strategy, following the project's backend pytest recipe and frontend
  `tsc` gate; the MCP tools should have unit tests against the service layer
  and one integration test that starts the server and calls a tool with and
  without the token.
- yfinance call batching and retry policy within the provider.
- Whether the dividend-adjustment factor is applied per ex-date or batched
  per run; the result must match a standard total-return index within
  rounding.

## 6. Open questions resolved during design

- **MCP vs. REST for agents:** MCP, decided by Frank.
- **Holdings source:** manual, multi-account, agent-assisted from
  screenshots, decided by Frank.
- **Proposal handling:** recorded in MarketHawk, human accept/reject, decided
  by Frank.
- **Data via a universe:** yes, a dedicated static universe, decided by Frank.
- **Daily resolution:** decided by Frank.
- **Canadian bars:** yfinance provider rather than depending on an IBKR TSX
  entitlement, decided by Frank.
- **Return basis:** total return (dividend-adjusted), decided by Frank.
- **MCP exposure:** localhost on the Docker host only, decided by Frank.

## 7. Designer's calls to check while reading

- Reporting currency defaults to **CAD**. Change the setting if USD is
  preferred; nothing else depends on the default.
- Accepting a proposal sets the target allocation and does not touch
  holdings.
- Proposals with constraint violations are stored but cannot be accepted.
- The on-sale score formula in §4.3 is a starting heuristic.
- `short_history` threshold is 3 years.
- MCP auth is a single static bearer token, not per-agent identities.
- Single-tenant `lt_*` tables; ownership deferred to #373.
- A proposal is a complete target; omitted held tickers become implied
  sells to 0%; `account_id` on a line is a display-only execution hint.
- Adjusted (total-return) closes are computed in memory each run, never
  stored.
- Polygon forex is the FX fallback behind yfinance.
