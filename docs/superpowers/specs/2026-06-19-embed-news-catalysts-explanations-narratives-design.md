# Embed News, Catalysts, Explanations, and Narratives — Design

**Date:** 2026-06-19
**Issue:** #478
**Parent epic:** #450 (Optional LLM Narrative and Semantic Intelligence)
**Status:** Spec — pending review
**Blocked by:** #477 (Add embedding storage and retrieval foundation)

---

## Overview

Issue #478 creates the embedding jobs that populate the semantic-retrieval store introduced by #477 with domain-specific content. Once in place, the embedding layer allows downstream features (semantic "find signals like this" search from Epic 3 issue 8, analyst Q&A from Epic 3 issue 9) to retrieve relevant records using free-text or signal-similarity queries.

The core invariant: **every scanner workflow remains deterministic and unaffected by embedding availability.** Embeddings are an optional enrichment layer. A failure in an embedding job must never propagate to news polling, narrative generation, or any scanner code path.

---

## Requirements

Distilled from the issue acceptance criteria and Q&A:

1. **Three source types are embedded.** No separate "catalyst" source type exists — catalysts are accessed through the `news` source type (the underlying `NewsArticle` entity, joined to scanner events by ticker/time at retrieval).
   - `news` — `NewsArticle` records
   - `explanation_brief` — deterministic `ai_signal_brief` payloads from Epic 2 issue 5
   - `narrative` — generated narrative text from Epic 3 issue 2

2. **Text assembled per source type.** Each source type produces a single UTF-8 string passed to the embedding model:

   | Source type | Text assembled |
   |-------------|----------------|
   | `news` | `f"{article.title}\n\n{article.description or ''}"` — mirrors the assembly already used in `catalyst_parser.py:107` |
   | `explanation_brief` | `"\n".join(brief["why"]) + "\n\n" + "\n".join(brief["risks"]) + "\n\n" + str(brief.get("outcome_context", ""))` — human-readable prose fields only; raw JSONB keys/braces are excluded |
   | `narrative` | The full generated narrative text (plain prose, already a string) |

3. **Idempotent, version-aware batch job as the backbone.** A single Celery task `embed_pending_records` in `tasks/sync.py` selects records where the embedding is absent, stale, or failed, and embeds them in chunks. The task is registered in the Beat schedule (hourly, weekdays).

4. **Optional event-driven latency optimization.** `embed_pending_records.apply_async()` is fired (best-effort) at the tail of `poll_massive_news` and at the tail of the narrative generation flow. These calls are non-blocking: a failure in the async dispatch or in the embedding worker does not propagate to the caller.

5. **Failure tracking on the embedding record.** The embedding record from #477 must carry: `embedding_status` (`pending` / `embedded` / `failed`), `last_error` (Text, nullable), `attempt_count` (Integer), `last_attempt_at` (DateTime). The batch job selects `status IN ('pending', 'failed')` and writes `last_error` + bumps `attempt_count` on failure rather than raising to Celery retry. Fleet-level visibility is provided by the existing `celery_tasks_total{status="failure"}` metric and Seq log event.

6. **Historical backfill is included.** The batch job selects on "unembedded" with no age cutoff — equivalent to the `ScannerEvent.regime.is_(None)` filter in `backfill_regime_labels`. On first deployment, all existing `NewsArticle` rows will be processed. Chunked pagination (configurable batch size, default 100) is required to bound per-run memory and LLM API cost.

7. **Tests cover all three source types and the stale/recompute path.** For each source type: a test that embeds a fresh record (status → `embedded`), a test that re-runs on a stale record (content hash changed or model version bumped → re-embedded), and a test that the provider error path writes `last_error` and sets status → `failed` without raising.

---

## Architecture

### Service: `app/services/embedding_jobs.py`

A new `EmbeddingJobService` class encapsulates:

- **`assemble_text(source_type, record) -> str`** — builds the text string per source type.
- **`get_pending_records(db, source_type, limit) -> list[EmbeddingRecord]`** — queries the embedding store from #477 for records with `status IN ('pending', 'failed')` and the current model version. Accepts `source_type=None` to process all types.
- **`embed_and_persist(db, embedding_record) -> bool`** — calls the embedding provider (configured via Epic 3 issue 1 LLM provider config), writes the vector + `status="embedded"` + `embedded_at` on success; writes `last_error` + `status="failed"` + increments `attempt_count` on failure. Returns `True`/`False`. Never raises.

### Task: `embed_pending_records` in `tasks/sync.py`

```python
@celery_app.task(bind=True, max_retries=0, name="app.tasks.embed_pending_records")
def embed_pending_records(self, source_type: str | None = None, batch_size: int = 100):
    """
    Idempotent batch job: embed all unembedded/failed/stale records.
    source_type: 'news' | 'explanation_brief' | 'narrative' | None (all types).
    """
    ...
```

Pattern mirrors `backfill_regime_labels` in `tasks/regime.py`: open `SessionLocal()`, query for target rows, iterate and call service, log progress, close session. `max_retries=0` because the job is already idempotent — a failure on one record writes `last_error` to DB; the next scheduled run picks it up.

### Beat registration in `app/core/celery_app.py`

```python
"embed-pending-records-hourly": {
    "task": "app.tasks.embed_pending_records",
    "schedule": crontab(minute="0", hour="*", day_of_week="1-5"),
    "kwargs": {"source_type": None, "batch_size": 100},
},
```

