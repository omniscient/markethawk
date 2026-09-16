import logging
import time as _time
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.metrics import (
    aggregate_gap_days,
    aggregate_staleness_hours,
    celery_task_duration_seconds,
    celery_tasks_total,
)
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

# Fallback defaults for quality thresholds (overridable via SystemConfig)
_DEFAULT_STALENESS_HOURS = 48
_DEFAULT_GAP_MIN_WEEKDAYS = 2
_DEFAULT_ALERT_PCT = 20


def _load_quality_thresholds(db: Session) -> tuple[int, int, int]:
    """Return (staleness_hours, gap_min_weekdays, alert_pct) from SystemConfig with fallbacks."""
    from app.models.system_config import SystemConfig

    keys = ["quality_staleness_hours", "quality_gap_min_weekdays", "quality_alert_pct"]
    rows = db.query(SystemConfig).filter(SystemConfig.key.in_(keys)).all()
    cfg = {r.key: r.value for r in rows}

    try:
        staleness_hours = int(
            cfg.get("quality_staleness_hours", _DEFAULT_STALENESS_HOURS)
        )
    except (ValueError, TypeError):
        staleness_hours = _DEFAULT_STALENESS_HOURS

    try:
        gap_min_weekdays = int(
            cfg.get("quality_gap_min_weekdays", _DEFAULT_GAP_MIN_WEEKDAYS)
        )
    except (ValueError, TypeError):
        gap_min_weekdays = _DEFAULT_GAP_MIN_WEEKDAYS

    try:
        alert_pct = int(cfg.get("quality_alert_pct", _DEFAULT_ALERT_PCT))
    except (ValueError, TypeError):
        alert_pct = _DEFAULT_ALERT_PCT

    return staleness_hours, gap_min_weekdays, alert_pct


def compute_universe_data_health(db: Session, universe_id: int) -> dict:
    """
    Lightweight health sweep for a single universe.

    Staleness: MAX(timestamp) per ticker (day/1 timespan).
    Gaps: universe-wide day holes — weekdays where far fewer tickers than
    usual have a day bar (a systemic sync outage signature).  Per-ticker gap
    counting is deliberately NOT used: on illiquid small-cap universes a
    missing day bar almost always means the stock didn't trade that day
    (verified against the provider), not that data is missing.

    Returns a summary dict with staleness/gap metrics.
    Does NOT write to UniverseQualityReport.
    """
    from app.models.market_holiday import MarketHoliday
    from app.models.stock_aggregate import StockAggregate
    from app.models.stock_universe_ticker import StockUniverseTicker
    from app.services.quality_helpers import _detect_universe_day_holes

    staleness_hours_threshold, _gap_min_weekdays, _ = _load_quality_thresholds(db)

    tickers = (
        db.query(StockUniverseTicker.ticker)
        .filter(StockUniverseTicker.universe_id == universe_id)
        .all()
    )
    ticker_list = [t.ticker for t in tickers]

    if not ticker_list:
        return {
            "ticker_count": 0,
            "stale_count": 0,
            "gapped_count": 0,
            "stale_pct": 0.0,
            "gapped_pct": 0.0,
            "worst_staleness_hours": 0.0,
            "worst_gap_days": 0.0,
            "degraded": False,
            "grade": "A",
        }

    now_utc = utc_now()
    stale_count = 0
    worst_staleness_hours = 0.0

    for ticker in ticker_list:
        # MAX(timestamp) staleness check — day bars only (lightweight)
        result = (
            db.query(func.max(StockAggregate.timestamp))
            .filter(
                StockAggregate.ticker == ticker,
                StockAggregate.timespan == "day",
                StockAggregate.multiplier == 1,
            )
            .scalar()
        )

        if not isinstance(result, datetime):
            # No day bars for this ticker — treat as maximally stale
            stale_count += 1
            worst_staleness_hours = max(worst_staleness_hours, float("inf"))
            continue

        staleness_h = (now_utc - result).total_seconds() / 3600
        worst_staleness_hours = max(worst_staleness_hours, staleness_h)
        if staleness_h > staleness_hours_threshold:
            stale_count += 1

    # ── Systemic day-hole detection (last 90 days) ────────────────────────────
    # The last 2 calendar days are excluded: bars not yet synced there are
    # staleness, already alarmed above, not a mid-history hole.
    window_start = (now_utc - timedelta(days=90)).date()
    window_end = (now_utc - timedelta(days=2)).date()

    day_count_rows = (
        db.query(
            func.date(StockAggregate.timestamp).label("d"),
            func.count(func.distinct(StockAggregate.ticker)).label("n"),
        )
        .filter(
            StockAggregate.ticker.in_(ticker_list),
            StockAggregate.timespan == "day",
            StockAggregate.multiplier == 1,
            StockAggregate.timestamp >= window_start,
        )
        .group_by(func.date(StockAggregate.timestamp))
        .all()
    )
    counts_by_day = {r.d: r.n for r in day_count_rows}

    holiday_rows = (
        db.query(MarketHoliday.date)
        .filter(
            MarketHoliday.exchange == "NYSE",
            MarketHoliday.event_type == "full_close",
            MarketHoliday.date >= window_start,
            MarketHoliday.date <= window_end,
        )
        .all()
    )
    holidays = {r.date for r in holiday_rows}

    holes = _detect_universe_day_holes(
        counts_by_day, window_start, window_end, holidays
    )

    trading_days_checked = sum(
        1
        for i in range((window_end - window_start).days + 1)
        if (window_start + timedelta(days=i)).weekday() < 5
        and (window_start + timedelta(days=i)) not in holidays
    )
    gapped_count = len(holes)

    # Longest run of consecutive hole trading-days
    worst_gap_days = 0.0
    run = 0
    prev_hole = None
    for hole in holes:
        if prev_hole is not None and (hole - prev_hole).days <= 3:
            run += 1
        else:
            run = 1
        worst_gap_days = max(worst_gap_days, float(run))
        prev_hole = hole

    n = len(ticker_list)
    stale_pct = round(stale_count / n * 100, 1) if n > 0 else 0.0
    gapped_pct = (
        round(gapped_count / trading_days_checked * 100, 1)
        if trading_days_checked > 0
        else 0.0
    )

    _, _, alert_pct = _load_quality_thresholds(db)
    degraded = stale_pct > alert_pct or gapped_pct > alert_pct

    # Grade: A if healthy, B if minor, C if degraded, D/F if severely degraded
    max_pct = max(stale_pct, gapped_pct)
    if max_pct == 0:
        grade = "A"
    elif max_pct <= 5:
        grade = "B"
    elif max_pct <= alert_pct:
        grade = "C"
    elif max_pct <= 50:
        grade = "D"
    else:
        grade = "F"

    return {
        "ticker_count": n,
        "stale_count": stale_count,
        "gapped_count": gapped_count,
        "stale_pct": stale_pct,
        "gapped_pct": gapped_pct,
        "worst_staleness_hours": round(worst_staleness_hours, 1)
        if worst_staleness_hours != float("inf")
        else 9999.0,
        "worst_gap_days": round(worst_gap_days, 1),
        "degraded": degraded,
        "grade": grade,
    }


