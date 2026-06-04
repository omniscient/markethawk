# Dark Factory Seed Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single `seed_preview.sql` with a modular `seed/` directory so dark factory previews have enough data for meaningful human review.

**Architecture:** Split the existing seed file into ordered SQL modules in `dark-factory/seed/`. Update three infrastructure touchpoints (docker-compose, Dockerfile, entrypoint) to load the directory. Add seed data awareness guidance to the dark-factory-implement command.

**Tech Stack:** PostgreSQL (SQL), Docker Compose, Bash, Archon commands (Markdown)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `dark-factory/seed/00_base_tickers.sql` | Create | ticker_references, stock_universes, stock_universe_tickers |
| `dark-factory/seed/01_scanner_configs.sql` | Create | scanner_configs, system_config |
| `dark-factory/seed/02_scanner_data.sql` | Create | scanner_runs, scanner_events |
| `dark-factory/seed/03_market_data.sql` | Create | stock_aggregates (minute bars for charts) |
| `dark-factory/seed/04_watchlist.sql` | Create | active_watchlist |
| `dark-factory/docker-compose.preview.yml` | Modify | Update seed service to run directory of SQL files |
| `dark-factory/Dockerfile` | Modify | Copy seed/ directory instead of single file |
| `dark-factory/entrypoint.sh` | Modify | Copy seed/ directory instead of single file |
| `dark-factory/seed_preview.sql` | Delete | Replaced by seed/ directory |
| `.archon/commands/dark-factory-implement.md` | Modify | Add seed data awareness section |

---

### Task 1: Create seed directory and split base tickers module

**Files:**
- Create: `dark-factory/seed/00_base_tickers.sql`

This module contains `ticker_references`, `stock_universes`, and `stock_universe_tickers` — extracted from the existing `seed_preview.sql` and expanded.

- [ ] **Step 1: Create `dark-factory/seed/00_base_tickers.sql`**

