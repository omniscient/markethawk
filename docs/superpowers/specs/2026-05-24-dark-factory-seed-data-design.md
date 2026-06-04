# Dark Factory Seed Data — Modular Catalog for Preview Environments

## Problem

Dark factory preview environments launch with minimal seed data: 6 tickers, 2 universes, 1 scanner run, 2 events, and 8 minute bars. The remaining 30+ tables are empty. When reviewing a PR's preview site, most pages render empty states, making it impossible to visually verify that new features work correctly.

## Goal

Ensure every dark factory preview has enough realistic data to meaningfully review frontend features in a browser, without requiring live API connections or manual data loading.

## Approach: Baseline + AI Top-Up

Two layers of seed data:

1. **Baseline catalog** — a set of SQL modules checked into the repo that every preview loads. Covers the core tables that most features depend on. Sourced from a curated production export.
2. **AI top-up** — when the dark factory agent builds a feature that needs data outside the baseline, it generates a feature-specific seed file. If that data is generally useful, the agent promotes it into a new baseline module as part of its PR.

## Seed Module Catalog

Replace the single `dark-factory/seed_preview.sql` with a `dark-factory/seed/` directory containing ordered modules:

```
dark-factory/seed/
├── 00_base_tickers.sql       # ticker_references, stock_universes, stock_universe_tickers
├── 01_scanner_configs.sql    # scanner_configs, system_config
├── 02_scanner_data.sql       # scanner_runs, scanner_events
├── 03_market_data.sql        # stock_aggregates (1-2 days of minute bars for 2-3 tickers)
├── 04_watchlist.sql          # active_watchlist
└── 99_feature.sql            # (optional) AI-generated, feature-specific data
```

Modules execute in filename-sorted order. Each module is idempotent (`ON CONFLICT DO NOTHING`).

### Module Contents

| Module | Tables | Data Scope |
|--------|--------|------------|
| `00_base_tickers.sql` | `ticker_references`, `stock_universes`, `stock_universe_tickers` | One universe ("Large Cap Tech", 6-8 tickers) + Sector ETFs universe (11 tickers) |
| `01_scanner_configs.sql` | `scanner_configs`, `system_config` | All active scanner configs (pre-market volume, liquidity hunt, oversold bounce). System config keys. |
| `02_scanner_data.sql` | `scanner_runs`, `scanner_events` | 2-3 completed runs with 4-6 events across different severities and scanner types |
| `03_market_data.sql` | `stock_aggregates` | 1-2 days of minute bars for 2-3 tickers (pre-market + regular session). Enough for charts to render. |
| `04_watchlist.sql` | `active_watchlist` | 2-3 symbols |

### Tables Not in Baseline

These tables are left empty in the baseline. The AI agent creates seed data for them when a feature requires it:

`trades`, `trade_executions`, `journal_entries`, `tags`, `trading_strategies`, `news_articles`, `news_preferences`, `alert_rules`, `alert_delivery_logs`, `push_subscriptions`, `futures_aggregates`, `futures_contracts`, `futures_rollovers`, `signal_analysis_runs`, `signal_clusters`, `signal_reviews`, `scanner_outcome_snapshots`, `scanner_outcome_summaries`, `stock_metrics`, `stock_splits`, `market_holidays`, `universe_quality_reports`, `auto_trade_orders`, `monitored_stocks`.

## Data Source

Baseline modules are populated from a curated production database export. The export is done once, reviewed, and committed. It is refreshed manually when models change significantly or when the data becomes stale.

No production credentials are needed at dark factory runtime — the seed data is static SQL checked into the repo.

## Infrastructure Changes

Three files change to support the modular catalog:

### 1. `dark-factory/docker-compose.preview.yml` — seed service

Replace the single-file mount with a directory mount and a loop runner:

```yaml
seed:
  image: postgres:15-alpine
  volumes:
    - ./seed:/seed:ro
  entrypoint: >
    sh -c "for f in /seed/*.sql; do
      echo \"Running $$f...\";
      PGPASSWORD=preview_password psql -h postgres -U postgres -d stockscanner -f \"$$f\";
    done && echo 'All seed modules loaded'"
  depends_on:
    backend:
      condition: service_healthy
  networks:
    - preview-network
  restart: "no"
```

### 2. `dark-factory/Dockerfile`

Replace the single file copy with a directory copy:

```dockerfile
# Before:
COPY dark-factory/seed_preview.sql /opt/dark-factory/seed_preview.sql

# After:
COPY dark-factory/seed/ /opt/dark-factory/seed/
```

### 3. `dark-factory/entrypoint.sh`

Replace the single file copy with a directory copy:

```bash
# Before:
cp /opt/dark-factory/seed_preview.sql "$CLONE_DIR/dark-factory/seed_preview.sql"

# After:
cp -r /opt/dark-factory/seed/ "$CLONE_DIR/dark-factory/seed/"
```

## AI Top-Up Protocol

The dark factory agent follows this protocol during implementation:

1. **Check**: Does the feature touch pages or endpoints that need data not covered by the baseline modules in `dark-factory/seed/`?
2. **Generate**: If yes, write a `dark-factory/seed/99_feature.sql` with the necessary INSERT statements. Use `ON CONFLICT DO NOTHING` for idempotency.
3. **Promote**: If the generated data would be useful for future features (not just this one), add it to a new numbered baseline module (e.g. `05_trades.sql`, `06_journal.sql`) and commit it as part of the PR. This grows the baseline organically as new features are built.

This guidance is added to the `dark-factory-implement` command's system prompt so the agent considers seed data needs as part of its implementation work.

### Prompt Addition for `dark-factory-implement`

Add to the implement command's instructions:

> **Seed data awareness:** Before implementing, check if the feature requires data that isn't in the baseline seed modules (`dark-factory/seed/`). If it does, create `dark-factory/seed/99_feature.sql` with idempotent INSERT statements for the missing data. If that data would benefit other features, also add it to a new numbered baseline module (e.g. `05_trades.sql`) so it persists for future previews. All seed SQL must use `ON CONFLICT DO NOTHING`.

## What Does Not Change

- The preview-up workflow step in `archon-dark-factory.yaml` — unchanged
- The validate step — unchanged
- The PR creation step — unchanged
- The close/teardown flow — unchanged
- Alembic migrations — still run before seed data, still the source of truth for schema

## Migration Path

1. Create `dark-factory/seed/` directory with modules split from the current `seed_preview.sql`
2. Expand the data in each module using a production export
3. Update the three touchpoints (docker-compose, Dockerfile, entrypoint)
4. Delete the old `seed_preview.sql`
5. Update the `dark-factory-implement` command prompt with seed data guidance
6. Rebuild the dark factory image
