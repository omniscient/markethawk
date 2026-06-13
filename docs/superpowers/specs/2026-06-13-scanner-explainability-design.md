# Scanner Explainability, Edge Intelligence, and Optional LLM Narrative Design

**Date:** 2026-06-13
**Status:** Approved for issue creation

## Product Goal

MarketHawk scanner hits should become durable, explainable signal records. A hit should not only say that a ticker fired. It should explain why it fired, which criteria passed, which caveats or secondary checks failed, what data-quality risks affect the signal, what inputs drove confidence, how similar historical signals behaved, and what AI systems can safely say about it.

The differentiating loop is:

```text
scanner evidence -> explanation -> outcome tracking -> trait/archetype analysis -> better future decisions
```

The implementation is staged across three linked epics:

1. **Explainability Foundation**: first-class persisted explanations for scanner events. Published as GitHub issue #448.
2. **Explanation-Aware Edge Intelligence**: deterministic analogs, trait performance, archetypes, and AI-ready briefs. Published as GitHub issue #449.
3. **Optional LLM Narrative and Semantic Intelligence**: feature-flagged generated narratives, embeddings, and analyst workflows. Published as GitHub issue #450.

## Existing Project Fit

The design builds on existing MarketHawk concepts instead of replacing them:

- `ScannerEvent` already stores `indicators`, `criteria_met`, `metadata_`, `signal_quality_score`, and event summaries.
- ADR-005 already accepts JSONB as the extension model for scanner-specific event payloads.
- `DataQualityService` and `DataReadinessService` already reason about coverage, integrity, continuity, and scanner data requirements.
- Outcome tracking and Scorecard already compute post-signal MFE, MAE, follow-through, edge decay, and distributions.
- Statistical discovery already supports correlations, SHAP feature weights, and clustering.
- Frontend destinations already exist for Scanner Results, Stock Detail, Scorecard, and EdgeExplorer.

## Epic 1: Explainability Foundation

### Goal

Make scanner explanations a first-class persisted contract on every new scanner hit, starting with one reference scanner and then migrating the rest.

### Scope

- Add dedicated `scanner_events.explanation` JSONB.
- Define `scanner_explanation.v1`.
- Build scanner-neutral explanation validation and builder helpers.
- Use scanner-specific criterion IDs inside the scanner-neutral envelope.
- Enhance existing data quality/readiness services for event-scoped warnings.
- Keep `scanner_events.signal_quality_score` as the sortable scalar, and mirror or decompose it in `explanation.confidence_inputs`.
- Integrate `pre_market_volume_spike` as the reference scanner.
- Expose explanations through scanner API responses.
- Add a practical Scanner Results / Stock Detail UI for "why this fired."
- Add best-effort historical backfill.
- Migrate remaining scanners after the reference path is proven.

### Explanation Schema

```json
{
  "schema_version": "scanner_explanation.v1",
  "why": [
    "Volume was 2.3x 30-day average",
    "Price closed above VWAP"
  ],
  "criteria_passed": {
    "premarket.relative_volume": {
      "label": "Relative volume",
      "observed": 2.3,
      "threshold": 2.0,
      "operator": ">=",
      "unit": "x",
      "source": "stock_aggregates.day.volume",
      "lookback": "30d",
      "importance": 0.31
    }
  },
  "criteria_failed": {},
  "confidence_inputs": {
    "score": 0.74,
    "score_source": "signal_quality_score",
    "positive": {
      "relative_volume": 0.31,
      "above_vwap": 0.18
    },
    "negative": {},
    "missing": {}
  },
  "data_quality_warnings": [
    {
      "code": "missing_intraday_bars",
      "severity": "medium",
      "message": "12 minute bars missing during pre-market window",
      "affected_inputs": ["vwap", "pre_market_volume"]
    }
  ],
  "evidence": {
    "reconstructed": false,
    "reconstruction_quality": null,
    "generated_at": "2026-06-13T14:00:00Z",
    "generator_version": "explanation_builder.v1",
    "market_data_asof": "2026-06-13T13:45:00Z",
    "provider": "polygon"
  }
}
```

### Design Rules

- `why` is derived from structured criteria and evidence, not manually maintained as a separate source of truth.
- `criteria_passed` and `criteria_failed` use stable criterion IDs.
- Event-scoped data warnings come from enhanced existing data quality/readiness services.
- Backfilled historical explanations must be honest about reconstruction limits.
- New scanners should not invent custom top-level explanation shapes.

### Epic 1 Issues

1. **Add persisted scanner event explanation column**
   - Labels: `enhancement`, `scanner`, `priority: must-have`, `size: M`, `ready-for-agent`
   - Blocked by: none

2. **Define scanner explanation schema and validation helpers**
   - Labels: `enhancement`, `scanner`, `testing`, `priority: must-have`, `size: M`, `ready-for-agent`
   - Blocked by: issue 1

