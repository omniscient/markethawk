# Canonical Signal Replay Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Epic #483 by shipping the additive replay engine: reproducible manifests, intraday exit simulation, benchmark regimes, execution metrics, REST endpoints, and the `/replay` UI.

**Architecture:** Add new `ReplayRun` and `ReplayTrade` tables beside the existing backtest tables. Keep replay services in `backend/app/services/replay/`, with pure simulation/metrics logic unit-tested separately from task/router orchestration. Expose a thin `/api/v1/replay` router and a React Query powered page that renders server-derived run analytics.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, Celery, PostgreSQL JSONB, pytest, React 19, TypeScript, React Query, Recharts, Lightweight Charts.

## Global Constraints

- Do not modify or replace the existing `BacktestRun` / `BacktestTrade` feature.
- Do not use Dark Factory; Epic #483 child tickets are reserved with `ready-for-human`.
- Use TDD for production behavior: write failing tests before implementation code.
- Reuse `StockAggregate` for benchmark bars; do not introduce a parallel benchmark table.
- `exit_fidelity` values are `"intraday"` and `"daily"`.
- `benchmark_symbol` is a manifest field and defaults to `"SPY"`.
- Store reproducibility inputs as immutable JSON snapshots on `replay_runs`.
- Keep headline metrics queryable as scalar columns and detailed analytics in `metrics` JSONB.
- Frontend API calls go through `apiClient`; no raw `fetch`.

---

### Task 1: Models, Manifest Resolver, Data Hash (#484)

**Files:**
- Create: `backend/app/models/replay_run.py`
- Create: `backend/app/models/replay_trade.py`
- Create: `backend/app/services/replay/__init__.py`
- Create: `backend/app/services/replay/manifest.py`
- Create: `backend/app/alembic/versions/f1a2b3c4d5e6_add_replay_engine_tables.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/services/test_replay_manifest.py`

**Interfaces:**
- Produces `ReplayRun`, `ReplayTrade`, `ManifestResolver`, `ResolvedManifest`, `compute_data_hash`.
- Later tasks consume `ReplayRun.universe_snapshot["tickers"]`, `strategy_snapshot`, `data_hash`, and `ReplayTrade` ledger fields.

- [ ] Write failing manifest/data-hash tests:
  - `ManifestResolver.resolve()` freezes scanner config, optional strategy, and sorted universe tickers.
  - Mutating source objects after `resolve()` does not mutate returned snapshots.
  - `compute_data_hash()` is stable for identical bars and changes when one OHLCV field changes.
  - `compute_data_hash()` changes when minute-bar count or applied split version changes.
  - `ReplayRun.metrics` is nullable until computed and `trading_strategy_id` accepts null.
- [ ] Verify red with `python -m pytest tests/services/test_replay_manifest.py -q`.
- [ ] Implement models, migration, manifest resolver, and package exports.
- [ ] Verify green with targeted pytest and model import smoke test.

### Task 2: Intraday Exit Simulator (#485)

**Files:**
- Create: `backend/app/services/replay/protocols.py`
- Create: `backend/app/services/replay/exit_simulator.py`
- Test: `backend/tests/services/test_replay_exit_simulator.py`

**Interfaces:**
- Produces `SignalRecord`, `StrategyParams`, `SimulatedTrade`, `ExitSimulator`, `IntradayExitSimulator`.
- Later task consumes `IntradayExitSimulator.simulate(signal, strategy, bars, max_hold_days)`.

- [ ] Write failing fixture tests for long stop-first, long target-first, time exit, EOD no-fill, daily fallback stop-first, and short-only inversion.
- [ ] Verify red with `python -m pytest tests/services/test_replay_exit_simulator.py -q`.
- [ ] Implement pure simulator with no DB access.
- [ ] Verify green.

### Task 3: Benchmark Ingestion and Regime Classifier (#486)

