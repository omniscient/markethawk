# ADR-005: JSONB Columns for Scanner Event Metadata

**Date**: 2026-05-28  
**Status**: Accepted

## Context

`ScannerEvent` stores the output of each scanner type. Different scanner types produce different indicator sets — the pre-market volume scanner produces `volume_ratio`, `vwap_distance`, and `gap_pct`; the oversold bounce scanner produces `rsi_14`, `distance_from_52w_low`, and `bb_width`. Storing all possible indicator values as normalized columns would require either:

- A wide table with many nullable columns (one per indicator per scanner type), growing with every new scanner, or
- A scanner-specific table per scanner type, requiring schema changes and JOIN complexity each time a new scanner is added.

Three columns on `scanner_events` use JSONB to avoid this:

| Column | Purpose |
|---|---|
| `indicators` | Numeric signal values computed by the scanner (volume ratios, RSI, gap %, etc.) |
| `criteria_met` | Boolean flags for each condition that triggered the alert |
| `metadata_` | Enrichment data added after detection (catalysts, float, short interest, splits) |

JSONB was chosen over JSON because PostgreSQL indexes JSONB as a binary document, enabling `@>` containment queries and GIN indexing — useful for queries like "all events where RSI < 30 was a criteria met flag."

### Trade-offs accepted

The primary cost of JSONB is queryability. Filtering on a specific indicator value requires a JSONB path expression (`indicators->>'volume_ratio'::numeric > 4`) rather than a simple column predicate. This is harder to write, harder for query planners to optimize without explicit GIN indexes, and harder to enforce as a schema.

For ad-hoc signal analysis (the primary query pattern), this cost is acceptable. The alternative — a normalized schema — would make adding or changing scanner types a DDL operation requiring a migration for every iteration.

## Decision

Three JSONB columns on `scanner_events`: `indicators`, `criteria_met`, and `metadata_`. Schema flexibility over query ergonomics.

New scanner types extend the payload by writing new keys into these columns. No migration is required to add a new scanner — only the service logic changes.

## Consequences

- No compile-time validation of indicator keys or value types. Errors in scanner logic produce silently wrong JSONB rather than a DB error.
- Query filtering on JSONB values requires cast syntax and may need GIN indexes for performance as event volume grows.
- The Pydantic schemas for `ScannerEvent` responses (`ScannerEventRead`) expose `indicators`, `criteria_met`, and `metadata_` as `dict[str, Any]` — callers cannot rely on a typed schema for scanner-specific fields without additional validation in the service layer.
- Adding a new scanner type is a code-only change (no migration), which was the primary motivation.
