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
}
