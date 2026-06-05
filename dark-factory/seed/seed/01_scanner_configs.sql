-- Module 01: Scanner configurations and system config.
-- Source: curated production export. Idempotent.

BEGIN;

-- Scanner config: Pre-Market Volume Spike
INSERT INTO scanner_configs (id, uuid, name, description, scanner_type, parameters, criteria, is_active, universe_id)
VALUES (
  1,
  gen_random_uuid(),
  'Pre-Market Volume Spike',
  'Detects stocks with unusual pre-market volume — 4x average with minimum liquidity',
  'pre_market_volume_spike',
  '{"lookback_days": 20, "min_volume": 50000}',
  '[{"field": "relative_volume", "op": ">=", "value": 4.0}, {"field": "price", "op": ">=", "value": 5.0}, {"field": "gap_pct", "op": ">=", "value": 1.0}]',
  true,
  1
)
ON CONFLICT (id) DO NOTHING;

-- Scanner config: Liquidity Hunt (Evening)
INSERT INTO scanner_configs (id, uuid, name, description, scanner_type, parameters, criteria, is_active, universe_id)
VALUES (
  2,
  gen_random_uuid(),
  'Liquidity Hunt (Evening)',
  'Identifies stocks with unusual post-market volume patterns suggesting institutional activity',
  'liquidity_hunt',
  '{"lookback_days": 20, "min_volume": 100000, "scan_window": "evening"}',
  '[{"field": "volume_spike", "op": ">=", "value": 3.0}, {"field": "price", "op": ">=", "value": 10.0}, {"field": "spread_pct", "op": ">=", "value": 0.5}]',
  true,
  1
)
ON CONFLICT (id) DO NOTHING;

-- Scanner config: Oversold Bounce
INSERT INTO scanner_configs (id, uuid, name, description, scanner_type, parameters, criteria, is_active, universe_id)
VALUES (
  3,
  gen_random_uuid(),
  'Oversold Bounce',
  'Identifies oversold conditions with early reversal signals',
  'oversold_bounce',
  '{"lookback_days": 14, "rsi_period": 14}',
  '[{"field": "rsi", "op": "<=", "value": 30.0}, {"field": "price", "op": ">=", "value": 5.0}, {"field": "volume", "op": ">=", "value": 50000}]',
  true,
  1
)
ON CONFLICT (id) DO NOTHING;

-- Scanner config: Pocket Pivot (Evening)
-- Migration 1bf5e10f1111 seeds this row via auto-id; migration c7e2a9f4b1d3 activates it
-- and normalises criteria to []. This INSERT is a no-op when those migrations have run;
-- it provides the row for any edge case where migrations did not seed it.
INSERT INTO scanner_configs (id, uuid, name, description, scanner_type, parameters, criteria, is_active, universe_id)
VALUES (
  4,
  gen_random_uuid(),
  'Pocket Pivot',
  'Identifies pocket pivot breakout setups with above-average volume on up days',
  'pocket_pivot',
  '{"lookback_days": 10, "volume_floor": 100000}',
  '[{"field": "volume_ratio", "op": ">=", "value": 1.5}, {"field": "price", "op": ">=", "value": 5.0}]',
  true,
  1
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