@celery_app.task(bind=True, max_retries=0, name="app.tasks.analyze_universe_quality")
def analyze_universe_quality(self, universe_id: int):
    """
    Run a full data-quality analysis for a universe and persist the result.
    """
    from app.models.universe_quality_report import UniverseQualityReport
    from app.services.data_quality import DataQualityService

    _task_name = "analyze_universe_quality"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        logger.info(f"🔍 Starting quality analysis for universe {universe_id}")

        # Mark as running
        report = (
            db.query(UniverseQualityReport)
            .filter(UniverseQualityReport.universe_id == universe_id)
            .first()
        )
        if not report:
            report = UniverseQualityReport(universe_id=universe_id)
            db.add(report)
        report.status = "running"
        report.started_at = utc_now()
        report.error_message = None
        db.commit()

        result = DataQualityService.analyze_universe(db, universe_id)

        report.status = "complete"
        report.overall_grade = result["overall_grade"]
        report.overall_score = result["overall_score"]
        report.ticker_count = result["ticker_count"]
        report.generated_at = utc_now()
        report.report_data = result
        db.commit()

        logger.info(
            f"✅ Quality analysis complete for universe {universe_id}: "
            f"grade={result['overall_grade']} score={result['overall_score']}"
        )
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()

    except Exception as e:
        logger.error(f"❌ Quality analysis failed for universe {universe_id}: {e}")
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        try:
            report = (
                db.query(UniverseQualityReport)
                .filter(UniverseQualityReport.universe_id == universe_id)
                .first()
            )
            if report:
                report.status = "error"
                report.error_message = str(e)
                db.commit()
        except Exception:
            pass
        db.rollback()
        raise
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()


