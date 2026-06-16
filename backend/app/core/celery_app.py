import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import (
    after_setup_logger,
    after_setup_task_logger,
    worker_process_shutdown,
    worker_ready,
)

from app.core.config import settings

celery_app = Celery(
    "stockscanner",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks"],
)


@after_setup_logger.connect
@after_setup_task_logger.connect
def _install_log_redaction(logger, **kwargs):
    # Re-install after Celery resets the root logger, so secrets stay redacted
    # in worker/beat logs too (F-LOG-01).
    from app.core.log_filters import install_redacting_filter

    install_redacting_filter()

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)


@worker_ready.connect
def _on_worker_ready(sender, **kwargs):
    """Run startup validation when the Celery worker finishes booting."""
    from app.tasks.scanning import validate_scheduled_scanner_configs

    validate_scheduled_scanner_configs()


@worker_process_shutdown.connect
def _cleanup_prometheus_on_exit(sender, pid, exitcode, **kwargs):
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess

        multiprocess.mark_process_dead(pid)


# News polling runs weekdays only (Mon-Fri).
# The task itself enforces the precise 2 AM – 8 PM ET window.
celery_app.conf.beat_schedule = {
    "poll-news-weekdays": {
        "task": "app.tasks.poll_massive_news",
        "schedule": crontab(minute="*", hour="*", day_of_week="1-5"),
    },
    "sync-stock-splits-nightly": {
        "task": "app.tasks.sync_stock_splits",
        "schedule": crontab(minute="0", hour="1"),
    },
    # Auto-trade fill polling — every minute on weekdays during extended market hours
    # (4 AM – 8 PM ET = 9 AM – 1 AM UTC+1, simpler to just run 8-23 UTC Mon-Fri)
    # The task itself is a no-op when there are no submitted/open orders.
    "poll-auto-trade-fills": {
        "task": "app.tasks.poll_auto_trade_fills",
        "schedule": crontab(minute="*", hour="9-23", day_of_week="1-5"),
    },
    # Liquidity hunt scan: runs at 02:00 UTC Mon–Fri
    # After-market closes 20:00 ET; 02:00 UTC = 21:00 EST (winter) / 22:00 EDT (summer) — always post-close.
    "run-liquidity-hunt-scan-evening": {
        "task": "app.tasks.run_liquidity_hunt_scheduled",
        "schedule": crontab(minute="0", hour="2", day_of_week="1-5"),
    },
    # Pocket pivot scan: runs at 02:00 UTC Mon–Fri (same post-close slot as liquidity hunt)
    "run-pocket-pivot-scan-evening": {
        "task": "app.tasks.run_pocket_pivot_scheduled",
        "schedule": crontab(minute="0", hour="2", day_of_week="1-5"),
    },
    # Trend pullback scan: runs at 02:00 UTC Mon–Fri (same post-close slot as pocket pivot)
    "run-trend-pullback-scan-evening": {
        "task": "app.tasks.run_trend_pullback_scheduled",
        "schedule": crontab(minute="0", hour="2", day_of_week="1-5"),
    },
    "analyze-signal-features-nightly": {
        "task": "app.tasks.analyze_signal_features",
        "schedule": crontab(minute="0", hour="11", day_of_week="1-5"),
    },
    # Tweet monitor: trigger every 45 seconds (expires in 40s to prevent pile-up)
    "trigger-tweet-monitor": {
        "task": "app.tasks.trigger_tweet_monitor",
        "schedule": 45.0,
        "options": {"expires": 40},
    },
    # HMM regime retraining: 21:00 UTC weekdays (17:00 ET / 16:00 EDT — post market-close)
    "update-regime-model-nightly": {
        "task": "app.tasks.update_regime_model",
        "schedule": crontab(minute="0", hour="21", day_of_week="1-5"),
    },
}
