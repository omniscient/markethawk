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