```sql
-- Module 00: Base tickers, universes, and universe memberships.
-- Source: curated production export. Idempotent.

BEGIN;

-- Ticker references (large-cap tech stocks)
INSERT INTO ticker_references (ticker, name, market_cap, sector, industry, primary_exchange, active)
VALUES
  ('AAPL', 'Apple Inc.', 3200000000000, 'Technology', 'Consumer Electronics', 'XNAS', true),
  ('TSLA', 'Tesla, Inc.', 780000000000, 'Consumer Cyclical', 'Auto Manufacturers', 'XNAS', true),
  ('NVDA', 'NVIDIA Corporation', 2800000000000, 'Technology', 'Semiconductors', 'XNAS', true),
  ('AMD', 'Advanced Micro Devices', 230000000000, 'Technology', 'Semiconductors', 'XNAS', true),
  ('MSFT', 'Microsoft Corporation', 3100000000000, 'Technology', 'Software - Infrastructure', 'XNAS', true),
  ('META', 'Meta Platforms, Inc.', 1400000000000, 'Communication Services', 'Internet Content & Information', 'XNAS', true),
  ('GOOGL', 'Alphabet Inc.', 2100000000000, 'Communication Services', 'Internet Content & Information', 'XNAS', true),
  ('AMZN', 'Amazon.com, Inc.', 1900000000000, 'Consumer Cyclical', 'Internet Retail', 'XNAS', true)
ON CONFLICT (ticker) DO NOTHING;

-- Sector ETF ticker references
INSERT INTO ticker_references (ticker, name, market_cap, sector, industry, primary_exchange, active)
VALUES
  ('XLK',  'Technology Select Sector SPDR', NULL, 'Technology', 'ETF', 'ARCX', true),
  ('XLF',  'Financial Select Sector SPDR', NULL, 'Financial Services', 'ETF', 'ARCX', true),
  ('XLV',  'Health Care Select Sector SPDR', NULL, 'Healthcare', 'ETF', 'ARCX', true),
  ('XLY',  'Consumer Discretionary Select Sector SPDR', NULL, 'Consumer Cyclical', 'ETF', 'ARCX', true),
  ('XLP',  'Consumer Staples Select Sector SPDR', NULL, 'Consumer Defensive', 'ETF', 'ARCX', true),
  ('XLE',  'Energy Select Sector SPDR', NULL, 'Energy', 'ETF', 'ARCX', true),
  ('XLI',  'Industrial Select Sector SPDR', NULL, 'Industrials', 'ETF', 'ARCX', true),
  ('XLB',  'Materials Select Sector SPDR', NULL, 'Basic Materials', 'ETF', 'ARCX', true),
  ('XLRE', 'Real Estate Select Sector SPDR', NULL, 'Real Estate', 'ETF', 'ARCX', true),
  ('XLU',  'Utilities Select Sector SPDR', NULL, 'Utilities', 'ETF', 'ARCX', true),
  ('XLC',  'Communication Services Select Sector SPDR', NULL, 'Communication Services', 'ETF', 'ARCX', true)
ON CONFLICT (ticker) DO NOTHING;

-- Universe: Large Cap Tech
INSERT INTO stock_universes (id, name, description, criteria, is_active)
VALUES (
  1,
  'Large Cap Tech',
  'Top technology stocks by market cap — seed data for preview testing',
  '{"sector": "Technology", "min_market_cap": 100000000000}',
  true
)
ON CONFLICT (id) DO NOTHING;

-- Universe tickers: Large Cap Tech
INSERT INTO stock_universe_tickers (universe_id, ticker, asset_class, data_source)
VALUES
  (1, 'AAPL',  'stocks', 'massive'),
  (1, 'TSLA',  'stocks', 'massive'),
  (1, 'NVDA',  'stocks', 'massive'),
  (1, 'AMD',   'stocks', 'massive'),
  (1, 'MSFT',  'stocks', 'massive'),
  (1, 'META',  'stocks', 'massive'),
  (1, 'GOOGL', 'stocks', 'massive'),
  (1, 'AMZN',  'stocks', 'massive')
ON CONFLICT DO NOTHING;

-- Universe: Sector ETFs
INSERT INTO stock_universes (id, name, description, criteria, is_active)
VALUES (
  2,
  'Sector ETFs',
  '11 SPDR sector ETFs for pre-market momentum context',
  '{"type": "sector_etfs"}',
  true
)
ON CONFLICT (id) DO NOTHING;

-- Universe tickers: Sector ETFs
INSERT INTO stock_universe_tickers (universe_id, ticker, asset_class, data_source)
VALUES
  (2, 'XLK',  'stocks', 'massive'),
  (2, 'XLF',  'stocks', 'massive'),
  (2, 'XLV',  'stocks', 'massive'),
  (2, 'XLY',  'stocks', 'massive'),
  (2, 'XLP',  'stocks', 'massive'),
  (2, 'XLE',  'stocks', 'massive'),
  (2, 'XLI',  'stocks', 'massive'),
  (2, 'XLB',  'stocks', 'massive'),
  (2, 'XLRE', 'stocks', 'massive'),
  (2, 'XLU',  'stocks', 'massive'),
  (2, 'XLC',  'stocks', 'massive')
ON CONFLICT DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Verify the SQL is valid**

Run: `docker-compose exec -T postgres psql -U postgres -d stockscanner -c "\i /dev/stdin" < dark-factory/seed/00_base_tickers.sql`

Expected: `COMMIT` with no errors. Verify with:
```bash
docker-compose exec -T postgres psql -U postgres -d stockscanner -c "SELECT count(*) FROM ticker_references;"
```
Expected: 19 (8 stocks + 11 ETFs)

- [ ] **Step 3: Commit**

```bash
git add dark-factory/seed/00_base_tickers.sql
git commit -m "feat(seed): add 00_base_tickers module with tickers and universes"
```

---

### Task 2: Create scanner configs module

**Files:**
- Create: `dark-factory/seed/01_scanner_configs.sql`

Scanner configurations and system config keys. Expanded from the original seed to include all scanner types.

- [ ] **Step 1: Create `dark-factory/seed/01_scanner_configs.sql`**

```sql
-- Module 01: Scanner configurations and system config.
-- Source: curated production export. Idempotent.

BEGIN;

