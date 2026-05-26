-- Tweet monitor seed data
-- Seeds the @PlayBookTrades monitored account and sample tweet signals
-- Idempotent: ON CONFLICT DO NOTHING throughout

INSERT INTO monitored_accounts (handle, display_name, platform, poll_interval_seconds, enabled, classification_config, created_at, updated_at)
VALUES ('PlayBookTrades', 'PlayBook Trades', 'x', 45, true, '{}', NOW(), NOW())
ON CONFLICT ON CONSTRAINT uq_monitored_account_handle_platform DO NOTHING;