3. **Build scanner-neutral ExplanationBuilder**
   - Labels: `enhancement`, `scanner`, `testing`, `priority: must-have`, `size: L`, `ready-for-agent`
   - Blocked by: issue 2

4. **Enhance data quality and readiness services for event warnings**
   - Labels: `enhancement`, `scanner`, `analytics`, `testing`, `priority: must-have`, `size: L`, `ready-for-agent`
   - Blocked by: issue 2

5. **Integrate pre-market volume spike as the reference explained scanner**
   - Labels: `enhancement`, `scanner`, `testing`, `priority: must-have`, `size: L`, `ready-for-agent`
   - Blocked by: issues 3 and 4

6. **Expose scanner explanations through API contracts**
   - Labels: `enhancement`, `scanner`, `testing`, `priority: must-have`, `size: M`, `ready-for-agent`
   - Blocked by: issue 5

7. **Add practical scanner explanation UI**
   - Labels: `enhancement`, `frontend`, `scanner`, `testing`, `priority: must-have`, `size: L`, `ready-for-agent`
   - Blocked by: issue 6

8. **Backfill best-effort explanations for historical scanner events**
   - Labels: `enhancement`, `scanner`, `analytics`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
   - Blocked by: issue 5

9. **Migrate liquidity hunt scanners to explanation contract**
   - Labels: `enhancement`, `scanner`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
   - Blocked by: issues 5 and 8

10. **Migrate oversold bounce and pocket pivot scanners to explanation contract**
    - Labels: `enhancement`, `scanner`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
    - Blocked by: issues 5 and 8

11. **Migrate trend pullback scanner to explanation contract**
    - Labels: `enhancement`, `scanner`, `testing`, `priority: should-have`, `size: M`, `ready-for-agent`
    - Blocked by: issues 5 and 8

12. **Migrate live and social scanner event writers to explanation contract**
    - Labels: `enhancement`, `scanner`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
    - Blocked by: issues 5 and 8

## Epic 2: Explanation-Aware Edge Intelligence

### Goal

Use explanations as deterministic, analyzable signal intelligence. MarketHawk should show which reasons actually produce edge, which traits degrade results, and how the current hit compares to similar historical signals.

### Scope

- Flatten explanations into analysis features.
- Add deterministic historical analog search.
- Add explanation trait performance breakdowns.
- Add signal archetypes using explanation traits and outcomes.
- Add deterministic `ai_signal_brief` payloads that do not require LLM generation.
- Upgrade existing Scorecard and EdgeExplorer surfaces instead of creating a new page.
- Upgrade event-level UI with analogs, expected behavior, archetype, and outcome context.

### Deterministic Historical Analogs

Epic 2 should start with explainable deterministic similarity, not embeddings. Candidate inputs include:

- scanner type,
- criterion pass/fail overlap,
- normalized observed criterion values,
- confidence inputs,
- catalyst recency,
- sector and market context,
- volatility regime,
- data-quality cleanliness,
- outcome availability.

The response should include similar prior events plus outcome summaries, sample size, and warnings when analog confidence is weak.

### AI Signal Brief

Epic 2 produces model-ready payloads without generating model text:

```json
{
  "schema_version": "ai_signal_brief.v1",
  "facts": {},
  "why": [],
  "risks": [],
  "data_quality_warnings": [],
  "historical_analogs": [],
  "outcome_context": {},
  "archetype": {},
  "forbidden_claims": []
}
```

The brief is the safe substrate for Epic 3 narratives, alert copy, and analyst Q&A.

### UI Direction

- **Scanner Results / Stock Detail**: event-level explanation, analogs, expected behavior, and post-signal outcome context.
- **Scorecard**: performance by explanation trait and archetype.
- **EdgeExplorer**: research surface for trait filters, correlations, clusters, SHAP, analogs, and edge decay.

### Epic 2 Issues

1. **Extract analysis-ready features from scanner explanations**
   - Labels: `enhancement`, `analytics`, `scanner`, `testing`, `priority: must-have`, `size: L`, `ready-for-agent`
   - Blocked by: Epic 1 issues 9, 10, 11, and 12

2. **Add deterministic historical analog service**
   - Labels: `enhancement`, `analytics`, `scanner`, `testing`, `priority: must-have`, `size: L`, `ready-for-agent`
   - Blocked by: issue 1

3. **Add explanation trait performance aggregation**
   - Labels: `enhancement`, `analytics`, `scanner`, `testing`, `priority: must-have`, `size: L`, `ready-for-agent`
   - Blocked by: issue 1

4. **Generate signal archetypes from explanation traits and outcomes**
   - Labels: `enhancement`, `analytics`, `ml`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
   - Blocked by: issues 1 and 3

5. **Add deterministic AI signal brief endpoint**
   - Labels: `enhancement`, `analytics`, `ml`, `scanner`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
   - Blocked by: issues 2 and 4