-- Scanner config: Pre-Market Volume Spike
INSERT INTO scanner_configs (id, name, description, scanner_type, parameters, criteria, is_active)
VALUES (
  1,
  'Pre-Market Volume Spike',
  'Detects stocks with unusual pre-market volume — 4x average with minimum liquidity',
  'pre_market_volume',
  '{"lookback_days": 20, "min_volume": 50000}',
  '{"relative_volume_threshold": 4.0, "min_price": 5.0, "min_gap_pct": 1.0}',
  true
)
ON CONFLICT (id) DO NOTHING;

-- Scanner config: Liquidity Hunt (Evening)
INSERT INTO scanner_configs (id, name, description, scanner_type, parameters, criteria, is_active)
VALUES (
  2,
  'Liquidity Hunt (Evening)',
  'Identifies stocks with unusual post-market volume patterns suggesting institutional activity',
  'liquidity_hunt',
  '{"lookback_days": 20, "min_volume": 100000, "scan_window": "evening"}',
  '{"volume_spike_threshold": 3.0, "min_price": 10.0, "min_spread_pct": 0.5}',
  true
)
ON CONFLICT (id) DO NOTHING;

-- Scanner config: Oversold Bounce
INSERT INTO scanner_configs (id, name, description, scanner_type, parameters, criteria, is_active)
VALUES (
  3,
  'Oversold Bounce',
  'Identifies oversold conditions with early reversal signals',
  'oversold_bounce',
  '{"lookback_days": 14, "rsi_period": 14}',
  '{"rsi_threshold": 30.0, "min_price": 5.0, "min_volume": 50000}',
  true
)
ON CONFLICT (id) DO NOTHING;

-- System config defaults
INSERT INTO system_config (key, value)
VALUES
  ('scanner.auto_run', 'false'),
  ('scanner.default_universe', '1'),
  ('timesfm_enabled', 'false'),
  ('timesfm_anomaly_threshold', '2.0'),
  ('timesfm_min_history_bars', '30'),
  ('timesfm_fallback_multiplier', '4.0')
ON CONFLICT (key) DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Verify the SQL is valid**

Run: `docker-compose exec -T postgres psql -U postgres -d stockscanner -c "\i /dev/stdin" < dark-factory/seed/01_scanner_configs.sql`

Expected: `COMMIT` with no errors. Verify with:
```bash
docker-compose exec -T postgres psql -U postgres -d stockscanner -c "SELECT name, scanner_type FROM scanner_configs ORDER BY id;"
```
Expected: 3 rows (pre_market_volume, liquidity_hunt, oversold_bounce)

- [ ] **Step 3: Commit**

```bash
git add dark-factory/seed/01_scanner_configs.sql
git commit -m "feat(seed): add 01_scanner_configs module with all scanner types"
```

---

### Task 3: Create scanner data module

**Files:**
- Create: `dark-factory/seed/02_scanner_data.sql`

Scanner runs and events. Expanded to 3 runs with 5 events across different scanner types and severities.

- [ ] **Step 1: Create `dark-factory/seed/02_scanner_data.sql`**

