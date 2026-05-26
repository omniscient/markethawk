import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=0, name='app.tasks.analyze_universe_quality')
def analyze_universe_quality(self, universe_id: int):
    """
    Run a full data-quality analysis for a universe and persist the result.
    """
    from app.models.universe_quality_report import UniverseQualityReport
    from app.services.data_quality import DataQualityService

    db: Session = SessionLocal()
    try:
        logger.info(f"🔍 Starting quality analysis for universe {universe_id}")

        # Mark as running
        report = db.query(UniverseQualityReport).filter(
            UniverseQualityReport.universe_id == universe_id
        ).first()
        if not report:
            report = UniverseQualityReport(universe_id=universe_id)
            db.add(report)
        report.status = "running"
        report.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
        report.error_message = None
        db.commit()

        result = DataQualityService.analyze_universe(db, universe_id)

        report.status = "complete"
        report.overall_grade = result["overall_grade"]
        report.overall_score = result["overall_score"]
        report.ticker_count = result["ticker_count"]
        report.generated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        report.report_data = result
        db.commit()

        logger.info(
            f"✅ Quality analysis complete for universe {universe_id}: "
            f"grade={result['overall_grade']} score={result['overall_score']}"
        )

    except Exception as e:
        logger.error(f"❌ Quality analysis failed for universe {universe_id}: {e}")
        try:
            report = db.query(UniverseQualityReport).filter(
                UniverseQualityReport.universe_id == universe_id
            ).first()
            if report:
                report.status = "error"
                report.error_message = str(e)
                db.commit()
        except Exception:
            pass
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=0, name='app.tasks.normalize_universe_quality')
def normalize_universe_quality(self, universe_id: int, resume: bool = False, target_tickers: list = None):
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
        logger.info(f"🔧 Starting normalization for universe {universe_id} (resume={resume})")

        report = db.query(UniverseQualityReport).filter(
            UniverseQualityReport.universe_id == universe_id
        ).first()

        if not report or not report.report_data:
            logger.error(f"No quality report found for universe {universe_id}. Run analysis first.")
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
        report = db.query(UniverseQualityReport).filter(
            UniverseQualityReport.universe_id == universe_id
        ).first()
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
            report = db.query(UniverseQualityReport).filter(
                UniverseQualityReport.universe_id == universe_id
            ).first()
            if report:
                report.normalization_status = "error"
                existing = dict(report.normalization_data) if report.normalization_data else {}
                existing["error"] = str(e)
                report.normalization_data = existing
                db.commit()
        except Exception:
            pass
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=1, name='app.tasks.analyze_signal_features')
def analyze_signal_features(self, scanner_type: str | None = None, k: int = 6):
    import pandas as pd
    from app.models.scanner_event import ScannerEvent
    from app.models.signal_analysis_run import SignalAnalysisRun
    from app.models.signal_cluster import SignalCluster
    from app.models.scanner_outcome_summary import ScannerOutcomeSummary
    from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot
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
            run.error_message = f"Insufficient data (n={len(unique_event_ids)} events, min=500)"
            db.commit()
            logger.info("analyze_signal_features: insufficient data (%d events)", len(unique_event_ids))
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
            c for c in df.columns
            if c not in {"event_id", "interval_key", "pct_change"}
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
        run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        logger.info("analyze_signal_features: completed (events=%d)", len(unique_event_ids))

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