6. **Upgrade Scorecard with explanation trait and archetype performance**
   - Labels: `enhancement`, `frontend`, `analytics`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
   - Blocked by: issues 3 and 4

7. **Add EdgeExplorer explanation trait filters and archetype charts**
   - Labels: `enhancement`, `frontend`, `analytics`, `ml`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
   - Blocked by: issues 2, 3, and 4

8. **Add EdgeExplorer historical analog drill-down**
   - Labels: `enhancement`, `frontend`, `analytics`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
   - Blocked by: issues 2 and 7

9. **Upgrade event-level intelligence UI**
   - Labels: `enhancement`, `frontend`, `scanner`, `analytics`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
   - Blocked by: issues 2 and 5

## Epic 3: Optional LLM Narrative and Semantic Intelligence

### Goal

Add optional model-generated narratives, semantic retrieval, and analyst workflows on top of the deterministic foundations from Epics 1 and 2.

### Scope

- Feature-flagged LLM configuration.
- Cached event narratives grounded in `ai_signal_brief`.
- Generated alert copy and post-mortems.
- Embeddings for news, catalysts, explanations, and generated narratives.
- Semantic "find signals like this" search.
- Analyst Q&A over explained events, outcomes, analogs, and briefs.
- UI toggles and provenance controls.
- Cost, latency, cache, and safety guardrails.

### Design Rules

- Epic 3 is optional. MarketHawk must remain explainable and insight-rich without LLM calls.
- Generated text must be grounded in deterministic facts.
- Narrative output must expose provenance and stale/cache state.
- Embeddings are reserved for free-text, news, catalyst, and narrative similarity. Deterministic numeric analogs remain in Epic 2.

### Epic 3 Issues

1. **Add LLM feature flags, provider config, and usage guardrails**
   - Labels: `enhancement`, `ml`, `infrastructure`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
   - Blocked by: Epic 2 issue 5

2. **Add cached scanner event narrative generation**
   - Labels: `enhancement`, `ml`, `scanner`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
   - Blocked by: issue 1

3. **Add narrative provenance and forbidden-claim enforcement**
   - Labels: `enhancement`, `ml`, `testing`, `priority: should-have`, `size: M`, `ready-for-agent`
   - Blocked by: issue 2

4. **Generate AI-assisted alert copy from signal briefs**
   - Labels: `enhancement`, `ml`, `scanner`, `testing`, `priority: could-have`, `size: M`, `ready-for-agent`
   - Blocked by: issue 3

5. **Generate signal post-mortems from explanation versus outcome**
   - Labels: `enhancement`, `ml`, `analytics`, `testing`, `priority: could-have`, `size: L`, `ready-for-agent`
   - Blocked by: issue 3

6. **Add embedding storage and retrieval foundation**
   - Labels: `enhancement`, `ml`, `analytics`, `infrastructure`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
   - Blocked by: issues 1 and 2

7. **Embed news, catalysts, explanations, and narratives**
   - Labels: `enhancement`, `ml`, `analytics`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
   - Blocked by: issue 6

8. **Add semantic find-signals-like-this search**
   - Labels: `enhancement`, `ml`, `analytics`, `frontend`, `testing`, `priority: could-have`, `size: L`, `ready-for-agent`
   - Blocked by: issue 7

9. **Add analyst Q&A over explained events and outcomes**
   - Labels: `enhancement`, `ml`, `analytics`, `frontend`, `testing`, `priority: could-have`, `size: L`, `ready-for-agent`
   - Blocked by: issues 3 and 7

10. **Add LLM cost, latency, cache, and observability controls**
   - Labels: `enhancement`, `ml`, `observability`, `performance`, `testing`, `priority: should-have`, `size: L`, `ready-for-agent`
   - Blocked by: issue 1

11. **Add UI controls for optional AI narrative layers**
    - Labels: `enhancement`, `frontend`, `ml`, `testing`, `priority: could-have`, `size: M`, `ready-for-agent`
    - Blocked by: issues 2, 4, 5, and 10

## Cross-Epic Dependencies

- Epic 2 depends on Epic 1's stable explanation schema, populated scanner events, scanner migrations, and historical backfill.
- Epic 3 depends on Epic 2's deterministic `ai_signal_brief`, analogs, outcomes, and archetypes.
- Epic 3 embeddings should not replace Epic 2 deterministic numeric analogs.

## Acceptance Criteria for the Whole Feature

- Every supported scanner hit can explain why it fired.
- Users can inspect explanations in the product without reading raw JSON.
- Explanation warnings make data-quality risk visible at event-review time.
- Historical events can be backfilled with honest reconstruction markers.
- Scorecard and EdgeExplorer can evaluate which reasons produce edge.
- AI-ready briefs expose facts, risks, warnings, analogs, and forbidden claims without requiring a live LLM.
- Optional LLM output is feature-flagged, cached, grounded, and reversible.
