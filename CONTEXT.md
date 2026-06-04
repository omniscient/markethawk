# MarketHawk

Stock scanning platform that detects pre-market and after-hours trading anomalies — volume spikes, price gaps, and liquidity patterns — to surface actionable signals before the regular session opens.

## Language

**Signal**:
A detected trading anomaly for a specific ticker on a specific date that met a scanner's criteria. One signal per scanner type per ticker per day. Stored as `ScannerEvent` in the database.
_Avoid_: Event (overloaded — alert delivery also produces events)

**Scanner**:
A named detection algorithm with specific criteria (detection rules like volume ratio > 4x, gap > 1%) and thresholds that identifies trading anomalies. Not to be confused with **Universe** criteria, which are membership filters. Each Scanner has a type slug (e.g., `liquidity_hunt_pre`, `pre_market_volume_spike`). Stored as `ScannerConfig` in the database.
_Avoid_: Strategy (that's auto-trading), filter

**Scan**:
A single execution of a **Scanner** against a **Universe** over a date range. Produces zero or more **Signals**. Stored as `ScannerRun` in the database.
_Avoid_: Run (ambiguous — Celery tasks also "run")

**Universe**:
A curated collection of tickers grouped by investment thesis (e.g., sector + market cap range). Defines the population a **Scan** evaluates. Most Universes have criteria (membership filters like sector, market cap range) that auto-refresh membership; some are hand-built for special purposes (e.g., a set of futures symbols or market ETFs used as validators). A ticker can belong to multiple Universes.
_Avoid_: Watchlist (that's the real-time monitoring concept), portfolio

**Review**:
A human verdict on a **Signal** — confirmed (real opportunity), rejected (noise), or enhanced (valid signal but the **Scanner** could have caught it better or earlier, with a suggestion for threshold changes). One Review per Signal. Reviews feed back into Scanner tuning.
_Avoid_: Rating, grade

**Outcome**:
The measured price action following a **Signal** — captured at fixed time intervals (5m, 15m, 30m, 1h, EOD, +1d, +5d) and summarized into metrics like max favorable excursion (MFE), max adverse excursion (MAE), and R-multiple. Outcomes are objective; **Reviews** are subjective. Together they assess **Scanner** quality. Currently computed separately from the **Scan** that produced the Signal.
_Avoid_: Result, backtest

**Watchlist**:
A small set of tickers being actively monitored in real-time via Interactive Brokers live data feeds during market hours. Tickers can be added from **Signals** that fired or manually. Drives live quotes, 5-second bars, and real-time alerts. Unlike a **Universe**, which is a batch scanning population, a Watchlist is for live intraday monitoring.
_Avoid_: Universe (batch concept), portfolio

**Aggregate**:
A single OHLCV (open, high, low, close, volume) bar for a ticker at a specific timespan granularity (1-minute, 5-minute, daily, etc.). The raw market data that **Scanners** consume to detect **Signals**. Sourced from providers like Polygon.io or Interactive Brokers and cached in the database; `data_source` tracks which provider supplied each bar.
_Avoid_: Candle (informal), bar (informal), quote (that's real-time)

**Session**:
One of three time windows in a US trading day: Pre-Market (4:00–9:30 AM ET), Regular (9:30 AM–4:00 PM ET), and Post-Market (4:00–8:00 PM ET). **Scanner** logic evaluates each session independently — some Scanners specifically target off-hours sessions where anomalies are more actionable.
_Avoid_: Extended hours (ambiguous — could mean pre or post), market hours (only covers Regular)

**Alert**:
A notification triggered when a **Signal** matches an **Alert Rule's** filters. Handles delivery (push, email, Google Chat, webhook) and throttling (cooldown per ticker). A Signal is the detection; an Alert is the notification about it.
_Avoid_: Notification (too generic), signal (that's the detection itself)

**Alert Rule**:
A user-configured filter that determines which **Signals** trigger **Alerts** and how they're delivered. Filters by scanner type and severity. Can optionally link to a **Trading Strategy** for automated order execution.
_Avoid_: Trigger, subscription

**Trading Strategy**:
A set of automated entry and exit rules that execute orders via Interactive Brokers when an **Alert** fires. Defines position sizing, stop-loss, take-profit, and time-based exit conditions. Linked from an **Alert Rule**. Not yet tested in production.
_Avoid_: Bot, automation, playbook

**Trade**:
A logged position (long or short) in the Journal. Currently manually recorded. Tracks entry/exit prices, P&L, and user-defined tags. Has one or more **Executions** (individual fills). Not yet linked back to the **Signal** that prompted it.
_Avoid_: Order (that's the broker-level concept), position (ambiguous)

**Execution**:
An individual fill on a **Trade** — a single buy or sell at a specific price and quantity.
_Avoid_: Fill (informal), order

**Enrichment**:
Contextual data attached to a **Signal** beyond the raw **Aggregate** metrics — market cap, float rotation, news catalysts, futures direction (ES/NQ risk-on/risk-off), and sector ETF movements. Computed during a **Scan** and stored on the Signal's metadata. Helps assess whether a volume spike has a fundamental catalyst or is noise.
_Avoid_: Metadata (too generic), context (overloaded)

**Scorecard**:
An aggregate performance report for a **Scanner** — computed from **Outcomes** across all its **Signals**. Shows win rate, profit factor, expectancy, R-multiple, and performance broken down by time horizon. Used to evaluate whether a Scanner is producing actionable Signals.
_Avoid_: Analytics (too broad), dashboard (that's the home page)

**Signal Cluster**:
A group of **Signals** with similar characteristics, identified by unsupervised analysis. Each cluster has a centroid (feature vector), return profile, and label. Used in the Edge Explorer to discover patterns across Signals. Experimental — not yet production-tested.
_Avoid_: Pattern (too vague), archetype

**Edge**:
The statistical advantage a **Scanner** provides over random chance — measured by win rate, expectancy, and profit factor from **Outcomes**. The Edge Explorer analyzes whether an edge persists over time, decays, or concentrates in specific **Signal Clusters**.
_Avoid_: Alpha (hedge fund jargon), advantage (too generic)

**Provider**:
An external market data source. Polygon.io supplies historical **Aggregates** for batch **Scans** (the "massive" provider is Polygon in bulk ingestion mode). Interactive Brokers (IBKR) supplies real-time data for the **Watchlist** and acts as the execution broker for **Trading Strategies**. Each **Aggregate** records which Provider sourced it.
_Avoid_: Data source (too generic), feed (that's real-time only)

## Example dialogue

> **Dev**: "The liquidity hunt scanner fired 90 signals when we ran a scan against the small cap universe for April."
>
> **Domain expert**: "How many held up? Did you review them?"
>
> **Dev**: "We confirmed about 70%, rejected the rest — mostly too-late or noise. The enrichment showed a few had news catalysts. We still need to compute outcomes so we can check the scorecard."
>
> **Domain expert**: "Good. If the edge holds, let's set up an alert rule to push notifications on high-severity signals and add the hits to the watchlist for live monitoring."

## Architecture Decisions

Past decisions that shape the codebase live in [`docs/adr/`](docs/adr/). The [`docs/adr/README.md`](docs/adr/README.md) is the decision-log index — scan it to find what has been decided before diving into individual records.