**Files:**
- Create: `backend/app/services/replay/benchmark.py`
- Create: `backend/app/services/replay/classifier.py`
- Modify: `backend/app/services/replay/__init__.py`
- Test: `backend/tests/services/test_replay_benchmark.py`
- Test: `backend/tests/services/test_replay_regime_classifier.py`

**Interfaces:**
- Produces `BenchmarkIngestor`, `BenchmarkIngestionError`, `ReplayRegime`, `RegimeClassifier`, `get_benchmark_regime`.
- Execution task uses the ingestor and classifier to tag trades.

- [ ] Write failing tests for idempotent gap-fill, interior gap detection, provider error wrapping, SMA200 trend labels, realized-vol buckets, threshold validation, and carry-forward lookup.
- [ ] Verify red with targeted pytest.
- [ ] Implement benchmark and classifier services.
- [ ] Verify green.

### Task 4: Execution Task and Metrics (#487)

**Files:**
- Create: `backend/app/services/replay/signal_source.py`
- Create: `backend/app/services/replay/metrics.py`
- Create: `backend/app/tasks/replay.py`
- Modify: `backend/app/services/replay/__init__.py`
- Test: `backend/tests/services/test_replay_metrics.py`
- Test: `backend/tests/tasks/test_replay_task.py`

**Interfaces:**
- Produces `MetricsComputer.compute(run_id, db)` and Celery task `run_signal_replay`.
- API uses cached scalar metrics and `metrics` JSONB.

- [ ] Write failing metrics tests from a hand-computed trade ledger covering win/loss/flat trades, equity curve, quarter decay, holding-period decay, and regime breakdown.
- [ ] Write failing task tests for completed run persistence and benchmark/signal-source failure setting `status="failed"`.
- [ ] Implement signal source, metrics, and task orchestration.
- [ ] Verify green.

### Task 5: REST API (#488)

**Files:**
- Create: `backend/app/schemas/replay.py`
- Create: `backend/app/routers/replay.py`
- Modify: `backend/app/routers/__init__.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/api/test_replay.py`

**Interfaces:**
- Produces `/api/v1/replay/runs`, `/runs/{uuid}`, `/runs/{uuid}/trades`, `/runs/{uuid}/analytics`, `/runs/compare`.
- Frontend consumes these endpoints.

- [ ] Write failing API tests for create/list/get/trades/analytics/compare, malformed UUIDs, unknown runs, and compare count limits.
- [ ] Implement schemas and router using the existing backtest router style.
- [ ] Verify green.

### Task 6: Frontend Replay Page (#489, #490)

**Files:**
- Create: `frontend/src/api/replay.ts`
- Create: `frontend/src/pages/Replay/index.tsx`
- Create: `frontend/src/pages/Replay/RunCreateForm.tsx`
- Create: `frontend/src/pages/Replay/RunSummaryPanel.tsx`
- Create: `frontend/src/pages/Replay/AnalyticsPanel.tsx`
- Create: `frontend/src/utils/replayChartOverlays.ts`
- Modify: `frontend/src/components/ui/StockChart.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout.tsx`
- Test: `frontend/src/utils/replayChartOverlays.test.ts`

**Interfaces:**
- Consumes replay API types from `frontend/src/api/replay.ts`.
- Extends `StockChart` with optional `replayMarkers` and `priceLines`.

- [ ] Write failing utility tests for replay chart overlays.
- [ ] Implement typed API client.
- [ ] Implement run creation, polling, completed run analytics, trade table, chart modal, and comparison mode.
- [ ] Add route and navigation entry.
- [ ] Verify with `npx tsc --noEmit -p tsconfig.app.json` and targeted Vitest.

### Task 7: Integration Verification and Issue Closure

**Files:**
- No new source files expected.

- [ ] Run targeted backend replay tests.
- [ ] Run frontend type-check and targeted Vitest.
- [ ] Run Alembic upgrade head against a reachable database or document blocker.
- [ ] Start the dev/demo stack if feasible and browser-check `/replay`.
- [ ] Update/close #484-#490 and #483 according to actual completion state.
- [ ] Commit, push `codex/epic-483-replay-engine`, and open a PR.
