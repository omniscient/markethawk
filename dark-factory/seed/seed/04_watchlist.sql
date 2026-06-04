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