```sql
-- Module 02: Scanner runs and events.
-- Source: curated production export. Idempotent.

BEGIN;

-- Scanner run 1: Pre-market volume (completed, found 2 events)
INSERT INTO scanner_runs (id, scanner_type, universe_id, status, stocks_scanned, events_detected, execution_time_ms, created_at)
VALUES (
  1, 'pre_market_volume', 1, 'completed', 8, 2, 1250,
  NOW() - INTERVAL '2 hours'
)
ON CONFLICT (id) DO NOTHING;

-- Scanner run 2: Liquidity hunt (completed, found 2 events)
INSERT INTO scanner_runs (id, scanner_type, universe_id, status, stocks_scanned, events_detected, execution_time_ms, created_at)
VALUES (
  2, 'liquidity_hunt', 1, 'completed', 8, 2, 980,
  NOW() - INTERVAL '14 hours'
)
ON CONFLICT (id) DO NOTHING;

-- Scanner run 3: Oversold bounce (completed, found 1 event)
INSERT INTO scanner_runs (id, scanner_type, universe_id, status, stocks_scanned, events_detected, execution_time_ms, created_at)
VALUES (
  3, 'oversold_bounce', 1, 'completed', 8, 1, 1100,
  NOW() - INTERVAL '26 hours'
)
ON CONFLICT (id) DO NOTHING;

-- Event 1: NVDA pre-market volume spike (high severity)
INSERT INTO scanner_events (id, ticker, event_date, scanner_type, summary, severity, previous_close, opening_price, indicators, criteria_met, metadata)
VALUES (
  1, 'NVDA', CURRENT_DATE, 'pre_market_volume',
  'NVDA showing 6.2x average pre-market volume with 2.3% gap up',
  'high',
  132.50, 135.55,
  '{"relative_volume": 6.2, "pre_market_volume": 1850000, "avg_volume_20d": 298000, "gap_pct": 2.3}',
  '{"volume_spike": true, "gap_up": true, "min_price": true}',
  '{"source": "seed_data"}'
)
ON CONFLICT (ticker, event_date, scanner_type) DO NOTHING;

-- Event 2: AMD pre-market volume spike (medium severity)
INSERT INTO scanner_events (id, ticker, event_date, scanner_type, summary, severity, previous_close, opening_price, indicators, criteria_met, metadata)
VALUES (
  2, 'AMD', CURRENT_DATE, 'pre_market_volume',
  'AMD showing 4.8x average pre-market volume with 1.5% gap up',
  'medium',
  165.20, 167.68,
  '{"relative_volume": 4.8, "pre_market_volume": 920000, "avg_volume_20d": 191000, "gap_pct": 1.5}',
  '{"volume_spike": true, "gap_up": true, "min_price": true}',
  '{"source": "seed_data"}'
)
ON CONFLICT (ticker, event_date, scanner_type) DO NOTHING;

-- Event 3: MSFT liquidity hunt (high severity)
INSERT INTO scanner_events (id, ticker, event_date, scanner_type, summary, severity, previous_close, opening_price, indicators, criteria_met, metadata)
VALUES (
  3, 'MSFT', CURRENT_DATE - INTERVAL '1 day', 'liquidity_hunt',
  'MSFT unusual post-market volume — 3.8x average with tight spread',
  'high',
  428.50, 430.20,
  '{"relative_volume": 3.8, "post_market_volume": 680000, "avg_volume_20d": 179000, "spread_pct": 0.3}',
  '{"volume_spike": true, "spread_tight": true, "min_price": true}',
  '{"source": "seed_data"}'
)
ON CONFLICT (ticker, event_date, scanner_type) DO NOTHING;

-- Event 4: TSLA liquidity hunt (medium severity)
INSERT INTO scanner_events (id, ticker, event_date, scanner_type, summary, severity, previous_close, opening_price, indicators, criteria_met, metadata)
VALUES (
  4, 'TSLA', CURRENT_DATE - INTERVAL '1 day', 'liquidity_hunt',
  'TSLA post-market volume 3.2x average with elevated spread',
  'medium',
  248.90, 251.40,
  '{"relative_volume": 3.2, "post_market_volume": 520000, "avg_volume_20d": 162500, "spread_pct": 0.7}',
  '{"volume_spike": true, "spread_tight": false, "min_price": true}',
  '{"source": "seed_data"}'
)
ON CONFLICT (ticker, event_date, scanner_type) DO NOTHING;

-- Event 5: AMZN oversold bounce (low severity)
INSERT INTO scanner_events (id, ticker, event_date, scanner_type, summary, severity, previous_close, opening_price, indicators, criteria_met, metadata)
VALUES (
  5, 'AMZN', CURRENT_DATE - INTERVAL '2 days', 'oversold_bounce',
  'AMZN RSI at 28.5 with early reversal candle pattern',
  'low',
  185.30, 183.90,
  '{"rsi_14": 28.5, "reversal_candle": true, "volume_confirmation": false}',
  '{"rsi_oversold": true, "reversal_signal": true, "min_price": true}',
  '{"source": "seed_data"}'
)
ON CONFLICT (ticker, event_date, scanner_type) DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Verify the SQL is valid**

Run: `docker-compose exec -T postgres psql -U postgres -d stockscanner -c "\i /dev/stdin" < dark-factory/seed/02_scanner_data.sql`

Expected: `COMMIT` with no errors. Verify with:
```bash
docker-compose exec -T postgres psql -U postgres -d stockscanner -c "SELECT ticker, scanner_type, severity FROM scanner_events ORDER BY id;"
```
Expected: 5 rows across 3 scanner types and 3 severity levels

- [ ] **Step 3: Commit**

```bash
git add dark-factory/seed/02_scanner_data.sql
git commit -m "feat(seed): add 02_scanner_data module with runs and events"
```

---

### Task 4: Create market data module

**Files:**
- Create: `dark-factory/seed/03_market_data.sql`

Minute-level stock aggregates for 3 tickers covering pre-market and regular session. Enough bars to render meaningful charts.

- [ ] **Step 1: Create `dark-factory/seed/03_market_data.sql`**

```sql
-- Module 03: Stock aggregates (minute bars) for chart rendering.
-- Covers pre-market (04:00-09:29) and regular session (09:30+) for NVDA, AMD, MSFT.
-- Source: curated production export. Idempotent.