@celery_app.task(bind=True, max_retries=0, name="app.tasks.normalize_universe_quality")
def normalize_universe_quality(
    self, universe_id: int, resume: bool = False, target_tickers: list = None
):
    """
    Fix all data-quality issues for a universe so every ticker reaches an A grade.

    Fixes applied per ticker×timespan combo:
      1. Dedup duplicate timestamps
      2. Fill gaps detected by the quality analyser
      3. Back-fill stale tails to today

    The task is resumable: pass resume=True to continue from a previous
    interrupted run.  Progress is checkpointed after every combo.

    After all fixes are applied the quality analyser is re-run automatically
    so the report reflects the improvements.
    """
    from app.models.universe_quality_report import UniverseQualityReport
    from app.services.normalization import NormalizationService

    db: Session = SessionLocal()
    try:
        logger.info(
            f"🔧 Starting normalization for universe {universe_id} (resume={resume})"
        )

        report = (
            db.query(UniverseQualityReport)
            .filter(UniverseQualityReport.universe_id == universe_id)
            .first()
        )

        if not report or not report.report_data:
            logger.error(
                f"No quality report found for universe {universe_id}. Run analysis first."
            )
            raise RuntimeError("Quality analysis must be run before normalization.")

        # Load checkpoint for resume, or start fresh
        checkpoint = {}
        if resume and report.normalization_data:
            checkpoint = dict(report.normalization_data)
            logger.info(
                f"Resuming from checkpoint: "
                f"{len(checkpoint.get('processed_combos', []))} combos already done"
            )

        # Mark as running
        report.normalization_status = "running"
        report.normalization_data = {**checkpoint, "status": "running"}
        db.commit()

        quality_report = dict(report.report_data)

        final_data = NormalizationService.run(
            db=db,
            universe_id=universe_id,
            quality_report=quality_report,
            normalization_data=checkpoint,
            target_tickers=target_tickers,
        )

        # Save final state
        report = (
            db.query(UniverseQualityReport)
            .filter(UniverseQualityReport.universe_id == universe_id)
            .first()
        )
        report.normalization_status = "complete"
        report.normalization_data = final_data
        db.commit()

        logger.info(
            f"✅ Normalization complete for universe {universe_id}: "
            f"{final_data.get('fixes_applied')}"
        )

        # Automatically re-run quality analysis so the modal shows updated grades
        analyze_universe_quality.delay(universe_id)

    except Exception as e:
        logger.error(f"❌ Normalization failed for universe {universe_id}: {e}")
        try:
            report = (
                db.query(UniverseQualityReport)
                .filter(UniverseQualityReport.universe_id == universe_id)
                .first()
            )
            if report:
                report.normalization_status = "error"
                existing = (
                    dict(report.normalization_data) if report.normalization_data else {}
                )
                existing["error"] = str(e)
                report.normalization_data = existing
                db.commit()
        except Exception:
            pass
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=1, name="app.tasks.analyze_signal_features")
def analyze_signal_features(self, scanner_type: str | None = None, k: int = 6):
    import pandas as pd

    from app.models.scanner_event import ScannerEvent
    from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot
    from app.models.scanner_outcome_summary import ScannerOutcomeSummary
    from app.models.signal_analysis_run import SignalAnalysisRun
    from app.models.signal_cluster import SignalCluster
    from app.services.statistical_discovery import StatisticalDiscoveryService

    db: Session = SessionLocal()
    try:
        run = SignalAnalysisRun(
            status="running",
            scanner_type=scanner_type,
            celery_task_id=self.request.id,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        query = (
            db.query(
                ScannerEvent.id.label("event_id"),
                ScannerEvent.scanner_type,
                ScannerEvent.indicators,
                ScannerOutcomeSnapshot.interval_key,
                ScannerOutcomeSnapshot.pct_change,
            )
            .join(
                ScannerOutcomeSummary,
                ScannerOutcomeSummary.scanner_event_id == ScannerEvent.id,
            )
            .join(
                ScannerOutcomeSnapshot,
                ScannerOutcomeSnapshot.scanner_event_id == ScannerEvent.id,
            )
            .filter(
                ScannerOutcomeSummary.is_complete.is_(True),
                ScannerOutcomeSnapshot.status == "captured",
            )
        )
        if scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)

        rows = query.all()

        unique_event_ids = {r.event_id for r in rows}
        if len(unique_event_ids) < 500:
            run.status = "failed"
            run.error_message = (
                f"Insufficient data (n={len(unique_event_ids)} events, min=500)"
            )
            db.commit()
            logger.info(
                "analyze_signal_features: insufficient data (%d events)",
                len(unique_event_ids),
            )
            return

        flat_rows = []
        for r in rows:
            indicators = r.indicators or {}
            row = {
                "event_id": r.event_id,
                "interval_key": r.interval_key,
                "pct_change": float(r.pct_change) if r.pct_change is not None else None,
            }
            for k_feat, v in indicators.items():
                try:
                    row[k_feat] = float(v)
                except (TypeError, ValueError):
                    row[k_feat] = None
            flat_rows.append(row)

        raw_df = pd.DataFrame(flat_rows)
        svc = StatisticalDiscoveryService()
        df = svc.build_feature_matrix(raw_df)

        correlation_matrix = svc.compute_correlations(df)
        run.correlation_matrix = correlation_matrix

        feature_weights = svc.compute_shap_weights(df)
        run.feature_weights = feature_weights

        cluster_labels, centroids = svc.run_kmeans(df, k=k)
        conditional_stats = svc.compute_conditional_stats(df, cluster_labels)

        feature_cols = [
            c for c in df.columns if c not in {"event_id", "interval_key", "pct_change"}
        ]
        global_mean = {feat: float(df[feat].mean()) for feat in feature_cols}

        cluster_id_map: dict[int, int] = {}
        for cluster_idx, centroid in enumerate(centroids):
            label = svc.generate_label(centroid, global_mean)
            event_count = sum(1 for v in cluster_labels.values() if v == cluster_idx)
            cluster = SignalCluster(
                analysis_run_id=run.id,
                cluster_index=cluster_idx,
                label=label,
                centroid=centroid,
                return_profile=conditional_stats.get(cluster_idx, {}),
                event_count=event_count,
            )
            db.add(cluster)
            db.flush()
            cluster_id_map[cluster_idx] = cluster.id

        for event_id, cluster_idx in cluster_labels.items():
            db.query(ScannerEvent).filter(ScannerEvent.id == event_id).update(
                {"signal_cluster_id": cluster_id_map[cluster_idx]},
                synchronize_session=False,
            )

        run.status = "completed"
        run.event_count = len(unique_event_ids)
        run.completed_at = utc_now()
        db.commit()
        logger.info(
            "analyze_signal_features: completed (events=%d)", len(unique_event_ids)
        )

    except Exception as exc:
        logger.exception("analyze_signal_features failed: %s", exc)
        try:
            run.status = "failed"
            run.error_message = str(exc)
            db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=0, name="app.tasks.check_aggregate_staleness")
