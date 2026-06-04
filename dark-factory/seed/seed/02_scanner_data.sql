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
