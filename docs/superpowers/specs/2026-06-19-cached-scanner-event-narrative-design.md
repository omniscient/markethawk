# Cached Scanner Event Narrative Generation — Design

**Date:** 2026-06-19
**Issue:** #473
**Parent Epic:** #450 (Epic: Optional LLM Narrative and Semantic Intelligence)
**Blocked by:** #472 (LLM feature flags, provider config, and usage guardrails)
**Status:** Spec — pending review

---

## Overview

Scanner events already carry structured indicators, criteria, and enrichment metadata. Epic 2 adds a deterministic `ai_signal_brief` (facts, why, risks, data_quality_warnings, historical_analogs, outcome_context, archetype, forbidden_claims) that is machine-readable but not human-prose. Issue #473 adds optional LLM narrative generation on top of that brief: a short, grounded prose summary generated once and cached until the brief or the LLM configuration changes. When the feature is disabled the API returns the structured brief data with no generated text, so the deterministic explainability layer remains intact.

---

## Requirements

1. Narratives are derived solely from `ai_signal_brief.facts` and `ai_signal_brief.risks` — no other inputs fed to the LLM.
2. Each generated narrative is cached in PostgreSQL with provenance metadata: `model`, `provider`, `version` (prompt-template version), `brief_hash`, `generated_at`.
3. The cache is considered stale when any of the following differ from the current state: the brief content hash, the active `provider`, the active `model`, or the `version`. No time-based TTL.
4. When the LLM feature is disabled (per #472's `SystemConfig` flag), the endpoint returns the deterministic brief data with `narrative_text = null` — no LLM call, no cache write.
5. Narrative generation is synchronous and demand-driven (lazy cache-on-miss). No background pre-generation is in scope.
6. Tests cover four cases: cache hit (row exists, hashes/versions match), cache miss (no row → generate + persist), disabled feature (flag off → null text, no DB write), and stale brief (`brief_hash` mismatch → regenerate, not serve old text).
7. The narrative must respect `ai_signal_brief.forbidden_claims` — the system prompt must explicitly instruct the model not to make claims listed there.

---

## Architecture / Approach

### New Model: `ScannerEventNarrative`

New file: `backend/app/models/scanner_event_narrative.py`

```python
class ScannerEventNarrative(Base):
    __tablename__ = "scanner_event_narratives"

    id          = Column(Integer, primary_key=True)
    scanner_event_id = Column(Integer, ForeignKey("scanner_events.id", ondelete="CASCADE"), index=True)

    # Generated content
    narrative_text = Column(Text, nullable=False)

    # Provenance / cache-key metadata
    brief_hash  = Column(String(64), nullable=False)   # SHA-256 of ai_signal_brief payload
    provider    = Column(String(50), nullable=False)   # e.g. "anthropic"
    model       = Column(String(100), nullable=False)  # e.g. "claude-haiku-4-5"
    version     = Column(String(20), nullable=False)   # prompt template version, e.g. "narrative_v1"
    generated_at = Column(DateTime, default=utc_now)

    event = relationship("ScannerEvent", back_populates="narrative")
```

`ScannerEvent` gains: `narrative = relationship("ScannerEventNarrative", back_populates="event", uselist=False, cascade="all, delete-orphan")`

Register in `backend/app/models/__init__.py`. Generate and apply Alembic migration.

### Staleness Check

Cache is valid when all four columns match the current config from #472:

```python
CURRENT_VERSION = "narrative_v1"

def _is_stale(cached: ScannerEventNarrative, brief_hash: str, config: LLMConfig) -> bool:
    return (
        cached.brief_hash != brief_hash
        or cached.provider != config.provider
        or cached.model    != config.model
        or cached.version  != CURRENT_VERSION
    )
```

### New Service: `NarrativeService`

New file: `backend/app/services/narrative_service.py`

```
get_or_generate_narrative(event: ScannerEvent, db: Session) -> NarrativeResponse
```

1. Read `llm_enabled` and narrative-area flag from SystemConfig (from #472). If disabled → return `NarrativeResponse(brief=event_brief, narrative_text=None)`.
2. Compute `brief_hash = sha256(json.dumps(brief["facts"] + brief["risks"], sort_keys=True))`.
3. Query `scanner_event_narratives` by `scanner_event_id`. If row exists and not stale → return cached text + metadata.
4. On cache miss or stale: call `anthropic.Anthropic().messages.create(...)` using `provider`, `model`, `max_tokens`, `timeout`, `retry_policy` from #472 config. System prompt: "Generate a concise 2–3 sentence narrative summarizing this scanner signal using only the provided facts and risks. Do not make any of the following claims: {forbidden_claims}."
5. Persist new `ScannerEventNarrative` row (delete old stale row first if present). `db.commit()` before returning.
6. Return `NarrativeResponse(brief=event_brief, narrative_text=generated_text, model=..., provider=..., version=..., generated_at=..., brief_hash=...)`.

### New Endpoint

Router: `backend/app/routers/scanner.py` (or a new `narrative.py` router mounted at `/api/v1/scanner/`)

```
GET /api/v1/scanner/events/{event_uuid}/narrative
```

- Parse `event_uuid` as `uuid.UUID` (400 on bad input, 404 if no event).
- Fetch the `ScannerEvent` and its `ai_signal_brief` (from the event's JSONB — brief availability is guaranteed by #472's dependency on Epic 2, Issue 5).
- Delegate to `NarrativeService.get_or_generate_narrative(event, db)`.
- Return `ScannerEventNarrativeResponse` Pydantic schema.

### Response Schema

```python
class ScannerEventNarrativeResponse(BaseModel):
    event_uuid: uuid.UUID
    brief: dict                     # the ai_signal_brief payload (always present)
    narrative_text: Optional[str]   # null when feature is disabled
    model: Optional[str]
    provider: Optional[str]
    version: Optional[str]
    generated_at: Optional[datetime]
    brief_hash: Optional[str]
    cached: bool                    # True if served from cache, False if freshly generated
```

### LLM Provider

Use the `anthropic` Python SDK (already the project's AI API). Default model: `claude-haiku-4-5` (fast, low-cost, well-suited for short structured-text → prose). Model and provider are read from #472's config, not hardcoded — operators can raise the tier without code changes. The `version` field records the prompt-template version so prompt improvements can be deployed by bumping `CURRENT_VERSION` and letting stale rows regenerate lazily.

### Rate Limiting / Concurrency Guard

Because the endpoint is synchronous with a 1–10s LLM call on cache miss, add a short Redis lock on `(scanner_event_id, brief_hash)` using `SET NX EX 30` (via `core/cache.py`) before generation. A concurrent second request hitting the same cache miss reads the lock, waits briefly, and retries the DB look-up — avoiding duplicate LLM spend. This is advisory; the DB row has no unique constraint issue since the service deletes the old stale row before inserting.

---

## Alternatives Considered

### A: JSONB column on `scanner_events`

Store the narrative inline as `Column(JSONB)` on the main `scanner_events` table. Simpler, no new table. Rejected because: `scanner_events` is a hot table queried by the paginated results list; adding unbounded LLM text to each row bloats scans. It also conflates durable operational signal data with derived AI output, and makes multi-version provenance harder to track.

### B: Auto-generate on event creation (Celery task)

Fire a Celery task per `ScannerEvent` create when LLM is enabled. Rejected because: scans produce events in bulk and narratives would be generated for events no user opens, burning the usage guardrails that #472 introduces. It also collapses the cache-miss acceptance-criterion path into an edge case that's hard to exercise in tests.

### C: Async POST + Celery + poll

`POST /api/v1/scanner/events/{uuid}/narrative/generate` returns 202 with a task ID; frontend polls. More appropriate for bulk generation. Rejected for the per-event demand path: it adds a second polling loop, a task-status surface, and doesn't match the synchronous shape of the existing `/events/{uuid}/review` endpoint. If bulk narrative pre-warming is added later (e.g., top-N events in a results page), Option C is the extension pattern — not a replacement for the demand-driven GET.

---

## Assumptions

- **[ASSUMPTION]** Epic 2, Issue 5 ("Add deterministic AI signal brief endpoint") ships before this issue is implemented. This spec assumes `ai_signal_brief` is available as a JSONB field on or retrievable from a `ScannerEvent`.
- **[ASSUMPTION]** Issue #472 ships first and provides: an `llm_enabled` feature flag (disabled by default), a narrative-area allowed-feature gate, `provider`/`model`/`max_tokens`/`timeout`/`retry_policy` config keys in `SystemConfig`.
- **[ASSUMPTION]** The `anthropic` Python package is available as a backend dependency. If not, it must be added to `backend/requirements.txt`.
- **[ASSUMPTION]** The narrative length target is 2–3 sentences (~50–120 words). `max_tokens` from #472 config enforces this at the API layer; the prompt instructs the model.

---

## Open Questions

1. **Brief location**: Is `ai_signal_brief` stored as a JSONB column on `scanner_events` directly, or returned by a separate service that computes it on-demand from explanation data? The spec assumes it is accessible from the event at request time; the implementation may need a brief-fetch helper depending on how Epic 2 persists it.
2. **Concurrency approach**: The Redis lock approach is advisory. If the synchronous worker thread holding for 10s causes timeouts under load, the fallback is to return a 202 + polling shape for the generation path only (keeping the read-from-cache path synchronous). This could be decided at implementation time.
3. **Forbidden-claims injection**: The `ai_signal_brief.forbidden_claims` field may be empty for many events. The implementation should handle the empty case gracefully (omit the forbidden-claims instruction if the list is empty).

---

## Test Cases

| Case | Setup | Expected |
|---|---|---|
| Cache hit | Row exists, brief_hash/model/provider/version all match | Return cached text, `cached=True`, no LLM call |
| Cache miss | No row in `scanner_event_narratives` | Call LLM, persist row, return text, `cached=False` |
| Stale brief | Row exists but `brief_hash` differs | Delete old row, call LLM, persist new row, return text |
| Feature disabled | `llm_enabled=False` in SystemConfig | Return brief data, `narrative_text=None`, no LLM call, no DB write |
| Stale model version | Row exists but `model` or `version` differs from config | Treat as stale, regenerate |

LLM call in tests should be mocked (patch `anthropic.Anthropic.messages.create`). DB tests use the transaction-rollback fixture from `backend/tests/conftest.py`.