BEGIN;

-- NVDA: pre-market bars (today)
INSERT INTO stock_aggregates (ticker, timestamp, multiplier, timespan, open, high, low, close, volume, vwap, is_pre_market, provider)
VALUES
  ('NVDA', CURRENT_DATE + TIME '04:00', 1, 'minute', 133.10, 133.45, 132.90, 133.30, 45000,  133.20, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '04:30', 1, 'minute', 133.30, 134.00, 133.20, 133.85, 62000,  133.60, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '05:00', 1, 'minute', 133.85, 134.50, 133.70, 134.40, 78000,  134.10, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '05:30', 1, 'minute', 134.40, 134.80, 134.20, 134.65, 55000,  134.50, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '06:00', 1, 'minute', 134.65, 135.20, 134.30, 135.10, 95000,  134.75, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '06:30', 1, 'minute', 135.10, 135.40, 134.80, 135.25, 72000,  135.10, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '07:00', 1, 'minute', 135.25, 135.80, 134.90, 135.55, 120000, 135.35, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '07:30', 1, 'minute', 135.55, 135.90, 135.30, 135.70, 88000,  135.60, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '08:00', 1, 'minute', 135.70, 136.10, 135.50, 135.95, 105000, 135.80, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '08:30', 1, 'minute', 135.95, 136.30, 135.60, 136.15, 140000, 135.95, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '09:00', 1, 'minute', 136.15, 136.50, 135.90, 136.35, 180000, 136.20, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '09:15', 1, 'minute', 136.35, 136.60, 136.10, 136.45, 210000, 136.35, true, 'polygon')
ON CONFLICT DO NOTHING;

-- NVDA: regular session bars (today)
INSERT INTO stock_aggregates (ticker, timestamp, multiplier, timespan, open, high, low, close, volume, vwap, is_pre_market, provider)
VALUES
  ('NVDA', CURRENT_DATE + TIME '09:30', 1, 'minute', 136.45, 137.20, 136.30, 136.90, 350000, 136.75, false, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '09:31', 1, 'minute', 136.90, 137.40, 136.60, 137.10, 280000, 137.00, false, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '09:32', 1, 'minute', 137.10, 137.50, 136.80, 137.30, 260000, 137.15, false, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '09:33', 1, 'minute', 137.30, 137.60, 137.00, 137.45, 220000, 137.30, false, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '09:34', 1, 'minute', 137.45, 137.80, 137.20, 137.65, 195000, 137.50, false, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '09:35', 1, 'minute', 137.65, 137.90, 137.40, 137.55, 175000, 137.65, false, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '09:40', 1, 'minute', 137.55, 137.70, 137.20, 137.40, 150000, 137.45, false, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '09:45', 1, 'minute', 137.40, 137.60, 137.10, 137.50, 130000, 137.35, false, 'polygon')
ON CONFLICT DO NOTHING;

