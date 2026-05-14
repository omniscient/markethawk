# Statistical Discovery Engine — Phase 2b

**Date**: 2026-05-14
**Status**: Pending Review
**Issue**: #22 feat(phase-2b): Statistical discovery engine

## Problem

MarketHawk's Scanner Scorecard (Phase 2a) now captures post-signal price outcomes for every event, producing a growing backtest dataset of (signal features × interval returns). However, this data is not being used to answer the core product question: **which features actually predict subsequent returns, and under what conditions?**

Without a discovery phase, Phase 2c's signal ranker would be built on intuition rather than evidence. This spec defines the statistical analysis pipeline that turns the outcome dataset into actionable findings: correlation rankings, SHAP-backed feature importances, and cluster archetypes that name the conditions under which signals outperform.

## Requirements

Distilled from the GitHub issue and Q&A:

- `analyze_signal_features()` Celery task runs on demand (via API) and nightly (Beat schedule)
- Task analyzes only events with `ScannerOutcomeSummary.is_complete = True`, using `ScannerOutcomeSnapshot.pct_change` per `interval_key` as the return target
- Correlation analysis: compute both Pearson and Spearman correlation for each feature × interval pair
- Feature importance: fit a LightGBM regressor per interval, extract SHAP values to rank features
- Cluster analysis: K-means on the flattened feature vector; assign each analyzed event to a cluster
- Cluster archetypes stored in a new `SignalCluster` table; assignments backfilled onto `ScannerEvent`
- Conditional statistics (median return, win rate, Sharpe, sample size) stored per cluster
- `GET /api/outcomes/correlations` endpoint returns the correlation matrix for EdgeExplorer
- `GET /api/outcomes/analysis/latest` endpoint returns the feature weight table as JSON (Phase 2c input)
- `POST /api/outcomes/analyze` triggers on-demand analysis and returns `{"task_id": "..."}`
- New `CorrelationHeatmap` component added to EdgeExplorer as a new section (no new charting library)
- New dependencies: `lightgbm`, `shap` added to `backend/requirements.txt`
- Alembic migration for all new tables and columns

## Data Model

### SignalAnalysisRun

Anchor table for each analysis execution. Stores the correlation matrix and SHAP feature weights as JSONB, so the API can serve them without re-running analysis.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | Integer PK | Auto-increment |
| `scanner_type` | String(50), nullable | Filter applied; NULL = all scanner types |
| `status` | String(20) | `pending`, `running`, `completed`, `failed` |
| `event_count` | Integer | Number of complete events analyzed |
| `correlation_matrix` | JSONB | `{features: [...], intervals: [...], pearson: [[...]], spearman: [[...]]}` |
| `feature_weights` | JSONB | `[{feature, interval, shap_importance, rank}]` ordered by importance |
| `celery_task_id` | String(255), nullable | For status polling |
| `error_message` | Text, nullable | Populated on failure |
| `created_at` | DateTime | UTC timestamp |
| `completed_at` | DateTime, nullable | Set when status → completed/failed |

**Index**: `(created_at DESC)` for latest-by-default queries.

### SignalCluster

One row per cluster archetype produced by a single analysis run.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | Integer PK | Auto-increment |
| `analysis_run_id` | FK → signal_analysis_runs.id | Parent run |
| `cluster_index` | Integer | 0-based cluster number from K-means |
| `label` | String(200) | Auto-generated human label (see below) |
| `centroid` | JSONB | `{feature_name: centroid_value, ...}` — mean feature values for this cluster |
| `return_profile` | JSONB | `{interval: {median_pct, win_rate, sharpe, n}, ...}` — conditional stats per interval |
| `event_count` | Integer | Number of events assigned to this cluster |
| `created_at` | DateTime | UTC |

**Index**: `(analysis_run_id)`.

**Label generation**: Auto-generated from the top 2 features with the highest absolute centroid deviation from the global mean, e.g. `"high volume_anomaly_score + risk_on context"`. Labels are overridable by operators in a future iteration (out of scope here).

