from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "stockscanner",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=['app.tasks']
)

celery_app.conf.beat_schedule = {
    'poll-news-every-5-minutes': {
        'task': 'app.tasks.poll_massive_news',
        'schedule': 60.0,
    },
}
