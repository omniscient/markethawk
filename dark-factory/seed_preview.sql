-- Seed data for MarketHawk preview environments.
-- Runs after alembic migrations create the schema.
-- Idempotent: uses ON CONFLICT DO NOTHING throughout.

BEGIN;

-- Ticker references (6 large-cap stocks)
INSERT INTO ticker_references (ticker, name, market_cap, sector, industry, primary_exchange, active)
VALUES
  ('AAPL', 'Apple Inc.', 3200000000000, 'Technology', 'Consumer Electronics', 'XNAS', true),
  ('TSLA', 'Tesla, Inc.', 780000000000, 'Consumer Cyclical', 'Auto Manufacturers', 'XNAS', true),
  ('NVDA', 'NVIDIA Corporation', 2800000000000, 'Technology', 'Semiconductors', 'XNAS', true),
  ('AMD', 'Advanced Micro Devices', 230000000000, 'Technology', 'Semiconductors', 'XNAS', true),
  ('MSFT', 'Microsoft Corporation', 3100000000000, 'Technology', 'Software - Infrastructure', 'XNAS', true),
  ('META', 'Meta Platforms, Inc.', 1400000000000, 'Communication Services', 'Internet Content & Information', 'XNAS', true)
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

-- Universe tickers
INSERT INTO stock_universe_tickers (universe_id, ticker, asset_class, data_source)
VALUES
  (1, 'AAPL', 'stocks', 'massive'),
  (1, 'TSLA', 'stocks', 'massive'),
  (1, 'NVDA', 'stocks', 'massive'),
  (1, 'AMD', 'stocks', 'massive'),
  (1, 'MSFT', 'stocks', 'massive'),
  (1, 'META', 'stocks', 'massive')
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

-- Sector ETF universe tickers
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

-- Scanner config: Pre-Market Volume scanner
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

-- Scanner run (recent completed run)
INSERT INTO scanner_runs (id, scanner_type, universe_id, status, stocks_scanned, events_detected, execution_time_ms, created_at)
VALUES (
  1,
  'pre_market_volume',
  1,
  'completed',
  6,
  2,
  1250,
  NOW() - INTERVAL '2 hours'
)
ON CONFLICT (id) DO NOTHING;

-- Scanner events (two detections from the run)
INSERT INTO scanner_events (id, ticker, event_date, scanner_type, summary, severity, previous_close, opening_price, indicators, criteria_met, metadata)
VALUES
  (
    1, 'NVDA', CURRENT_DATE, 'pre_market_volume',
    'NVDA showing 6.2x average pre-market volume with 2.3% gap up',
    'high',
    132.50, 135.55,
    '{"relative_volume": 6.2, "pre_market_volume": 1850000, "avg_volume_20d": 298000, "gap_pct": 2.3}',
    '{"volume_spike": true, "gap_up": true, "min_price": true}',
    '{"source": "seed_data"}'
  ),
  (
    2, 'AMD', CURRENT_DATE, 'pre_market_volume',
    'AMD showing 4.8x average pre-market volume with 1.5% gap up',
    'medium',
    165.20, 167.68,
    '{"relative_volume": 4.8, "pre_market_volume": 920000, "avg_volume_20d": 191000, "gap_pct": 1.5}',
    '{"volume_spike": true, "gap_up": true, "min_price": true}',
    '{"source": "seed_data"}'
  )
ON CONFLICT (ticker, event_date, scanner_type) DO NOTHING;

-- Stock aggregates (a few minute bars for NVDA to have chart data)
INSERT INTO stock_aggregates (ticker, timestamp, multiplier, timespan, open, high, low, close, volume, vwap, is_pre_market, provider)
VALUES
  ('NVDA', CURRENT_DATE + TIME '04:00', 1, 'minute', 133.10, 133.45, 132.90, 133.30, 45000, 133.20, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '04:30', 1, 'minute', 133.30, 134.00, 133.20, 133.85, 62000, 133.60, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '05:00', 1, 'minute', 133.85, 134.50, 133.70, 134.40, 78000, 134.10, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '06:00', 1, 'minute', 134.40, 135.20, 134.30, 135.10, 95000, 134.75, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '07:00', 1, 'minute', 135.10, 135.80, 134.90, 135.55, 120000, 135.35, true, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '09:30', 1, 'minute', 135.55, 136.20, 135.30, 135.90, 250000, 135.75, false, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '09:31', 1, 'minute', 135.90, 136.40, 135.60, 136.10, 180000, 136.00, false, 'polygon'),
  ('NVDA', CURRENT_DATE + TIME '09:32', 1, 'minute', 136.10, 136.50, 135.80, 136.30, 160000, 136.15, false, 'polygon')
ON CONFLICT DO NOTHING;

-- System config defaults
INSERT INTO system_config (key, value)
VALUES
  ('scanner.auto_run', 'false'),
  ('scanner.default_universe', '1')
ON CONFLICT (key) DO NOTHING;

-- Active watchlist
INSERT INTO active_watchlist (symbol, security_type, notes)
VALUES
  ('NVDA', 'STK', 'Seed data — high relative volume today'),
  ('AMD', 'STK', 'Seed data — moderate volume spike')
ON CONFLICT (symbol) DO NOTHING;

COMMIT;
