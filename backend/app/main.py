"""
Stock Scanner Backend API
FastAPI-based REST API for stock scanning and alert system
"""

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import engine, Base
from app.routers import health_router, scanner_router, universe_router, stocks_router
from app.core.celery_app import celery_app as celery

# Celery Configuration
# celery instance is imported from app.core.celery_app


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        description="Professional stock scanning and alert system",
        version=settings.APP_VERSION,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health_router)
    app.include_router(scanner_router)
    app.include_router(universe_router)
    app.include_router(stocks_router)

    # Startup event
    @app.on_event("startup")
    async def startup_event():
        """Initialize database tables."""
        Base.metadata.create_all(bind=engine)
        logging.info("Database tables initialized")

    # Shutdown event
    @app.on_event("shutdown")
    async def shutdown_event():
        """Cleanup resources."""
        engine.dispose()
        logging.info("Database connection closed")

    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
