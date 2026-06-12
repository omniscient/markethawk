# MarketHawk README, Docs Site, and Demo Mode Design

Date: 2026-06-12

## Goal

Make MarketHawk understandable in five minutes without live credentials. The first impression should answer what the product is, what it is not, how data moves through the system, how it compares with adjacent tools, and how to run a reproducible local demo.

## Selected Approach

Use a docs-first launch surface plus an isolated demo stack.

This approach rewrites the README around clear positioning, adds a static docs site under `docs/site/`, and introduces `make demo` as a deterministic sandbox. The demo must use separate Docker Compose project names and demo-only volumes so it never wipes or mutates normal development or live data.

## Positioning

MarketHawk is a human-in-the-loop market scanning cockpit for turning market data, news, scanner hits, alerting, review, execution notes, and outcomes into a repeatable trader workflow.

MarketHawk is not:

- A broker or order-routing system by default.
- A promise of profitable trading.
- A pure vectorized research engine.
- A full institutional backtesting framework.
- A replacement for risk controls, broker compliance, or human judgment.

## Documentation Deliverables

### README

Rewrite `README.md` into a world-class public entry point with these sections:

- One-sentence positioning and short product summary.
- "What MarketHawk is / is not".
- 5-minute demo with `make demo`.
- Architecture diagram.
- Data flow: data -> scanner -> alert -> review -> execution -> journal -> outcome.
- Screenshots/GIFs section using committed placeholders if real captures are not generated in this pass.
- Local install with sample data.
- Roadmap.
- Safety and risk disclaimers.
- Comparison table versus Lean, NautilusTrader, vectorbt, backtrader, and pysystemtrade.
- Links to deeper docs.

### Static Docs Site

Add a static docs site in `docs/site/` that can be opened directly from the filesystem or served by any static host. It should not require a build step.

Minimum files:

- `docs/site/index.html`
- `docs/site/styles.css`

The site should cover the same story as the README with a more visual layout:

- Hero positioning.
- Five-minute demo.
- Architecture and data-flow diagrams.
- Demo walkthrough.
- Competitor comparison.
- Roadmap and safety notes.

The docs site should use plain HTML/CSS, accessible semantic markup, responsive layout, and no external network dependencies.

## Demo Mode Deliverables

### Command

Add a top-level `Makefile` target:

```bash
make demo
```

The target must start a reproducible credential-free demo stack and print the frontend and API URLs.

### Isolation

The demo must use demo-specific resources:

- A separate Docker Compose project name such as `markethawk_demo`.
- Demo-only Postgres and Redis volumes.
- No dependency on IBKR credentials, Polygon credentials, X credentials, or live broker connections.
- No mutation of the existing `markethawk_postgres_data`, `markethawk_redis_data`, or other normal dev/live volumes.

Every `make demo` run resets demo-owned resources so the walkthrough remains deterministic.

### Compose Shape

Add `docker-compose.demo.yml`, which runs only what the demo needs:

- PostgreSQL
- Redis
- Backend API
- Frontend

The demo compose file should set safe local environment values directly or through a generated demo env file. It should disable or omit services that require live credentials or unnecessary operational infrastructure.

### Seed Data

Add deterministic seed assets under `demo/seed/` or an equivalent clearly named directory. The seed must populate enough data for a realistic walkthrough:

- Ticker references and universes.
- OHLCV bars for chart rendering.
- News articles or catalyst-like records.
- Scanner configurations, runs, and events.
- Active watchlist rows.
- Signal review rows.
- Fake outcome snapshots and summaries.
- Journal/trade records if the existing schema supports them cleanly.
- A demo user if needed to make the UI immediately usable after startup.

Seed scripts must be idempotent inside a freshly reset demo database.

### Demo Walkthrough

The README and docs site should describe the expected demo path:

1. Start `make demo`.
2. Open the frontend.
3. View scanner results.
4. Inspect watchlist entries.
5. Review signal cards.
6. Open outcome/scorecard views.
7. Inspect journal or trade notes.

If authentication remains enabled, the demo command should either seed a clearly documented demo user or print the exact first-run account setup step.

## Testing and Verification

Use focused checks:

- Validate compose syntax for the demo compose file.
- Verify the demo seed files can load into a migrated demo database.
- Run targeted backend tests for affected scripts or seed assumptions when feasible.
- Run frontend build or relevant docs/static checks if frontend code changes.
- Manually smoke-test `make demo` enough to confirm services start and seeded API data is visible.

## Out of Scope

- Building a new production docs framework.
- Adding broker order submission to demo mode.
- Capturing polished real GIFs if browser automation is blocked; placeholders are acceptable with clear filenames and copy.
- Changing the normal production compose flow except where needed to support the demo override.
- Reworking authentication architecture.

## Risks and Mitigations

- **Risk: demo accidentally resets real data.** Use a separate compose project and demo-only named volumes.
- **Risk: demo requires credentials.** Omit IBKR/live-scanner/tweet-monitor/forecasting/factory services and set safe backend defaults.
- **Risk: README over-promises trading results.** Keep safety disclaimers explicit and avoid performance claims.
- **Risk: seed data drifts from schema.** Keep seeds small, deterministic, and covered by at least compose/seed smoke verification.
- **Risk: static docs duplicate README content.** Treat README as the fast entry point and docs site as the visual walkthrough.