### ScannerEvent — new column

Add `signal_cluster_id = Column(Integer, ForeignKey("signal_clusters.id"), nullable=True, index=True)` to `backend/app/models/scanner_event.py`. Nullable because events pre-dating the first analysis run have no assignment.

## Architecture

### StatisticalDiscoveryService

New service at `backend/app/services/statistical_discovery.py`. All CPU-intensive work happens inside the Celery task; the service provides the pure-Python computation methods.

```
StatisticalDiscoveryService
  ├── build_feature_matrix(events) → pd.DataFrame
  │     Flattens ScannerEvent.indicators JSONB into columns.
  │     Drops rows where > 50% of feature values are NULL.
  │     Returns one row per (event_id, interval_key) with feature columns + pct_change target.
  │
  ├── compute_correlations(df) → CorrelationResult
  │     Pearson and Spearman r per (feature × interval_key) using scipy.stats.
  │     Returns matrix suitable for direct JSON serialisation.
  │
  ├── compute_shap_weights(df) → list[FeatureWeight]
  │     For each interval_key:
  │       - Fit LightGBM LGBMRegressor(n_estimators=100, max_depth=4)
  │       - Compute SHAP values via shap.TreeExplainer
  │       - Mean |SHAP| per feature = importance score
  │     Returns list sorted by importance desc, tagged with interval.
  │
  ├── run_kmeans(df, k=6) → ClusterAssignment
  │     Fits sklearn KMeans on standardised feature vectors (StandardScaler).
  │     Returns cluster labels per event_id and cluster centroids.
  │     k defaults to 6; exposed as a task parameter for tuning.
  │
  └── compute_conditional_stats(df, cluster_labels) → dict[int, dict]
        For each cluster × interval: median pct_change, win_rate (pct_change > 0),
        Sharpe (mean/std of pct_change), sample size n.
```

**Note on scipy**: `scipy.stats` (needed for Spearman) should be added to `requirements.txt` alongside `lightgbm` and `shap`. `scikit-learn` is needed for `KMeans` and `StandardScaler`.

**Revised dependency list**: `lightgbm`, `shap`, `scikit-learn`, `scipy` — all new additions to `backend/requirements.txt`.

### analyze_signal_features Celery Task

```
app/tasks.py → analyze_signal_features(scanner_type=None, k=6)

1. Create SignalAnalysisRun(status='running', scanner_type=scanner_type)
2. Query:
     SELECT se.*, sos.pct_change, sos.interval_key
     FROM scanner_events se
     JOIN scanner_outcome_summaries sum ON sum.scanner_event_id = se.id
       AND sum.is_complete = TRUE
     JOIN scanner_outcome_snapshots sos ON sos.scanner_event_id = se.id
       AND sos.status = 'captured'
     WHERE (se.scanner_type = scanner_type OR scanner_type IS NULL)
3. If len(events) < 500: mark run failed with message "Insufficient data (n=X, min=500)", exit
4. StatisticalDiscoveryService.build_feature_matrix(events) → df
5. StatisticalDiscoveryService.compute_correlations(df) → save to run.correlation_matrix
6. StatisticalDiscoveryService.compute_shap_weights(df) → save to run.feature_weights
7. StatisticalDiscoveryService.run_kmeans(df, k) → cluster_labels, centroids
8. StatisticalDiscoveryService.compute_conditional_stats(df, cluster_labels) → conditional_stats
9. For each cluster index:
     - auto_label = generate_label(centroids[i], global_mean)
     - Create SignalCluster(analysis_run_id=run.id, cluster_index=i, label=auto_label,
                            centroid=centroids[i], return_profile=conditional_stats[i],
                            event_count=count)
10. Bulk-update ScannerEvent.signal_cluster_id for all analyzed event IDs
11. Set run.status = 'completed', run.completed_at = now(), run.event_count = n
```

