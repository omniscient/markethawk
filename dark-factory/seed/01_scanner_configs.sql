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
