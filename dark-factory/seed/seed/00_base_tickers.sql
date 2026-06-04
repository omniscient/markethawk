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