**Task signature**: `@celery_app.task(bind=True, max_retries=1, name='app.tasks.analyze_signal_features')`

**Beat schedule** (add to `celery_app.py`):
```python
'analyze-signal-features-nightly': {
    'task': 'app.tasks.analyze_signal_features',
    'schedule': crontab(minute='0', hour='11', day_of_week='1-5'),
},
```
11:00 UTC = 6:00 AM ET / 7:00 AM EDT — after overnight outcome capture settles, before the pre-market scan window opens.

## API Endpoints

All new endpoints added to `backend/app/routers/outcomes.py` (existing router, prefix `/api/outcomes`).

### POST /api/outcomes/analyze

Triggers on-demand analysis. Returns 202 immediately.

```python
@router.post("/analyze", status_code=202)
async def trigger_signal_analysis(
    scanner_type: str | None = None,
    k: int = 6,
    db: AsyncSession = Depends(get_db)
):
    result = analyze_signal_features.delay(scanner_type=scanner_type, k=k)
    return {"task_id": result.id}
```

### GET /api/outcomes/correlations

Returns the correlation matrix from the most recent completed analysis run.

**Query params**: `scanner_type` (optional filter), `interval` (optional, filters columns returned)

**Response**:
```json
{
  "run_id": 7,
  "scanner_type": null,
  "event_count": 4823,
  "completed_at": "2026-05-14T11:04:22Z",
  "features": ["gap_pct", "relative_volume", "fade_from_high_pct", "day_range_pct"],
  "intervals": ["1h", "4h", "eod", "1d", "2d", "5d"],
  "pearson": [[0.12, 0.18, 0.21, 0.19, 0.16, 0.14], ...],
  "spearman": [[0.15, 0.22, 0.25, 0.21, 0.18, 0.15], ...]
}
```

Returns 404 if no completed analysis run exists.

### GET /api/outcomes/analysis/latest

Returns the feature weight table and cluster report from the most recent completed run. This is the primary JSON artifact consumed by Phase 2c.

**Response**:
```json
{
  "run_id": 7,
  "completed_at": "2026-05-14T11:04:22Z",
  "feature_weights": [
    {"feature": "relative_volume", "interval": "1h", "shap_importance": 0.034, "rank": 1},
    {"feature": "gap_pct", "interval": "4h", "shap_importance": 0.028, "rank": 2}
  ],
  "clusters": [
    {
      "id": 12,
      "label": "high relative_volume + risk_on context",
      "event_count": 847,
      "centroid": {"relative_volume": 4.2, "gap_pct": 2.1, ...},
      "return_profile": {
        "1h":  {"median_pct": 0.8, "win_rate": 0.58, "sharpe": 0.9, "n": 847},
        "4h":  {"median_pct": 1.4, "win_rate": 0.62, "sharpe": 1.1, "n": 847},
        "eod": {"median_pct": 2.1, "win_rate": 0.64, "sharpe": 1.3, "n": 847}
      }
    }
  ]
}
```

Returns 404 if no completed analysis run exists.

## Frontend

### CorrelationHeatmap Component

New file: `frontend/src/components/CorrelationHeatmap.tsx`

Renders a `<table>` with rows = features, columns = intervals, cells = correlation coefficient (Pearson or Spearman, toggled by a button). Cell `backgroundColor` is interpolated linearly: `r = -1` → red `#EF4444`, `r = 0` → dark gray `#374151`, `r = 1` → green `#10B981`. Cell text shows the rounded value (e.g. `0.72`).

Props: `data: CorrelationResponse`, `mode: 'pearson' | 'spearman'`

### EdgeExplorer Integration

Add a new `Card` section at the bottom of `frontend/src/pages/EdgeExplorer.tsx`:

