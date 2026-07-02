# Scanner Explainability Foundation Implementation Plan

Epic: GitHub #448, "Epic: Explainability Foundation for scanner events"

Worktree: `C:\Users\Frank\.codex\worktrees\b8e4\MarketHawk`

Branch: `codex/epic-448-explainability-foundation`

## Scope

- Add a nullable `scanner_events.explanation` JSONB column.
- Define and validate `scanner_explanation.v1` payloads.
- Generate explanations for the reference `pre_market_volume_spike` scanner.
- Return explanations through the existing scanner results API.
- Render compact explanation details in the existing scanner results surface.
- Add a backfill task and API trigger for historical events.

## Steps

1. Add backend tests for the new model column, schema validation, builder output, alert persistence, API serialization, and backfill task.
2. Add the Alembic migration and SQLAlchemy model field.
3. Add `backend/app/schemas/scanner_explanation.py` with strict scanner-neutral validation.
4. Add `backend/app/services/scanner_explanations.py` with the pre-market builder and reconstruction helper.
5. Thread optional `explanation` through alert persistence and pre-market scanner event saving.
6. Add API response field and backfill endpoint wired to a Celery task.
7. Add frontend types and a compact `ScannerExplanationPanel` in `ScannerResults`.
8. Run focused backend and frontend tests, then repo lint/type/build checks.

## Verification

- `ruff check .`
- Focused backend pytest for schema/service/API/task coverage.
- `python -m alembic heads`
- `npx tsc --noEmit -p tsconfig.app.json`
- `npx eslint . --report-unused-disable-directives-severity error`
- `npx vitest run src/components/ScannerResults.test.tsx`
- `npm run build`
