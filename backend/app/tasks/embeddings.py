import logging

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.news_article import NewsArticle
from app.models.scanner_event import ScannerEvent
from app.models.scanner_event_narrative import ScannerEventNarrative
from app.services.domain_embedding_service import DomainEmbeddingService

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.embed_news_article_source")
def embed_news_article_source(article_id: int) -> dict:
    db = SessionLocal()
    try:
        article = db.get(NewsArticle, article_id)
        if article is None:
            return {"status": "not_found", "source": "news", "id": article_id}
        result = DomainEmbeddingService().embed_news_article(db, article)
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        logger.exception("embed_news_article_source failed for article_id=%s", article_id)
        return {"status": "failed", "source": "news", "id": article_id, "error": str(exc)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.embed_scanner_event_sources")
def embed_scanner_event_sources(event_id: int) -> dict:
    db = SessionLocal()
    try:
        event = db.get(ScannerEvent, event_id)
        if event is None:
            return {"status": "not_found", "source": "scanner_event", "id": event_id}
        service = DomainEmbeddingService()
        result = {
            "catalyst": service.embed_scanner_catalyst(db, event),
            "signal_brief": service.embed_signal_brief(db, event),
        }
        db.commit()
        return {"status": "completed", "scanner_event_id": event_id, "results": result}
    except Exception as exc:
        db.rollback()
        logger.exception("embed_scanner_event_sources failed for event_id=%s", event_id)
        return {
            "status": "failed",
            "source": "scanner_event",
            "id": event_id,
            "error": str(exc),
        }
    finally:
        db.close()


@celery_app.task(name="app.tasks.embed_generated_narrative_source")
def embed_generated_narrative_source(narrative_id: int) -> dict:
    db = SessionLocal()
    try:
        narrative = db.get(ScannerEventNarrative, narrative_id)
        if narrative is None:
            return {
                "status": "not_found",
                "source": "generated_narrative",
                "id": narrative_id,
            }
        result = DomainEmbeddingService().embed_generated_narrative(db, narrative)
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        logger.exception(
            "embed_generated_narrative_source failed for narrative_id=%s",
            narrative_id,
        )
        return {
            "status": "failed",
            "source": "generated_narrative",
            "id": narrative_id,
            "error": str(exc),
        }
    finally:
        db.close()
