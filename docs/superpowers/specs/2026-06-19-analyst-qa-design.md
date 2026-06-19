# Analyst Q&A Over Explained Events and Outcomes

**Date:** 2026-06-19
**Issue:** #480
**Parent epic:** #450 (Optional LLM Narrative and Semantic Intelligence)
**Status:** Spec

## Overview

This feature adds a stateless, feature-flagged analyst Q&A capability that lets the operator ask natural-language questions about scanner events and their outcomes. Answers are grounded in deterministic event/outcome data and cite the specific fields they draw from. The capability is unavailable when LLM features are disabled and never required for the core scanning or outcome workflows.

**In scope:**
- Backend Q&A service: context assembly, Anthropic API call, provenance tracking
- New `/api/v1/analyst-qa/` router with `status` and `ask` endpoints
- Frontend: collapsible Q&A panel in Scanner Results (filtered-set scope) and inline per-event Q&A on StockDetailPage
- Feature-flag gate (`analyst_qa_enabled` SystemConfig key)
- `ANTHROPIC_API_KEY` env var wired through `Settings`
- Tests: grounded generation, unsupported questions, disabled state

**Out of scope:**
- Multi-turn conversation history (stateless only; see design decision below)
- Multi-LLM provider abstraction (Anthropic only; model is configurable)
- Caching / cost observability controls (covered by a separate Epic 3 issue #10)
- Embedding-based semantic retrieval slots (populated when #478 lands; spec accounts for forward compatibility)
- Full `ai_signal_brief` from Epic 2 (spec defines a brief-builder abstraction that works now and upgrades later)

## Requirements

1. Q&A is feature-flagged via `analyst_qa_enabled` in `SystemConfig`. `GET /api/v1/analyst-qa/status` returns `{enabled, model}`. When disabled, `POST /api/v1/analyst-qa/ask` returns HTTP 404.
2. Questions may target a single event (`event_id`) or a filtered set (`event_ids`, max 25).
3. Answers must cite which source fields they draw from (`grounded_fields` per event in the response).
4. The LLM system prompt must enumerate only the fields that are actually populated in the assembled brief, so the model cannot claim grounding it does not have.
5. The `ANTHROPIC_API_KEY` environment variable is optional at startup; the backend raises a descriptive config error at request time if the key is absent while the feature is enabled.
6. The model used is configurable via `analyst_qa_model` in `SystemConfig` (default `claude-sonnet-4-6`). No code change needed to change models.
7. The frontend Q&A panel renders only when the feature is enabled (no progressive disclosure for a disabled state — the acceptance criterion says the feature must be "unavailable").
8. Tests must cover: grounded answer generation (populated fields), unsupported question detection (model instructed to refuse out-of-scope questions), disabled state (404), missing API key, and valid/invalid request shapes.

## Architecture

### Backend

#### New service: `backend/app/services/analyst_qa.py`

```
load_qa_config(db)           -> {enabled: bool, model: str, api_key: str | None}
build_brief(event_ids, db)   -> dict  # ai_signal_brief.v1 shape
answer_question(question, event_ids, db) -> AnalystQAResponse
```

**Brief builder** (`build_brief`):

Targets the `ai_signal_brief.v1` contract, populating from what exists today. This is forward-compatible: when Epic 2 delivers a real `/ai-signal-brief` endpoint and #474/#478 add provenance/embeddings, the builder becomes a thin pass-through to those artifacts and the legacy field-mapping path is retired.

Fields populated now:
- `facts` ← `ScannerEvent.ticker`, `event_date`, `scanner_type`, `signal_quality_score`, `regime`, `open_price`, `close_price`, `volume`
- `why` ← `ScannerEvent.summary`, `criteria_met`
- `risks` ← `ScannerEvent.metadata_` (catalyst flags, float rotation, data quality fields)
- `data_quality_warnings` ← left empty until explanation schema lands (#448)
- `historical_analogs` ← left empty until analog service lands (#449 issue 2)
- `outcome_context` ← `ScannerOutcomeSummary` fields if present (MFE%, MAE%, time_to_mfe, follow_through)
- `archetype` ← left empty until archetypes land (#449 issue 4)
- `forbidden_claims` ← hardcoded: model must not claim the trade was profitable/unprofitable unless outcome data is present; must not claim analog count unless analog slot is populated

Fields left empty must appear in the prompt as explicitly absent so the model never fabricates them.

#### System prompt structure

```
You are an analyst assistant for a stock scanner tool. Answer questions about the provided scanner event data only.

GROUNDING RULES:
- Only reference facts present in the data below.
- If a field is listed as UNAVAILABLE, do not infer or estimate it.
- If the question cannot be answered from available data, say so explicitly.
- At the end of your answer, list which data fields you used.

FORBIDDEN CLAIMS:
{forbidden_claims}

EVENT DATA:
{brief_json}
```

The model is instructed to refuse questions about investment advice, price predictions, or anything outside the supplied event data.

#### New router: `backend/app/routers/analyst_qa.py`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/analyst-qa/status` | Returns `{enabled: bool, model: str \| null}`. Auth required. Rate-limit exempt (cheap read). |
| `POST` | `/api/v1/analyst-qa/ask` | Accepts `AnalystQARequest`; returns `AnalystQAResponse`. Returns 404 if disabled. |

#### Schemas: `backend/app/schemas/analyst_qa.py`

```python
class AnalystQARequest(BaseModel):
    question: str  # min 5 chars, max 500 chars
    event_id: UUID | None = None
    event_ids: list[UUID] | None = None  # max 25
    # Exactly one of event_id or event_ids must be set (validator enforced)

class AnalystQASource(BaseModel):
    event_id: UUID
    grounded_fields: list[str]  # e.g. ["summary", "signal_quality_score", "outcome.mfe_pct"]

class AnalystQAResponse(BaseModel):
    answer: str
    model: str
    sources: list[AnalystQASource]
```

#### Config / env

- `backend/app/core/config.py`: add `ANTHROPIC_API_KEY: str = ""` (optional; empty at startup is fine)
- `SystemConfig` keys (added via Alembic seed or startup upsert):
  - `analyst_qa_enabled` — `"false"` default
  - `analyst_qa_model` — `"claude-sonnet-4-6"` default

No new tables required. The feature is entirely stateless.

#### Exception types

- `QADisabledError(MarketHawkError)` — raised when `analyst_qa_enabled != "true"`; router converts to 404
- `QAConfigError(MarketHawkError)` — raised when API key is absent while enabled; router converts to 503
- `QAContextError(MarketHawkError)` — raised when event IDs are not found; router converts to 404

### Frontend

#### API client: `frontend/src/api/analyst_qa.ts`

```typescript
export interface AnalystQAStatus { enabled: boolean; model: string | null }
export interface AnalystQASource { event_id: string; grounded_fields: string[] }
export interface AnalystQAResponse { answer: string; model: string; sources: AnalystQASource[] }

export async function getQAStatus(): Promise<AnalystQAStatus>
export async function askQuestion(req: { question: string; event_id?: string; event_ids?: string[] }): Promise<AnalystQAResponse>
```

#### Scanner Results panel: `frontend/src/components/AnalystQAPanel.tsx`

- Collapsible panel at the bottom of the ScannerResults component
- Passes `event_ids` from the currently displayed result set (up to 25)
- Input: free-text textarea (max 500 chars) + "Ask" button
- Output: answer text, model label, and collapsed source field list per event
- Loading state uses a spinner; errors surface inline (not toast)
- Panel is not rendered when `status.enabled === false`

#### StockDetailPage integration

- "Ask about this event" affordance on the ScannerHistoryPanel per event row
- Clicking opens an inline Q&A area (not a modal) below the row, posting `event_id` only
- Same `AnalystQAPanel` component, configured for single-event mode

#### Feature flag gate

On app load (or Scanner page mount), React Query fetches `GET /api/v1/analyst-qa/status` with a 60-second stale time. If `enabled === false`, neither panel renders. No skeleton or "coming soon" placeholder — the acceptance criterion says the feature must be "unavailable."

## Approach

**Chosen: Stateless Q&A with Anthropic Claude, model configurable via SystemConfig, brief-builder abstraction for forward compatibility.**

Each question is a single HTTP round-trip: assemble brief from DB, call Anthropic, return answer + provenance. No server-side conversation history. No session state. The brief-builder targets `ai_signal_brief.v1` shape so the contract is stable when real briefs and embeddings land.

## Alternatives Considered

### Multi-turn conversation history

Would require a `qa_thread` + `qa_message` model, Alembic migration, context-windowing logic, and thread-scoped caching. For a single-user analyst tool where each question is anchored to a specific event or event set, the extra persistence adds no analytical value — the context doesn't accumulate meaningfully across sessions. Rejected.

### Provider-agnostic multi-LLM abstraction

Adds interface boilerplate and divergent SDK handling (streaming, retry, token counting) for providers not in the stack. The `SystemConfig`-driven model key already lets the operator switch model tiers (haiku → sonnet → opus) without a code change, which covers the cost/quality tradeoff without a provider abstraction. Rejected.

### Strict blocker gating (wait for full ai_signal_brief)

Would leave #480 permanently blocked on artifacts that may arrive across multiple PRs. The brief-builder abstraction with empty-but-declared slots resolves this: the Q&A is grounded in what exists, slots that are unpopulated are declared as UNAVAILABLE in the prompt (so the model cannot hallucinate them), and the contract doesn't change when real briefs arrive. Rejected in favor of the forward-compatible builder.

## Open Questions (non-blocking)

- **Response caching**: Should identical `(question, event_ids, brief_hash)` tuples reuse cached answers? The separate LLM cost/latency/cache issue (#450 epic 3 issue 10) will define the caching strategy; this spec leaves caching as a future enhancement.
- **Streaming responses**: The Anthropic API supports streaming (SSE). Should `/ask` stream the answer progressively or return it as a single JSON response? For simplicity this spec specifies non-streaming (single response), but the service layer should not prevent streaming from being added later.
- **Rate limiting**: The `/ask` endpoint should sit under `SCANNER_LIMIT` (5/min) to avoid accidental LLM cost spikes, but the exact limit belongs to the cost-controls issue. The spec records the intent without mandating the exact value.

## Assumptions

- `ScannerOutcomeSummary` model exists and is reachable via `ScannerEvent.outcome_summary` relationship (or a DB join). If not yet built, `outcome_context` in the brief is left empty and declared UNAVAILABLE.
- The `anthropic` Python SDK (e.g. `anthropic>=0.69`) is added to `backend/requirements.txt`.
- `SystemConfig` keys are upserted on backend startup (or via Alembic data migration) rather than requiring manual DB insertion.
- The frontend `AnalystQAStatus` fetch uses the existing Axios client (`frontend/src/api/client.ts`) and follows the `['analyst-qa-status']` React Query key convention.
- The Anthropic API is called synchronously from the FastAPI handler (using `anthropic.Anthropic().messages.create`). The handler runs in a threadpool executor (`run_in_executor`) to avoid blocking the event loop.