-- AMD: pre-market bars (today)
INSERT INTO stock_aggregates (ticker, timestamp, multiplier, timespan, open, high, low, close, volume, vwap, is_pre_market, provider)
VALUES
  ('AMD', CURRENT_DATE + TIME '04:00', 1, 'minute', 165.50, 165.80, 165.20, 165.60, 28000,  165.50, true, 'polygon'),
  ('AMD', CURRENT_DATE + TIME '05:00', 1, 'minute', 165.60, 166.30, 165.40, 166.10, 42000,  165.85, true, 'polygon'),
  ('AMD', CURRENT_DATE + TIME '06:00', 1, 'minute', 166.10, 166.80, 165.90, 166.55, 58000,  166.35, true, 'polygon'),
  ('AMD', CURRENT_DATE + TIME '07:00', 1, 'minute', 166.55, 167.20, 166.30, 167.00, 75000,  166.75, true, 'polygon'),
  ('AMD', CURRENT_DATE + TIME '08:00', 1, 'minute', 167.00, 167.50, 166.80, 167.35, 92000,  167.15, true, 'polygon'),
  ('AMD', CURRENT_DATE + TIME '09:00', 1, 'minute', 167.35, 167.80, 167.10, 167.68, 115000, 167.45, true, 'polygon')
ON CONFLICT DO NOTHING;

-- AMD: regular session bars (today)
INSERT INTO stock_aggregates (ticker, timestamp, multiplier, timespan, open, high, low, close, volume, vwap, is_pre_market, provider)
VALUES
  ('AMD', CURRENT_DATE + TIME '09:30', 1, 'minute', 167.68, 168.30, 167.50, 168.10, 220000, 167.90, false, 'polygon'),
  ('AMD', CURRENT_DATE + TIME '09:31', 1, 'minute', 168.10, 168.50, 167.80, 168.30, 180000, 168.15, false, 'polygon'),
  ('AMD', CURRENT_DATE + TIME '09:32', 1, 'minute', 168.30, 168.60, 168.00, 168.20, 160000, 168.30, false, 'polygon'),
  ('AMD', CURRENT_DATE + TIME '09:33', 1, 'minute', 168.20, 168.40, 167.90, 168.35, 140000, 168.15, false, 'polygon'),
  ('AMD', CURRENT_DATE + TIME '09:34', 1, 'minute', 168.35, 168.70, 168.10, 168.50, 130000, 168.40, false, 'polygon'),
  ('AMD', CURRENT_DATE + TIME '09:35', 1, 'minute', 168.50, 168.80, 168.20, 168.60, 120000, 168.50, false, 'polygon')
ON CONFLICT DO NOTHING;

-- MSFT: pre-market bars (yesterday, for liquidity hunt event)
INSERT INTO stock_aggregates (ticker, timestamp, multiplier, timespan, open, high, low, close, volume, vwap, is_pre_market, provider)
VALUES
  ('MSFT', (CURRENT_DATE - INTERVAL '1 day') + TIME '04:00', 1, 'minute', 427.80, 428.10, 427.50, 427.90, 15000, 427.80, true, 'polygon'),
  ('MSFT', (CURRENT_DATE - INTERVAL '1 day') + TIME '06:00', 1, 'minute', 427.90, 428.40, 427.70, 428.20, 22000, 428.05, true, 'polygon'),
  ('MSFT', (CURRENT_DATE - INTERVAL '1 day') + TIME '08:00', 1, 'minute', 428.20, 428.80, 428.00, 428.50, 35000, 428.40, true, 'polygon'),
  ('MSFT', (CURRENT_DATE - INTERVAL '1 day') + TIME '09:00', 1, 'minute', 428.50, 429.00, 428.30, 428.80, 48000, 428.65, true, 'polygon')
ON CONFLICT DO NOTHING;

-- MSFT: regular session bars (yesterday)
INSERT INTO stock_aggregates (ticker, timestamp, multiplier, timespan, open, high, low, close, volume, vwap, is_pre_market, provider)
VALUES
  ('MSFT', (CURRENT_DATE - INTERVAL '1 day') + TIME '09:30', 1, 'minute', 428.80, 429.50, 428.60, 429.20, 180000, 429.05, false, 'polygon'),
  ('MSFT', (CURRENT_DATE - INTERVAL '1 day') + TIME '09:31', 1, 'minute', 429.20, 429.80, 429.00, 429.60, 150000, 429.40, false, 'polygon'),
  ('MSFT', (CURRENT_DATE - INTERVAL '1 day') + TIME '09:32', 1, 'minute', 429.60, 430.00, 429.30, 429.80, 140000, 429.65, false, 'polygon'),
  ('MSFT', (CURRENT_DATE - INTERVAL '1 day') + TIME '09:33', 1, 'minute', 429.80, 430.20, 429.50, 430.00, 125000, 429.85, false, 'polygon'),
  ('MSFT', (CURRENT_DATE - INTERVAL '1 day') + TIME '09:34', 1, 'minute', 430.00, 430.40, 429.70, 430.20, 110000, 430.05, false, 'polygon'),
  ('MSFT', (CURRENT_DATE - INTERVAL '1 day') + TIME '09:35', 1, 'minute', 430.20, 430.50, 429.90, 430.10, 100000, 430.20, false, 'polygon')
