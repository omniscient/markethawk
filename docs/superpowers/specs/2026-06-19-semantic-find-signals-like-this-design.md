# Semantic Find-Signals-Like-This Search — Design

**Date:** 2026-06-19
**Issue:** #479
**Parent:** #450 (Epic: Optional LLM Narrative and Semantic Intelligence)
**Status:** Spec — pending review
**Blocked by:** #478 (Embed news, catalysts, explanations, and narratives)

---

## Overview

Scanner hits produce structured explanations (Epic 1) and deterministic numeric analogs (Epic 2). This feature adds a third retrieval layer: **embedding-based semantic similarity**. Users can ask "find me signals like this event" or type a free-text query such as "FDA approval squeeze" and get back events or content whose *narrative and catalyst texture* resembles their input — surface matches that deterministic numeric analogs would miss because their criteria values differ.

Semantic search is strictly additive. The deterministic analog path remains unchanged. Embeddings are reserved for free-text, news, catalyst, and narrative similarity, per the Epic 3 design rule.

---

## Requirements

Distilled from the acceptance criteria and Q&A:

1. **Two search modes**:
   - **Event-based**: given a `scanner_event.id`, find historically similar content using that event's embedding (its explanation, associated news, catalyst text, and generated narrative if present).
   - **Free-text query**: given an arbitrary query string (e.g., "FDA approval squeeze"), embed it on-the-fly and find similar content.
2. **Four content types** are searched in both modes: news articles, catalysts, scanner explanations, and generated narratives. Each result carries a `source_type` discriminator.
3. **Results are structurally separated** from deterministic analogs — a distinct `semantic_results` array, never interleaved with the analog response.
4. Every result item includes: `source_type`, `similarity_score`, `match_reason` (best-effort snippet or explanation text), `event_id` (nullable), `ticker` (nullable).
5. **Feature-flagged**: when disabled, the endpoint returns HTTP 200 with `{ "semantic_results": [], "feature_disabled": true }`. The UI degrades to an empty state with a hint. No conditional route registration.
6. **Provider-configurable**: embedding generation flows through the same LLM provider abstraction built in Epic 3 issue 1. No local heavyweight model (e.g., sentence-transformers/PyTorch) in the default backend image.
7. **Vector storage**: inherited from upstream issue #477. Expected baseline: embedding vectors stored as float arrays in plain PostgreSQL columns; similarity computed with numpy cosine distance in Python. If #477 introduces pgvector, #479 uses it; this spec documents the baseline so the feature is not blocked.
8. **Tests** must cover: event-based search returning results, free-text query returning results, empty corpus (no-result state), and feature-disabled state.

---

## Architecture / Approach

### New endpoint

```
POST /api/v1/scanner/semantic-search
```

Accepts `event_id` (UUID, optional) or `query_text` (string, optional) — exactly one must be provided.

**Request schema** (`SemanticSearchRequest`):
```python
class SemanticSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: Optional[UUID] = None
    query_text: Optional[str] = Field(None, max_length=1000)
    limit: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def exactly_one_input(self):
        if (self.event_id is None) == (self.query_text is None):
            raise ValueError("Provide exactly one of event_id or query_text")
        return self
```

**Response schema** (`SemanticSearchResponse`):
```python
class SemanticMatchItem(BaseModel):
    source_type: Literal["news", "catalyst", "scanner_explanation", "narrative"]
    similarity_score: float
    match_reason: Optional[str]  # excerpt or explanation text; nullable
    event_id: Optional[UUID]
    ticker: Optional[str]

class SemanticSearchResponse(BaseModel):
    semantic_results: list[SemanticMatchItem]
    feature_disabled: bool = False
```

### Service layer

`SemanticSearchService` (new file `backend/app/services/semantic_search.py`):

1. Check `settings.SEMANTIC_SEARCH_ENABLED`; return early with `feature_disabled=True` if off.
2. Resolve query embedding:
   - Event-based: load the event's pre-computed embedding from the `signal_embeddings` table (or equivalent established by #477/#478). Fall back to re-embedding on demand if embedding is absent for the event.
   - Free-text: call the provider's `embed(text)` method to produce a vector on the fly.
3. Query all embeddings from the corpus (`signal_embeddings`/`content_embeddings` table, all four `source_type` values) using the storage layer from #477.
4. Compute cosine similarity: `numpy.dot(query_vec, corpus_matrix) / (norm_q * norms_corpus)`.
5. Return top-`limit` results, excluding the query event itself (event-based mode).

### Settings

