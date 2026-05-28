"""add market_holidays table with CME 2024-2025 seed data

Revision ID: c5d6e7f8a9b0
Revises: b3c4d5e6f7a8
Create Date: 2026-04-08 00:00:00.000000

event_type values
─────────────────
  full_close   — market did not trade (Christmas, New Year's, etc.)
  early_close  — session ended at 12:00 CT (Good Friday, Christmas Eve,
                 Thanksgiving, etc.)

CME equity-index futures (NQ, ES, RTY, YM) follow the same US federal
holiday schedule.  Data sourced from CME Group holiday calendar.
Early-close sessions end at 12:00 noon CT (17:00 or 18:00 UTC depending
on Daylight Saving Time).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, tuple] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Create table (IF NOT EXISTS — idempotent) ─────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS market_holidays (
            id          SERIAL       NOT NULL,
            exchange    VARCHAR(20)  NOT NULL,
            date        DATE         NOT NULL,
            event_type  VARCHAR(20)  NOT NULL,
            description VARCHAR(200),
            PRIMARY KEY (id),
            CONSTRAINT uq_market_holiday_exchange_date UNIQUE (exchange, date)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_market_holidays_exchange
        ON market_holidays (exchange)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_market_holidays_date
        ON market_holidays (date)
    """)

    # ── Seed CME equity-index futures holiday schedule ────────────────────────
    # Covers NQ (NASDAQ-100), ES (S&P 500), RTY (Russell 2000), YM (DJIA).
    # NYSE/NASDAQ equities share the same federal-holiday calendar and are
    # seeded under the 'NYSE' key as a convenience alias.
    # ON CONFLICT DO NOTHING makes this migration idempotent.
    op.execute("""
        INSERT INTO market_holidays (exchange, date, event_type, description)
        VALUES
          -- ── 2024 ─────────────────────────────────────────────────────────
          ('CME',  '2024-01-01', 'full_close',  'New Year''s Day'),
          ('CME',  '2024-01-15', 'full_close',  'MLK Jr. Day'),
          ('CME',  '2024-02-19', 'full_close',  'Presidents'' Day'),
          ('CME',  '2024-03-29', 'early_close', 'Good Friday — early close 12pm CT'),
          ('CME',  '2024-05-27', 'full_close',  'Memorial Day'),
          ('CME',  '2024-06-19', 'full_close',  'Juneteenth National Independence Day'),
          ('CME',  '2024-07-03', 'early_close', 'Independence Day Eve — early close 12pm CT'),
          ('CME',  '2024-07-04', 'full_close',  'Independence Day'),
          ('CME',  '2024-09-02', 'full_close',  'Labor Day'),
          ('CME',  '2024-11-28', 'early_close', 'Thanksgiving Day — early close 12pm CT'),
          ('CME',  '2024-11-29', 'early_close', 'Day after Thanksgiving — early close 12pm CT'),
          ('CME',  '2024-12-24', 'early_close', 'Christmas Eve — early close 12pm CT'),
          ('CME',  '2024-12-25', 'full_close',  'Christmas Day'),

          -- ── 2025 ─────────────────────────────────────────────────────────
          ('CME',  '2025-01-01', 'full_close',  'New Year''s Day'),
          ('CME',  '2025-01-09', 'full_close',  'National Day of Mourning — President Carter'),
          ('CME',  '2025-01-20', 'full_close',  'MLK Jr. Day / Inauguration Day'),
          ('CME',  '2025-02-17', 'full_close',  'Presidents'' Day'),
          ('CME',  '2025-04-18', 'early_close', 'Good Friday — early close 12pm CT'),
          ('CME',  '2025-05-26', 'full_close',  'Memorial Day'),
          ('CME',  '2025-06-19', 'full_close',  'Juneteenth National Independence Day'),
          ('CME',  '2025-07-03', 'early_close', 'Independence Day Eve — early close 12pm CT'),
          ('CME',  '2025-07-04', 'full_close',  'Independence Day'),
          ('CME',  '2025-09-01', 'full_close',  'Labor Day'),
          ('CME',  '2025-11-27', 'early_close', 'Thanksgiving Day — early close 12pm CT'),
          ('CME',  '2025-11-28', 'early_close', 'Day after Thanksgiving — early close 12pm CT'),
          ('CME',  '2025-12-24', 'early_close', 'Christmas Eve — early close 12pm CT'),
          ('CME',  '2025-12-25', 'full_close',  'Christmas Day'),

          -- ── NYSE alias (US equities share the same federal calendar) ─────
          ('NYSE', '2024-01-01', 'full_close',  'New Year''s Day'),
          ('NYSE', '2024-01-15', 'full_close',  'MLK Jr. Day'),
          ('NYSE', '2024-02-19', 'full_close',  'Presidents'' Day'),
          ('NYSE', '2024-03-29', 'early_close', 'Good Friday — early close 1pm ET'),
          ('NYSE', '2024-05-27', 'full_close',  'Memorial Day'),
          ('NYSE', '2024-06-19', 'full_close',  'Juneteenth National Independence Day'),
          ('NYSE', '2024-07-03', 'early_close', 'Independence Day Eve — early close 1pm ET'),
          ('NYSE', '2024-07-04', 'full_close',  'Independence Day'),
          ('NYSE', '2024-09-02', 'full_close',  'Labor Day'),
          ('NYSE', '2024-11-28', 'full_close',  'Thanksgiving Day'),
          ('NYSE', '2024-11-29', 'early_close', 'Day after Thanksgiving — early close 1pm ET'),
          ('NYSE', '2024-12-24', 'early_close', 'Christmas Eve — early close 1pm ET'),
          ('NYSE', '2024-12-25', 'full_close',  'Christmas Day'),

          ('NYSE', '2025-01-01', 'full_close',  'New Year''s Day'),
          ('NYSE', '2025-01-09', 'full_close',  'National Day of Mourning — President Carter'),
          ('NYSE', '2025-01-20', 'full_close',  'MLK Jr. Day / Inauguration Day'),
          ('NYSE', '2025-02-17', 'full_close',  'Presidents'' Day'),
          ('NYSE', '2025-04-18', 'full_close',  'Good Friday'),
          ('NYSE', '2025-05-26', 'full_close',  'Memorial Day'),
          ('NYSE', '2025-06-19', 'full_close',  'Juneteenth National Independence Day'),
          ('NYSE', '2025-07-03', 'early_close', 'Independence Day Eve — early close 1pm ET'),
          ('NYSE', '2025-07-04', 'full_close',  'Independence Day'),
          ('NYSE', '2025-09-01', 'full_close',  'Labor Day'),
          ('NYSE', '2025-11-27', 'full_close',  'Thanksgiving Day'),
          ('NYSE', '2025-11-28', 'early_close', 'Day after Thanksgiving — early close 1pm ET'),
          ('NYSE', '2025-12-24', 'early_close', 'Christmas Eve — early close 1pm ET'),
          ('NYSE', '2025-12-25', 'full_close',  'Christmas Day'),

          -- ── 2026 ─────────────────────────────────────────────────────────
          -- Note: Jul 4 falls on Saturday; observed closure is Jul 3 (Friday)
          ('CME',  '2026-01-01', 'full_close',  'New Year''s Day'),
          ('CME',  '2026-01-19', 'full_close',  'MLK Jr. Day'),
          ('CME',  '2026-02-16', 'full_close',  'Presidents'' Day'),
          ('CME',  '2026-04-03', 'early_close', 'Good Friday — early close 12pm CT'),
          ('CME',  '2026-05-25', 'full_close',  'Memorial Day'),
          ('CME',  '2026-06-19', 'full_close',  'Juneteenth National Independence Day'),
          ('CME',  '2026-07-03', 'full_close',  'Independence Day (observed — Jul 4 falls on Saturday)'),
          ('CME',  '2026-09-07', 'full_close',  'Labor Day'),
          ('CME',  '2026-11-26', 'early_close', 'Thanksgiving Day — early close 12pm CT'),
          ('CME',  '2026-11-27', 'early_close', 'Day after Thanksgiving — early close 12pm CT'),
          ('CME',  '2026-12-24', 'early_close', 'Christmas Eve — early close 12pm CT'),
          ('CME',  '2026-12-25', 'full_close',  'Christmas Day'),

          ('NYSE', '2026-01-01', 'full_close',  'New Year''s Day'),
          ('NYSE', '2026-01-19', 'full_close',  'MLK Jr. Day'),
          ('NYSE', '2026-02-16', 'full_close',  'Presidents'' Day'),
          ('NYSE', '2026-04-03', 'full_close',  'Good Friday'),
          ('NYSE', '2026-05-25', 'full_close',  'Memorial Day'),
          ('NYSE', '2026-06-19', 'full_close',  'Juneteenth National Independence Day'),
          ('NYSE', '2026-07-03', 'full_close',  'Independence Day (observed — Jul 4 falls on Saturday)'),
          ('NYSE', '2026-09-07', 'full_close',  'Labor Day'),
          ('NYSE', '2026-11-26', 'full_close',  'Thanksgiving Day'),
          ('NYSE', '2026-11-27', 'early_close', 'Day after Thanksgiving — early close 1pm ET'),
          ('NYSE', '2026-12-24', 'early_close', 'Christmas Eve — early close 1pm ET'),
          ('NYSE', '2026-12-25', 'full_close',  'Christmas Day')
        ON CONFLICT (exchange, date) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_market_holidays_date")
    op.execute("DROP INDEX IF EXISTS ix_market_holidays_exchange")
    op.execute("DROP TABLE IF EXISTS market_holidays")
