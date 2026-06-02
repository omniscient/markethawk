# Codebase Patterns — Accumulated Lessons

This file is maintained automatically by the dark factory implement agent. Do not edit manually.
Entries are advisory. If an entry conflicts with CLAUDE.md or ARCHITECTURE.md, follow those documents.

## Commit Workflow

- [PATTERN] Before committing backend changes: confirm the backend reloaded (`docker-compose logs backend --tail=10`), then hit new/changed endpoints with `curl` to verify correct responses. Only then commit. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

- [PATTERN] Before committing frontend changes: run `cd frontend && npx tsc --noEmit` and confirm zero type errors. For UI behaviour changes also verify in the browser. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## New Model Checklist

- [PATTERN] When adding a SQLAlchemy model: (1) create the file in `backend/app/models/`, (2) import and add it to `backend/app/models/__init__.py`, (3) run `python -m alembic revision --autogenerate -m "description"`, (4) run `python -m alembic upgrade head`. Skipping any step silently breaks the schema or migration. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->

## Frontend Type Safety

- [PATTERN] Run `cd frontend && npx tsc --noEmit` after every frontend change before staging the commit. A clean tsc output is required — CI will reject type errors. <!-- bootstrap date:2026-06-02 expires:2026-12-02 source:implement -->