ON CONFLICT DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Verify the SQL is valid**

Run: `docker-compose exec -T postgres psql -U postgres -d stockscanner -c "\i /dev/stdin" < dark-factory/seed/03_market_data.sql`

Expected: `COMMIT` with no errors. Verify with:
```bash
docker-compose exec -T postgres psql -U postgres -d stockscanner -c "SELECT ticker, count(*) FROM stock_aggregates GROUP BY ticker ORDER BY ticker;"
```
Expected: NVDA 20, AMD 12, MSFT 10

- [ ] **Step 3: Commit**

```bash
git add dark-factory/seed/03_market_data.sql
git commit -m "feat(seed): add 03_market_data module with minute bars for charts"
```

---

### Task 5: Create watchlist module

**Files:**
- Create: `dark-factory/seed/04_watchlist.sql`

- [ ] **Step 1: Create `dark-factory/seed/04_watchlist.sql`**

```sql
-- Module 04: Active watchlist entries.
-- Source: curated production export. Idempotent.

BEGIN;

INSERT INTO active_watchlist (symbol, security_type, notes)
VALUES
  ('NVDA', 'STK', 'Seed data — high relative volume today'),
  ('AMD',  'STK', 'Seed data — moderate volume spike'),
  ('MSFT', 'STK', 'Seed data — post-market liquidity activity')
ON CONFLICT (symbol) DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Commit**

```bash
git add dark-factory/seed/04_watchlist.sql
git commit -m "feat(seed): add 04_watchlist module"
```

---

### Task 6: Update docker-compose.preview.yml seed service

**Files:**
- Modify: `dark-factory/docker-compose.preview.yml:98-109`

- [ ] **Step 1: Update the seed service to mount and run a directory**

Replace the existing `seed` service block (lines 98-109) with:

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

Key changes:
- Volume mount: `./seed:/seed:ro` instead of `./seed_preview.sql:/seed.sql:ro`
- Entrypoint: loops over `*.sql` files in sorted order instead of running a single file
- `$$f` is required (double-dollar) because Docker Compose interpolates `$` — this escapes it for the shell

- [ ] **Step 2: Verify YAML syntax**

Run: `docker compose -f dark-factory/docker-compose.preview.yml config --quiet`

Expected: No output (valid YAML). If it errors on variable substitution (the `${ISSUE_NUM_PADDED}` vars), that's expected — those are set at runtime.

- [ ] **Step 3: Commit**

```bash
git add dark-factory/docker-compose.preview.yml
git commit -m "feat(seed): update preview seed service to load modular SQL directory"
```

---

### Task 7: Update Dockerfile and entrypoint.sh

**Files:**
- Modify: `dark-factory/Dockerfile:70`
- Modify: `dark-factory/entrypoint.sh:132`

- [ ] **Step 1: Update Dockerfile — replace single file COPY with directory COPY**

In `dark-factory/Dockerfile`, replace line 70:

```dockerfile
# Before:
COPY dark-factory/seed_preview.sql /opt/dark-factory/seed_preview.sql

# After:
COPY dark-factory/seed/ /opt/dark-factory/seed/
```

- [ ] **Step 2: Update entrypoint.sh — replace single file copy with directory copy**

In `dark-factory/entrypoint.sh`, replace line 132:

```bash
# Before:
cp /opt/dark-factory/seed_preview.sql "$CLONE_DIR/dark-factory/seed_preview.sql"

