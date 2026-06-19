# Signal Post-Mortems — Design (issue #476)

**Date:** 2026-06-19
**Issue:** [#476](https://github.com/omniscient/markethawk/issues/476) — Generate signal post-mortems from explanation versus outcome
**Parent epic:** [#450](https://github.com/omniscient/markethawk/issues/450) — Optional LLM Narrative and Semantic Intelligence (Epic 3, issue 5)
**Blocked by:** [#474](https://github.com/omniscient/markethawk/issues/474) — Narrative provenance and forbidden-claim enforcement

---

## Overview

When a scanner signal's outcome is fully resolved, MarketHawk should be able to generate a **post-mortem**: a structured comparison of what was known at signal time (the explanation, expected analog behavior, archetype, risks) against what actually happened (the realized MFE/MAE/r-multiple, follow-through, gap-filled status).

The post-mortem is an optional, feature-flagged, LLM-assisted artifact that builds on the Epic 1 `explanation` JSONB and Epic 2 `ai_signal_brief`, and is grounded in the deterministic `ScannerOutcomeSummary` metrics. It distinguishes two temporal layers — the at-signal picture and the realized outcome — and produces a verdict and a narrative that could not have been written at signal time.

This issue ships the backend generation pipeline, caching, API, and test coverage. Frontend display is out of scope; it belongs to Epic 3 issue 11 ("Add UI controls for optional AI narrative layers"), which is blocked by this issue.

---

## Requirements

1. **Post-mortem generation is optional and feature-flagged.** A `SystemConfig` key (`signal_post_mortem_enabled`) gates all generation. When disabled, the table may be empty; the API returns HTTP 503.

2. **Post-mortems are generated automatically when outcome data completes.** When `ScannerOutcomeSummary.is_complete` transitions to `True`, a Celery task fires (mirroring the `evaluate_scanner_alerts` pattern) to generate a post-mortem for that event — if and only if the feature flag is enabled.

3. **Post-mortems are also regeneratable on demand** via `POST /api/v1/scanner/events/{uuid}/post-mortem`. Cached results are returned unless `is_stale=True` or `?force=true` is passed.

4. **Post-mortems use a frozen at-signal snapshot** so the record is reproducible even if the source explanation or brief later mutates.

5. **The verdict is computed deterministically** (not by the LLM) from `ScannerOutcomeSummary` fields: `follow_through`, `mfe_mae_ratio`, `r_multiple`. The LLM writes the narrative; it does not decide the verdict.

6. **The verdict enum has four states:** `incomplete` (outcome not done), `won`, `lost`, `neutral`. Verdict thresholds are stored in `SystemConfig` so they are tunable without code changes.

7. **Provenance and staleness tracking** follow the `SignalNarrative` conventions from Epic 3.2: `provenance` JSONB records source schema versions and generator version; `is_stale` is set when the source explanation or brief changes after generation.

8. **Tests cover** all four verdict states (won, lost, neutral, incomplete-outcome), the disabled-flag path, and on-demand regeneration with `is_stale` set.

---

## Data Model

### New table: `signal_post_mortems`

One-to-one with `scanner_events.id` (FK with `ondelete="CASCADE"`, matching `SignalReview`).

```python
class SignalPostMortem(Base):
    __tablename__ = "signal_post_mortems"

    id = Column(Integer, primary_key=True, index=True)
    scanner_event_id = Column(
        Integer,
        ForeignKey("scanner_events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Deterministic verdict — computed before the LLM call
    verdict = Column(String(20), nullable=False, index=True)
    # Values: "won" | "lost" | "neutral" | "incomplete"

    # Structured comparison payload (see schema below)
    comparison = Column(JSONB, nullable=False, default=dict)

    # LLM-generated narrative (null when incomplete-outcome or disabled)
    narrative_text = Column(Text, nullable=True)

    # Provenance — mirrors SignalNarrative conventions from Epic 3.2
    provenance = Column(JSONB, nullable=False, default=dict)
    model = Column(String(100), nullable=True)  # e.g. "claude-sonnet-4-6"
    generated_at = Column(DateTime, nullable=True)
    is_stale = Column(Boolean, default=False, index=True)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
```

### `comparison` JSONB schema

Three fixed top-level keys enforce the "known vs realized" temporal split:

```json
{
  "schema_version": "signal_post_mortem.v1",
  "at_signal": {
    "why": ["Volume was 2.3x 30-day average", "Price closed above VWAP"],
    "confidence_score": 0.74,
    "expected": {
      "median_mfe": 3.1,
      "win_rate": 0.62,
      "sample_size": 47
    },
    "archetype": {
      "label": "momentum_spike",
      "success_rate": 0.64
    },
    "analogs": [
      {"ticker": "AAPL", "date": "2026-01-10", "outcome_mfe_pct": 4.2}
    ],
    "risks": ["Elevated MAE in similar prior events", "Low catalyst recency"],
    "data_quality_warnings": [
      {"code": "missing_intraday_bars", "severity": "medium"}
    ]
  },
  "realized": {
    "mfe_pct": 2.8,
    "mfe_time_minutes": 42,
    "mae_pct": -1.1,
    "mae_time_minutes": 18,
    "mfe_mae_ratio": 2.55,
    "r_multiple": 0.9,
    "eod_pct_change": 2.1,
    "follow_through": true,
    "gap_filled": false
  },
  "delta": {
    "mfe_vs_expected": -0.3,
    "archetype_held": true
  }
}
```

- `at_signal` is a **frozen copy** taken from `ScannerEvent.explanation` and `ai_signal_brief` at generation time. Analogs are capped to 3 entries.
- `realized` is named fields from `ScannerOutcomeSummary` — not duplicated snapshots (those remain queryable via `ScannerOutcomeSnapshot` by event id).
- `delta` is computed deterministically: `mfe_vs_expected = realized.mfe_pct - at_signal.expected.median_mfe`; `archetype_held = realized.follow_through == (at_signal.archetype.success_rate >= 0.5)`.
- When `verdict == "incomplete"`, `realized` and `delta` are empty dicts; `narrative_text` is null.

### `provenance` JSONB schema

```json
{
  "explanation_schema_version": "scanner_explanation.v1",
  "brief_schema_version": "ai_signal_brief.v1",
  "post_mortem_schema_version": "signal_post_mortem.v1",
  "generator_version": "post_mortem_generator.v1",
  "verdict_thresholds": {
    "mfe_mae_ratio_win_floor": 1.0,
    "r_multiple_loss_ceiling": -1.0
  }
}
```

### Verdict determination (deterministic, pre-LLM)

Check in order — first match wins:

| Priority | Verdict | Condition |
|----------|---------|-----------|
| 1 | `incomplete` | `ScannerOutcomeSummary.is_complete == False` |
| 2 | `won` | `follow_through == True` AND `mfe_mae_ratio >= {mfe_mae_ratio_win_floor}` |
| 3 | `lost` | `follow_through == False` AND (`mfe_mae_ratio < 1` OR `r_multiple <= {r_multiple_loss_ceiling}`) |
| 4 | `neutral` | all other cases |

Thresholds are read from `SystemConfig`:
- `signal_post_mortem_mfe_mae_ratio_win_floor` (default `"1.0"`)
- `signal_post_mortem_r_multiple_loss_ceiling` (default `"-1.0"`)

The verdict is stored in `SignalPostMortem.verdict` before the LLM call. If the flag is disabled, the verdict is still computed and stored so the record exists for the incomplete-outcome test case.

---

## Architecture

### Generation flow

```
ScannerOutcomeSummary.is_complete → True
       │
       ▼
Celery task: generate_signal_post_mortem(event_id)
       │
       ├── Check SystemConfig signal_post_mortem_enabled → False? → return early (no row written)
       │
       ├── Load ScannerEvent (explanation, uuid)
       ├── Load ai_signal_brief (from ScannerEvent or SignalNarrative, per Epic 2/3 pattern)
       ├── Load ScannerOutcomeSummary (metrics)
       │
       ├── Compute verdict (deterministic)
       ├── Build comparison.at_signal (freeze explanation + brief fields)
       ├── Build comparison.realized (copy outcome metrics)
       ├── Build comparison.delta (mfe_vs_expected, archetype_held)
       │
       ├── verdict == "incomplete"?
       │     ├── Yes → write SignalPostMortem(verdict="incomplete", comparison=..., narrative_text=None)
       │     └── No  → call LLM with {comparison, verdict, provenance} as context
       │                    └── write SignalPostMortem(verdict=..., comparison=..., narrative_text=<llm output>)
       │
       └── Write provenance, model, generated_at, is_stale=False
```

### Where the Celery task is triggered

In `tasks/quality.py` (or `tasks/scanning.py`), mirror the pattern from `evaluate_scanner_alerts`:

```python
# Called when outcome backfill updates is_complete → True
generate_signal_post_mortem.delay(outcome_summary.scanner_event_id)
```

The task itself lives in `tasks/scanning.py` alongside other signal-lifecycle tasks.

### LLM prompt constraints

- The LLM is given `comparison` (frozen; no live DB access) and `verdict` (already decided).
- The prompt includes `provenance.forbidden_claims` from the `ai_signal_brief` (carried forward from Epic 3.3), blocking the LLM from asserting those.
- Output is a single paragraph (≤300 tokens) focused on the comparison narrative.
- Provider and model are read from `SystemConfig` (existing LLM config from Epic 3.1).

### Staleness tracking

Set `is_stale = True` when:
- `ScannerEvent.explanation` is updated after the post-mortem was generated.
- The `ai_signal_brief` version changes (checked via `provenance.brief_schema_version`).

The on-demand `POST .../post-mortem` endpoint regenerates and clears `is_stale`.

---

## API

Both endpoints live on the scanner router (`routers/scanner.py`), alongside `POST /events/{uuid}/review`.

### `GET /api/v1/scanner/events/{uuid}/post-mortem`

Returns the cached post-mortem for the event.

| Condition | Response |
|-----------|----------|
| Feature flag disabled | `HTTP 503` with `{"detail": "Post-mortem generation is disabled"}` |
| Post-mortem not generated yet | `HTTP 404` |
| Post-mortem exists | `HTTP 200` with `SignalPostMortemResponse` schema |

Response schema (`schemas/scanner.py`):

```python
class SignalPostMortemResponse(BaseModel):
    uuid: UUID
    scanner_event_uuid: UUID
    verdict: str  # "won" | "lost" | "neutral" | "incomplete"
    comparison: dict
    narrative_text: str | None
    provenance: dict
    model: str | None
    generated_at: datetime | None
    is_stale: bool
    created_at: datetime
    updated_at: datetime
```

### `POST /api/v1/scanner/events/{uuid}/post-mortem`

Triggers on-demand generation or regeneration.

| Condition | Response |
|-----------|----------|
| Feature flag disabled | `HTTP 503` |
| No `ScannerOutcomeSummary` row | `HTTP 422` with `{"detail": "No outcome summary available"}` |
| Existing post-mortem, not stale, `?force` not set | `HTTP 200` (cached) |
| Stale or `?force=true` | Regenerates synchronously, `HTTP 200` |
| New (no existing row) | Generates synchronously, `HTTP 201` |

Query param: `?force=true` (bool, default false) — bypass cache and regenerate.

---

## Approach Alternatives Considered

### Alternative A: Extend `SignalNarrative` with a `type` discriminator

Rejected. `SignalNarrative` is a one-to-one artifact per event (narrative text only). Adding a discriminator creates a mixed-type table with a mostly-null column set per type, and complicates staleness logic that's already designed for a single artifact. The pattern of one-table-per-concern (see `ScannerOutcomeSummary`, `SignalReview`, `ScannerOutcomeSnapshot`) is consistent across the codebase.

### Alternative B: JSONB column on `ScannerOutcomeSummary`

Rejected. `ScannerOutcomeSummary` is the deterministic, computed metrics row — written by the outcome-completion pipeline with no LLM dependency. Adding a stochastic, feature-flagged, regenerable LLM artifact to that table couples two very different concerns and gives no clean place for provenance, model, or staleness fields. It also makes `is_complete → True` the trigger *and* the target of generation, which is architecturally circular.

### Alternative C: On-demand only (no automatic generation)

Rejected. The acceptance criteria phrase "cached, feature-flagged, and provenance-aware" strongly implies a pre-computed cache, not a purely lazy-on-request system. The existing Celery pattern (`evaluate_scanner_alerts`) demonstrates that event-lifecycle hooks are the standard for derivative artifact generation.

---

## Open Questions (non-blocking)

1. **LLM call latency.** The automatic Celery path is async so latency doesn't affect the user path, but the on-demand `POST` is synchronous. If LLM calls exceed ~10s, consider making the on-demand endpoint asynchronous (enqueue a task, return 202, let the client poll or call GET). The `run_backtest` endpoint (`POST /api/v1/backtest/runs`, HTTP 202) demonstrates this pattern. Recommend starting synchronous and switching if P95 latency is measured above 5s.

2. **Forbidden-claims handling.** The LLM narrative must not assert `forbidden_claims` from the `ai_signal_brief`. Epic 3.3 (#474) implements this enforcement layer. This issue consumes it. The exact enforcement mechanism (pre-prompt injection vs post-generation filter) is defined by #474 and should not be re-invented here.

3. **Backfill for historical events.** Events that completed their outcomes before this feature is deployed will have no post-mortems. A backfill Celery task (iterating `ScannerOutcomeSummary WHERE is_complete=True`) is straightforward but out of scope for this issue — treat it as a follow-on.

---

## Assumptions

- **[ASSUMPTION]** `SignalNarrative` table exists with fields `scanner_event_id`, `narrative_text`, `provenance` JSONB, `model`, `generated_at`, `is_stale`. This is Epic 3.2 prior work. If its schema differs, the `provenance` field conventions in this spec should be reconciled.
- **[ASSUMPTION]** `ai_signal_brief` is retrievable per event at generation time, either as a stored column/row (Epic 2) or regenerated on demand. The spec assumes it is stored (not live-computed) so the `at_signal` snapshot can be a frozen copy.
- **[ASSUMPTION]** The `forbidden_claims` enforcement from Epic 3.3 (#474) exposes a reusable helper (e.g., `enforce_forbidden_claims(narrative_text, forbidden_claims)`) that this service can call without re-implementing the guardrail.
- **[ASSUMPTION]** LLM provider config (model, API key, timeout) is already in `SystemConfig` from Epic 3.1. This issue does not add new LLM configuration keys, only the post-mortem–specific feature flag and verdict threshold constants.