- Section title: **"Feature Correlations"**
- Fetches `GET /api/outcomes/correlations?scanner_type={scannerType}` via React Query (reuses existing `scannerType` state)
- Renders `<CorrelationHeatmap>` with Pearson/Spearman toggle
- Shows a "Run Analysis" button that `POST /api/outcomes/analyze` — displays task_id confirmation toast
- Loading/empty state: "No analysis data yet. Run analysis to populate this panel."

No new route, no new charting libraries, no new npm packages.

## Scope

### In scope

- New models: `SignalAnalysisRun`, `SignalCluster`
- New column: `ScannerEvent.signal_cluster_id`
- New service: `StatisticalDiscoveryService`
- New Celery task: `analyze_signal_features`
- Beat schedule entry: `analyze-signal-features-nightly`
- New API endpoints: `POST /api/outcomes/analyze`, `GET /api/outcomes/correlations`, `GET /api/outcomes/analysis/latest`
- New frontend component: `CorrelationHeatmap.tsx`
- New EdgeExplorer section (Feature Correlations card)
- New dependencies: `lightgbm`, `shap`, `scikit-learn`, `scipy` in `requirements.txt`
- Alembic migration for all new tables and columns

### Out of scope

- Cluster label editing by operators
- Configurable k (exposed as API param; UI tuning deferred)
- Phase 2c ranker implementation
- Dashboard widget for cluster summary
- Per-ticker correlation drill-down
- Storing historical analysis run comparison (only latest is surfaced)

## Alternatives Considered

### A. scikit-learn RandomForest instead of LightGBM + SHAP

**Pro**: One package instead of two; simpler install.
**Con**: RandomForest's built-in `feature_importances_` (impurity-based) are less reliable than SHAP TreeExplainer values and prone to bias toward high-cardinality features. Since neither scikit-learn nor lightgbm is currently installed, there is no cost advantage. The issue explicitly requires SHAP.

**Rejected**: LightGBM + SHAP as specified.

### B. DBSCAN instead of K-means for clustering

**Pro**: Discovers cluster count automatically; handles non-spherical clusters.
**Con**: Requires tuning `epsilon` and `min_samples` parameters that have no obvious defaults for this feature space. Hard to reproduce across runs. The "labelled archetypes" requirement implies a fixed, navigable set of clusters — K-means with k=6 (tunable) is simpler to reason about.

**Rejected**: K-means as default.

### C. Compute correlations on-the-fly in the API endpoint (no pre-computation)

**Pro**: Always reflects the latest data.
**Con**: Joining 5,000+ events × 6 intervals × N features and computing correlation matrices on every request would make the endpoint too slow for interactive use. The analysis is scheduled nightly — staleness of up to 24 hours is acceptable for a discovery phase.

**Rejected**: Pre-compute in task, serve from `SignalAnalysisRun.correlation_matrix`.

## Assumptions

- **Phase 2a complete**: `ScannerOutcomeSnapshot` and `ScannerOutcomeSummary` tables exist and are being populated. At least 500 events with `is_complete = True` are required before the task will run analysis.
- **JSONB feature keys are stable**: `ScannerEvent.indicators` keys (`gap_pct`, `relative_volume`, `fade_from_high_pct`, `day_range_pct`, etc.) are consistent enough across scanner types to build a shared feature matrix. Mixed-type indicators (strings, booleans) are coerced to float or dropped in `build_feature_matrix()`.
- **k=6 is a reasonable default**: The issue does not specify a cluster count. 6 gives enough granularity to surface meaningful archetypes without fragmenting small datasets. Exposed as an API param so operators can adjust without a code change.
- **scipy is acceptable**: `scipy.stats.spearmanr` is the standard implementation. If scipy is already present as a transitive dependency of another package, no new install cost is incurred.

## Open Questions

- Should `GET /api/outcomes/analysis/latest` support a `run_id` param for historical lookups? (Deferred to Phase 2c — only latest needed now.)
- Should the Beat task skip runs when the live scanner is active (market open)? The 11:00 UTC schedule is before market open; collision seems unlikely but could be guarded with a Redis lock if needed.