Add to `backend/app/core/config.py`:
```python
SEMANTIC_SEARCH_ENABLED: bool = False  # off by default until Epic 3 issue 1 LLM config lands
```

### Frontend integration

**Event-based — Scanner Results / Stock Detail:**
- Add a "Find similar" secondary action to `ScannerEventRow` / `ScannerHistoryPanel`.
- On click: `POST /api/v1/scanner/semantic-search` with the event's `id`.
- Render results in a slide-out panel or inline expansion, clearly labelled "Semantic matches" (not "Analogs" — that label is reserved for the deterministic Epic 2 path).
- If `feature_disabled: true`, render a muted "Semantic search is not enabled" hint instead.

**Free-text query — EdgeExplorer:**
- Add a "Narrative search" input to `EdgeExplorer.tsx` alongside the existing ticker/scannerType filters.
- On submit: `POST /api/v1/scanner/semantic-search` with `query_text`.
- Render a `semantic_results` list below any existing analysis panels, with each item showing `source_type` badge, `similarity_score`, `ticker`, and `match_reason` excerpt.
- Empty state: "No semantic matches found."

---

## Alternatives Considered

### Alt A: Embed via a local sentence-transformers model in the backend image

**Rejected.** `requirements.txt` has no PyTorch or transformers. Adding sentence-transformers would pull hundreds of MB into the default backend/celery image. The Epic 3 design rule requires the feature to be optional and zero-overhead when off; a local model makes embedding always-on and heavyweight. The isolated `forecast-worker` (profile-gated, 32 GB RAM) shows where ML dependencies belong when they are truly optional.

### Alt B: Use pgvector for vector storage

**Deferred to #477.** The current Postgres image (`postgres:15-alpine`) has no pgvector; adding it requires a custom image layer. At the expected corpus scale (thousands of embeddings, not millions) brute-force numpy cosine in Python is fast enough. If #477 adopts pgvector, #479 benefits automatically because `SemanticSearchService` delegates storage to whatever #477 provides.

### Alt C: Interleave semantic and deterministic results with a `result_type` discriminator

**Rejected.** The acceptance criteria explicitly requires semantic results to be labelled separately from deterministic analogs. Interleaving forces consumers to filter by a discriminator field and merges two result types that carry structurally different payloads (deterministic analogs expose numeric criterion deltas; semantic matches expose cosine similarity and source text). Separate arrays enforce the separation structurally and make no-result testing trivial.

### Alt D: Standalone semantic search page

**Rejected.** Both search modes fit existing destination pages (Scanner Results / Stock Detail for event-scoped actions, EdgeExplorer as the research surface). A standalone page fragments the explainability story and adds a route with no precedent.

---

## Open Questions (non-blocking)

1. **Embedding dimension and model version**: `#477` will fix the embedding model/version. `SemanticSearchService` should tolerate model-version mismatch gracefully (skip stale embeddings or re-embed) but the retry/recompute policy is owned by #477/#478.
2. **Batching for on-demand re-embedding**: if a query event lacks a pre-computed embedding, the service re-embeds it on the fly. For high-cardinality queries (many events without embeddings) this could be slow. A background idempotent backfill job in #478 should minimize this; #479 only needs a single on-demand fallback call.
3. **Rate limiting the endpoint**: `POST /api/v1/scanner/semantic-search` calls the embedding provider. Consider applying `SCANNER_LIMIT` (5/min via SlowAPI) until the Epic 3 issue 10 cost/latency guardrails land.

---

## Assumptions

- **[ASSUMED]** Issue #477 establishes a `signal_embeddings` (or equivalent) table in PostgreSQL with columns for `source_type`, `source_id`, `embedding` (float array), `model_version`, and `ticker`. If the schema differs, `SemanticSearchService` adapts to whatever #477 provides — it must not re-define storage.
- **[ASSUMED]** The Epic 3 issue 1 LLM provider abstraction includes an `embed(text) -> list[float]` method alongside the text-generation methods. If Epic 3 issue 1 has not landed when #479 is implemented, a thin `EmbeddingProvider` stub (with the same flag-gated interface) can be used as a placeholder.
- **[ASSUMED]** "Generated narratives" in the embedding corpus are nullable — most events will not have narratives until Epic 3 issue 2 lands. Queries against an empty or partial corpus return empty results rather than errors.
- **[ASSUMED]** The `match_reason` field is populated from the best available source: explanation `why` text (Epic 1) for scanner_explanation source_type, article title for news, catalyst label for catalyst, and a narrative excerpt for narrative. For source types where this is absent, `match_reason` is null.