# After:
cp -r /opt/dark-factory/seed/ "$CLONE_DIR/dark-factory/seed/"
```

- [ ] **Step 3: Commit**

```bash
git add dark-factory/Dockerfile dark-factory/entrypoint.sh
git commit -m "feat(seed): update Dockerfile and entrypoint for modular seed directory"
```

---

### Task 8: Delete old seed_preview.sql

**Files:**
- Delete: `dark-factory/seed_preview.sql`

- [ ] **Step 1: Remove the old monolithic seed file**

```bash
git rm dark-factory/seed_preview.sql
```

- [ ] **Step 2: Commit**

```bash
git commit -m "chore(seed): remove old monolithic seed_preview.sql"
```

---

### Task 9: Add seed data awareness to dark-factory-implement command

**Files:**
- Modify: `.archon/commands/dark-factory-implement.md`

- [ ] **Step 1: Add seed data awareness section after Phase 2 (PLAN)**

In `.archon/commands/dark-factory-implement.md`, add the following section after the `PHASE_2_CHECKPOINT` block (after line 51) and before `## Phase 3: IMPLEMENT (TDD)`:

```markdown
### Seed Data Awareness

Before implementing, check if the feature requires data that isn't in the baseline seed modules (`dark-factory/seed/`). The baseline covers: tickers, universes, scanner configs, scanner runs/events, stock aggregates (minute bars), watchlist, and system config.

If the feature touches pages or endpoints that need data not in the baseline:
1. Create `dark-factory/seed/99_feature.sql` with idempotent INSERT statements (`ON CONFLICT DO NOTHING`) for the missing data
2. If that data would benefit future features (not just this one), also add it to a new numbered baseline module (e.g. `05_trades.sql`, `06_journal.sql`) so it persists for future previews
3. Include the seed file(s) in your commits

Tables NOT in baseline that commonly need seed data: `trades`, `trade_executions`, `journal_entries`, `tags`, `trading_strategies`, `news_articles`, `alert_rules`, `futures_aggregates`, `stock_metrics`.
```

- [ ] **Step 2: Verify the markdown renders correctly**

Read the file back and confirm the new section sits between Phase 2 and Phase 3 without breaking the document structure.

- [ ] **Step 3: Commit**

```bash
git add .archon/commands/dark-factory-implement.md
git commit -m "feat(seed): add seed data awareness to dark-factory-implement command"
```

---

### Task 10: Verify end-to-end with a local preview (optional)

This task is optional — it validates the full pipeline but requires Docker and a running stack.

**Files:** None (verification only)

- [ ] **Step 1: Rebuild the dark factory image**

```bash
docker compose --profile factory build dark-factory
```

Expected: Build succeeds, `COPY dark-factory/seed/ /opt/dark-factory/seed/` line visible in build output.

- [ ] **Step 2: Spin up a test preview manually**

```bash
export ISSUE_NUM_PADDED="99"
docker compose -p mh-preview-99 -f dark-factory/docker-compose.preview.yml up -d --build
```

Wait for backend health, then check seed data loaded:

```bash
docker compose -p mh-preview-99 -f dark-factory/docker-compose.preview.yml logs seed
```

Expected: Output shows "Running /seed/00_base_tickers.sql...", "Running /seed/01_scanner_configs.sql...", etc., ending with "All seed modules loaded".

- [ ] **Step 3: Verify data in the preview database**

```bash
docker compose -p mh-preview-99 -f dark-factory/docker-compose.preview.yml exec -T postgres \
  psql -U postgres -d stockscanner -c "
    SELECT 'ticker_references' AS tbl, count(*) FROM ticker_references
    UNION ALL SELECT 'scanner_configs', count(*) FROM scanner_configs
    UNION ALL SELECT 'scanner_events', count(*) FROM scanner_events
    UNION ALL SELECT 'stock_aggregates', count(*) FROM stock_aggregates
    UNION ALL SELECT 'active_watchlist', count(*) FROM active_watchlist
    UNION ALL SELECT 'system_config', count(*) FROM system_config;"
```

Expected:
| tbl | count |
|-----|-------|
| ticker_references | 19 |
| scanner_configs | 3 |
| scanner_events | 5 |
| stock_aggregates | 42 |
| active_watchlist | 3 |
| system_config | 6 |

- [ ] **Step 4: Tear down test preview**

```bash
docker compose -p mh-preview-99 -f dark-factory/docker-compose.preview.yml down -v
```

- [ ] **Step 5: Final commit (if any fixes were needed)**

```bash
git add -A
git commit -m "fix(seed): adjustments from end-to-end preview validation"
```
