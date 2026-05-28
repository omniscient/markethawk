# ADR-009: Naive UTC Timestamps in the Database

**Date**: 2026-05-28  
**Status**: Accepted

## Context

PostgreSQL's `TIMESTAMP WITHOUT TIME ZONE` column type stores a bare datetime with no timezone information. SQLAlchemy's `DateTime` column maps to this type by default. Python `datetime` objects can be either timezone-aware (with a `tzinfo`) or timezone-naive.

If a timezone-aware datetime is passed to a `TIMESTAMP WITHOUT TIME ZONE` column, recent versions of SQLAlchemy/psycopg2 raise a warning or error. The historically common workaround was to store naive datetimes and document the convention that all stored values are UTC.

Every `created_at` and `updated_at` column across the MarketHawk models uses this pattern:

```python
default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
```

This generates the correct UTC moment and then strips the timezone annotation before writing to the DB. Reading the value back produces a naive datetime that consumers must know is UTC.

### Why not `TIMESTAMPTZ`?

`TIMESTAMP WITH TIME ZONE` (`TIMESTAMPTZ`) stores an absolute moment in time and always normalises to UTC internally. It removes the ambiguity entirely. Migrating to `TIMESTAMPTZ` would be the correct long-term path and would eliminate the `.replace(tzinfo=None)` discipline requirement. The cost is a column-level migration across all models — mechanical but broad.

At the time the models were written, the naive UTC pattern was the established codebase convention. Changing it mid-build would have required coordinating migrations with active feature work.

## Decision

All `DateTime` columns store naive UTC datetimes. The `.replace(tzinfo=None)` pattern is the project-wide convention for generating these values.

## Consequences

- Any code that reads a `created_at` or `updated_at` value and needs to do timezone-aware arithmetic must manually re-attach UTC: `value.replace(tzinfo=timezone.utc)`.
- Passing a timezone-aware datetime directly to a model field will either silently strip the timezone (older psycopg2 behaviour) or raise a warning/error depending on SQLAlchemy version. Always strip before writing.
- If the system is ever extended to support multiple timezones (e.g., per-user display preferences), the naive UTC pattern becomes a liability — all stored times must be re-interpreted as UTC at the application layer.
- The migration to `TIMESTAMPTZ` columns is the clean long-term fix; it can be done as a targeted Alembic migration with `ALTER TABLE ... ALTER COLUMN ... TYPE TIMESTAMPTZ USING ... AT TIME ZONE 'UTC'`. Until then, the `.replace(tzinfo=None)` pattern must be followed in every new model.
