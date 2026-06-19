# Embedding Storage and Retrieval Foundation — Design

**Date:** 2026-06-19
**Status:** Pending review
**Issue:** [#477](https://github.com/omniscient/markethawk/issues/477)
**Epic:** [#450 — Optional LLM Narrative and Semantic Intelligence](https://github.com/omniscient/markethawk/issues/450)

## Overview

MarketHawk's Epic 3 requires a durable, queryable store for dense vector embeddings
computed from free-text sources: news articles, catalysts, scanner explanations, and
generated narratives. This foundation layer provides the storage model, retrieval
service, and test infrastructure — without embedding generation logic and without
touching the deterministic historical analog service from Epic 2.

The design delivers:
- A `Embedding` ORM model backed by `embeddings` PostgreSQL table
- `EmbeddingService` with `upsert` and `find_similar` methods
- Python-side cosine similarity retrieval (no pgvector extension required)
- Graceful degradation when no embeddings exist (disabled/missing-provider path)

Downstream issues that depend on this foundation: issue 7 (embed news/catalysts/
explanations/narratives), issue 8 (semantic "find signals like this" search),
issue 9 (analyst Q&A).

## Requirements

1. Embedding records store: `source_type`, `source_id`, `model`, `model_version`,
   `dimension`, `vector`, `metadata`, `created_at`, `updated_at`.
2. The unique key is `(source_type, source_id, model, model_version)`. Upserting
   the same key overwrites the vector and metadata in place (`updated_at` bumped).
   A new `model_version` produces a new row automatically.
3. `source_type` is a `String(50)` column (not a DB enum) so new types can be added
   without migrations. Initial valid values: `news`, `catalyst`, `explanation`,
   `narrative`.
4. `find_similar(db, query_vector, top_k, source_type, model, model_version)` returns
   the top-k most similar embeddings by cosine similarity. All parameters except
   `db` and `query_vector` are optional filters.
5. When no embeddings match the filter, `find_similar` returns an empty list (not an
   exception). This covers the "LLM provider disabled" path.
6. `find_similar` must validate that `query_vector` dimension matches the stored
   `dimension` for the filtered set; raises `ValueError` on mismatch.
7. The deterministic analog service (`services/`) must not import or call any
   embedding service. No coupling at model, service, or router level.
8. Tests cover: insert, update-existing (same key), retrieval order correctness,
   source-type filtering, model-version filtering, empty-result graceful return,
   dimension mismatch error.

## Architecture

### Data model — `backend/app/models/embedding.py`

```python
from sqlalchemy import Column, String, Integer, DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
import sqlalchemy as sa
from app.models.base import Base
from app.utils.time import utc_now
import uuid

class Embedding(Base):
    __tablename__ = "embeddings"

    id           = Column(sa.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type  = Column(String(50),  nullable=False)   # news|catalyst|explanation|narrative
    source_id    = Column(sa.UUID(as_uuid=True), nullable=False)
    model        = Column(String(100), nullable=False)   # e.g. "text-embedding-3-small"
    model_version = Column(String(50), nullable=False)   # semver or date stamp
    dimension    = Column(Integer,     nullable=False)   # vector length for guard
    vector       = Column(ARRAY(sa.Float), nullable=False)
    meta         = Column("metadata", JSONB, nullable=True)
    created_at   = Column(DateTime,   nullable=False, default=utc_now)
    updated_at   = Column(DateTime,   nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_id", "model", "model_version",
            name="uq_embeddings_source_model_version",
        ),
        Index("ix_embeddings_source_type",    "source_type"),
        Index("ix_embeddings_source_id",      "source_id"),
        Index("ix_embeddings_source_type_id", "source_type", "source_id"),
    )
```

Follow the existing model file convention: add the import to
`backend/app/models/__init__.py` and generate an Alembic autogenerate migration.
No `CREATE EXTENSION` step is needed — `ARRAY(Float)` is native to
`postgres:15-alpine`.

### Service — `backend/app/services/embedding_service.py`

```python
class EmbeddingService:

    @staticmethod
    def upsert(
        db: Session,
        source_type: str,
        source_id: UUID,
        model: str,
        model_version: str,
        vector: list[float],
        metadata: dict | None = None,
    ) -> Embedding:
        """Insert or overwrite an embedding record."""

    @staticmethod
    def get(
        db: Session,
        source_type: str,
        source_id: UUID,
        model: str,
        model_version: str,
    ) -> Embedding | None:
        """Fetch a single embedding record, or None if absent."""

    @staticmethod
    def find_similar(
        db: Session,
        query_vector: list[float],
        top_k: int = 10,
        source_type: str | None = None,
        model: str | None = None,
        model_version: str | None = None,
    ) -> list[tuple[Embedding, float]]:
        """
        Return the top-k most similar embeddings by cosine similarity.
        Applies SQL filters (source_type, model, model_version) before
        fetching vectors; computes similarity in Python via numpy.
        Returns [] when no embeddings match (graceful degradation).
        Raises ValueError if any candidate dimension != len(query_vector).
        """

    @staticmethod
    def delete(
        db: Session,
        source_type: str,
        source_id: UUID,
        model: str | None = None,
        model_version: str | None = None,
    ) -> int:
        """Delete matching embeddings. Returns count deleted."""
```

**Retrieval implementation detail:** `find_similar` builds a `db.query(Embedding)`
with optional `filter(Embedding.source_type == source_type)` etc., fetches all
candidate rows, then computes cosine similarity with numpy in a single vectorized
pass. The result is sorted descending and sliced to `top_k`. At the expected scale
of thousands of records this is fast; the B-tree indexes on `source_type` and
`source_id` ensure the candidate set is pre-filtered in SQL before Python sees it.

The `upsert` implementation uses a try/except around an INSERT with
`on_conflict_do_update` (PostgreSQL `INSERT ... ON CONFLICT`) keyed to the unique
constraint, updating `vector`, `meta`, `updated_at`, and `dimension`.

### No REST endpoint at this layer

The acceptance criterion "Retrieval API supports top-k semantic matches" is fully
satisfied by the Python service method above. Issue #8 ("Add semantic find-signals-
like-this search") owns the REST endpoint and response schema. Adding one now would
create a user-facing surface with no consumer and pre-empt #8's design decisions
(query-by-event-ID semantics, ranking, response shape).

### Tests — `backend/tests/services/test_embedding_service.py`

Use the project's standard transaction-rollback `db` fixture from `conftest.py`
(SAVEPOINT isolation, no MagicMock). Cover:

| Test | Scenario |
|------|----------|
| `test_upsert_creates` | Insert new record; verify all fields stored |
| `test_upsert_updates_existing` | Same `(source_type, source_id, model, model_version)`; verify vector + `updated_at` overwritten |
| `test_upsert_new_version_new_row` | Different `model_version` → distinct row |
| `test_find_similar_order` | 3 embeddings; verify similarity rank order |
| `test_find_similar_source_type_filter` | Two source types; filter returns only requested |
| `test_find_similar_model_version_filter` | Two model versions; filter returns only requested |
| `test_find_similar_empty_returns_empty_list` | No embeddings stored → `[]` (disabled/missing-provider path) |
| `test_find_similar_dimension_mismatch` | Query vector length ≠ stored dimension → `ValueError` |
| `test_delete_by_source` | Delete by source_type + source_id; count returned |

## Alternatives Considered

### A: pgvector extension

Add `pgvector` Python package, switch `docker-compose.yml` postgres image to
`pgvector/pgvector:pg15`, store the embedding column as the native `Vector(dim)`
type, and use IVFFLAT/HNSW indexing for approximate nearest-neighbor queries.

**Rejected because:** The current postgres service uses `postgres:15-alpine` with
no custom image build. Switching images (or maintaining a custom `Dockerfile`) adds
operational overhead and complicates the production upgrade path documented in
`deployment-guide.md`. At thousands-of-records scale the IVFFLAT index threshold
isn't met anyway (pgvector recommends ≥1M rows for IVFFLAT; under that, an exact
scan is faster than an approximate one). If scale demands it later, migrating from
`ARRAY(Float)` to a pgvector `Vector` column is a single Alembic migration.

### B: JSONB blob

Store the vector as a JSON array in a `JSONB` column.

**Rejected because:** `JSONB` is opaque to SQL arithmetic operators and loses the
type safety that `ARRAY(Float)` provides. numpy cannot operate directly on JSONB
without deserialization overhead, and there is no structural advantage over a typed
array column. `JSONB` is the right choice for `metadata` (variable-key dicts), not
for the vector itself.

## Open Questions

- **Future pgvector migration path**: if embedding volume grows beyond ~100K rows,
  the `ARRAY(Float)` column can be replaced with a pgvector `Vector` column in a
  single `ALTER TABLE ... ALTER COLUMN` migration. The service interface (Python
  method signatures) is unchanged — only the similarity query implementation swaps
  from numpy to pgvector SQL operators.
- **Source ID typing**: `source_id` is typed as UUID. Ensure that all embedding
  consumers (issue 7) use the UUID PK of the respective source model
  (`NewsArticle.id`, `ScannerEvent.id`). Non-UUID PKs would require `source_id`
  to become `String` — not expected given existing model conventions.

## Assumptions

- **[Assumption]** The `app.utils.time.utc_now` helper used elsewhere in the backend
  is available for `created_at`/`updated_at` defaults (confirmed: present in
  `backend/app/utils/time.py` per backend-patterns memory).
- **[Assumption]** Blockers #472 and #473 will be merged before this issue's
  Celery embedding tasks run; this foundation issue does not call any LLM provider
  itself, so it can be implemented independently of the provider configuration.
- **[Assumption]** The `source_id` column stores the UUID PK of the referenced
  source model row. No foreign-key constraint is added (different source types
  point to different tables); referential integrity is enforced by the application
  layer in issue 7.