Hourly on weekdays aligns with `poll_massive_news` (every minute, weekdays) producing fresh news. The batch size of 100 per run bounds LLM API cost without starving the catch-up queue.

### Event-driven triggers (latency optimization)

At the tail of `poll_massive_news` in `tasks/sync.py`, after news records are flushed to DB:

```python
try:
    embed_pending_records.apply_async(kwargs={"source_type": "news"})
except Exception:
    logger.warning("embed_pending_records dispatch failed — will catch up on next hourly run")
```

The narrative generation flow (Epic 3 issue 2) adds an analogous `apply_async` call after the narrative is written, targeting `source_type="narrative"`.

### Content-hash freshness tracking

Each embedding record stores a `content_hash` (SHA-256 of the assembled text). The staleness query checks `content_hash != hash_of_current_source_text` OR `model_version != current_model_version`. This is the "source freshness" mechanism — a title/description edit or model upgrade automatically triggers re-embedding on the next batch run.

---

## Alternatives Considered

### Approach B: Per-source-type Celery tasks

Three separate tasks (`embed_news_records`, `embed_explanation_briefs`, `embed_narratives`), each with its own Beat entry.

**Trade-off:** More isolation (a news embedding hang doesn't slow brief embedding), but three times the boilerplate, three Beat entries, and three code paths to test. The single unified task with a `source_type` parameter covers isolation via independent invocations without the duplication. Rejected.

### Approach C: Inline synchronous embedding inside news polling

Embed immediately inside `poll_massive_news` before the news poll task commits. Simple, no separate task.

**Trade-off:** Directly couples news polling to LLM API availability. A provider timeout fails the news poll entirely, violating "failures must not block deterministic scanner workflows." Rejected.

### Per-record audit log table (for failure visibility)

A dedicated `EmbeddingJobLog` table recording every attempt with status and error.

**Trade-off:** Full attempt history is useful but adds a model, migration, and write amplification. The existing codebase convention (used in `ScannerRun.failed_tickers`, `BacktestRun.error_message`, `SignalAnalysisRun.error_message`) is `last_error` + `attempt_count` on the owning record — sufficient for the acceptance criteria and consistent with existing patterns. Rejected.

---

## Integration Points

| Upstream dependency | What this issue consumes |
|---------------------|--------------------------|
| #477 (embedding storage) | `EmbeddingRecord` model, `embedding_store.insert/update`, retrieval API |
| Epic 3 issue 1 (LLM feature flags) | Embedding provider config, enabled/disabled flag; if LLM is disabled, `embed_and_persist` short-circuits cleanly |
| Epic 2 issue 5 (ai_signal_brief) | `ScannerEvent.explanation` JSONB containing `ai_signal_brief.v1` structure with `why`, `risks`, `outcome_context` fields |
| Epic 3 issue 2 (narrative generation) | Generated narrative text stored on (TBD) `ScannerEvent.narrative` or equivalent |
| `tasks/sync.py` `poll_massive_news` | Target of the event-driven `embed_pending_records.apply_async()` tail call |

---

## Open Questions (Non-blocking)

1. **Explanation brief field location:** The Q&A assumes `ai_signal_brief` is stored in `ScannerEvent.explanation` as a JSONB sub-key. The exact column name and structure depends on Epic 2 issue 5's implementation. The `assemble_text` method should use a defensive `brief.get("why", [])` / `brief.get("risks", [])` pattern.

2. **Hourly batch size:** 100 records per hourly run processes 2,400 records/day. If the existing `news_articles` backlog is larger (months of news polling), the first-run batch will take multiple hours to catch up. If faster initial backfill is needed, a one-time manual invocation with a higher `batch_size` can be dispatched via Celery admin. This is an operational concern, not a code change.

3. **`explanation_brief` and `narrative` row counts at implementation time:** Both upstream features may have zero rows when #478 ships. The implementation must handle `get_pending_records` returning an empty list gracefully (no-op, no error).

4. **Embedding model version string:** The model version stored in the embedding record should come from the provider config (Epic 3 issue 1). A placeholder constant (e.g., `settings.EMBEDDING_MODEL_VERSION`) should be used until that config is finalized.

---

## Assumptions

- **[A1]** Issue #477 delivers an `EmbeddingRecord` ORM model with at minimum: `source_type` (str), `source_id` (int/UUID), `model_version` (str), `content_hash` (str), `vector` (pgvector column), `embedded_at` (DateTime), and the four status/error columns specified in Requirement 5. If #477's schema differs, the `EmbeddingJobService` API surface may need adjustment.

- **[A2]** The LLM embedding provider (from Epic 3 issue 1) exposes a synchronous `embed(text: str) -> list[float]` interface that raises on failure (so `embed_and_persist` can catch it and write `last_error`).

- **[A3]** The existing `celery_tasks_total` and `celery_task_duration_seconds` Prometheus metrics automatically capture `embed_pending_records` task outcomes — no new metric definitions are needed for fleet-level visibility.

- **[A4]** "Catalyst" is not a separate embedding source type. Catalyst–event linkage is maintained at the retrieval layer by associating news article embedding IDs with scanner events via the existing `CatalystParser` ticker/time join logic (not a new DB table).
