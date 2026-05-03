# Dark Factory: Smart Continue for Preview Stack

**Date:** 2026-05-03
**Status:** Approved
**Scope:** `.archon/workflows/archon-dark-factory.yaml` — `preview-up` node only

## Problem

When running `"Continue issue #N"`, the dark factory's `preview-up` node performs the full bootstrap sequence regardless of whether a preview stack is already running:

1. `docker compose up -d --build` (full image rebuild)
2. `Base.metadata.create_all` (creates tables)
3. `alembic stamp head` (stamps current revision)
4. `alembic upgrade head` (runs migrations)

Steps 2 and 3 are harmful on continue — stamping head on an existing DB can mark migrations as applied when they weren't, and `create_all` is redundant if alembic owns the schema. Step 1 is wasteful but not harmful thanks to Docker layer caching.

## Design

### Detection

After `docker compose up -d --build`, query the preview postgres to check if tables already exist:

```bash
TABLE_COUNT=$(docker compose -p "mh-preview-${ISSUE}" \
  -f dark-factory/docker-compose.preview.yml \
  exec -T postgres psql -U postgres -d stockscanner -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" 2>/dev/null || echo "0")
```

### Branching logic

- **Tables exist (continue with existing DB):** Skip `create_all` and `stamp head`. Only run `alembic upgrade head` — idempotent, catches any new migrations from the continue work.
- **No tables (fresh DB):** Full bootstrap — `create_all`, `stamp head`, `upgrade head`. Same as current behavior.

### What stays the same

- `docker compose up -d --build` always runs. Docker layer cache reuses unchanged layers; only the final COPY layer rebuilds when source code changes.
- The entrypoint (fresh clone, dep install) is unchanged.
- The `docker-compose.preview.yml` file is unchanged — no volume mounts added.
- All other workflow nodes are untouched.
- "new" and "close" intent behavior is unchanged.

## Changes

**File:** `.archon/workflows/archon-dark-factory.yaml`
**Node:** `preview-up` (bash)

Replace the fixed bootstrap sequence with a conditional that checks for existing tables before deciding which initialization steps to run.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Persistent workspace volume | No | Fresh clone is fine — repo is 9MB, source of truth is the remote branch |
| Volume mounts for live code | No | Lean on Docker layer cache instead — simpler, no compose file changes |
| DB init on continue | Always run `alembic upgrade head` | Idempotent, catches new migrations without risk of stamping over un-applied ones |
| Skip `stamp head` on continue | Yes | Stamping on an existing DB is the main correctness risk |
