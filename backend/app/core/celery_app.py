from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

celery_app = Celery(
    "stockscanner",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=['app.tasks']
)

# News polling runs weekdays only (Mon-Fri).
# The task itself enforces the precise 2 AM – 8 PM ET window.
celery_app.conf.beat_schedule = {
    'poll-news-weekdays': {
        'task': 'app.tasks.poll_massive_news',
        'schedule': crontab(minute='*', hour='*', day_of_week='1-5'),
    },
    'sync-stock-splits-nightly': {
        'task': 'app.tasks.sync_stock_splits',
        'schedule': crontab(minute='0', hour='1'),
    },
    # Auto-trade fill polling — every minute on weekdays during extended market hours
    # (4 AM – 8 PM ET = 9 AM – 1 AM UTC+1, simpler to just run 8-23 UTC Mon-Fri)
    # The task itself is a no-op when there are no submitted/open orders.
    'poll-auto-trade-fills': {
        'task': 'app.tasks.poll_auto_trade_fills',
        'schedule': crontab(minute='*', hour='9-23', day_of_week='1-5'),
    },
    # Liquidity hunt scan: runs at 02:00 UTC Mon–Fri
    # After-market closes 20:00 ET; 02:00 UTC = 21:00 EST (winter) / 22:00 EDT (summer) — always post-close.
    'run-liquidity-hunt-scan-evening': {
        'task': 'app.tasks.run_liquidity_hunt_scheduled',
        'schedule': crontab(minute='0', hour='2', day_of_week='1-5'),
    },
}