def check_aggregate_staleness(self):
    """
    Nightly lightweight sweep of all active universes for data staleness and gaps.

    Emits:
      - markethawk_aggregate_staleness_hours{universe_id} Prometheus gauge
      - markethawk_aggregate_gap_days{universe_id} Prometheus gauge
      - logger.warning Seq event when >quality_alert_pct% of tickers are stale/gapped
    """
    from app.models.stock_universe import StockUniverse

    _task_name = "check_aggregate_staleness"
    _start = _time.monotonic()
    db: Session = SessionLocal()
    try:
        logger.info("🔍 Starting nightly aggregate staleness/gap sweep")

        universes = (
            db.query(StockUniverse).filter(StockUniverse.is_active.is_(True)).all()
        )

        _, _, alert_pct = _load_quality_thresholds(db)
        total_universes = len(universes)
        degraded_universes = 0

        for universe in universes:
            try:
                health = compute_universe_data_health(db, universe.id)

                uid_str = str(universe.id)
                aggregate_staleness_hours.labels(universe_id=uid_str).set(
                    health["worst_staleness_hours"]
                )
                aggregate_gap_days.labels(universe_id=uid_str).set(
                    health["worst_gap_days"]
                )

                if health["degraded"]:
                    degraded_universes += 1
                    logger.warning(
                        "⚠️ Data quality degraded for universe %s (id=%s): "
                        "stale_pct=%.1f%% gapped_pct=%.1f%% "
                        "worst_staleness_hours=%.1f worst_gap_days=%.1f grade=%s",
                        universe.name,
                        universe.id,
                        health["stale_pct"],
                        health["gapped_pct"],
                        health["worst_staleness_hours"],
                        health["worst_gap_days"],
                        health["grade"],
                    )
                else:
                    logger.info(
                        "✅ Universe %s (id=%s) health OK: stale=%.1f%% gapped=%.1f%%",
                        universe.name,
                        universe.id,
                        health["stale_pct"],
                        health["gapped_pct"],
                    )

            except Exception as exc:
                logger.error(
                    "check_aggregate_staleness: error for universe %s: %s",
                    universe.id,
                    exc,
                )

        logger.info(
            "✅ Aggregate staleness sweep complete: %d/%d universes degraded",
            degraded_universes,
            total_universes,
        )
        celery_tasks_total.labels(task_name=_task_name, status="success").inc()

    except Exception as e:
        logger.error("❌ check_aggregate_staleness failed: %s", e)
        celery_tasks_total.labels(task_name=_task_name, status="failure").inc()
        raise
    finally:
        celery_task_duration_seconds.labels(task_name=_task_name).observe(
            _time.monotonic() - _start
        )
        db.close()
