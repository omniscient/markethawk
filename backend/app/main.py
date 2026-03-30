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
from app.routers import health_router, scanner_router, universe_router, stocks_router, news_router, live_data_router, journal_router, system_router
from app.core.celery_app import celery_app as celery
from app.services.websocket_manager import websocket_manager

# Celery Configuration
# celery instance is imported from app.core.celery_app


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Centralized SQL Logging
    # Centralized SQL Logging
    if settings.LOG_LEVEL == "DEBUG":
        from sqlalchemy import event
        from sqlalchemy.engine import Engine
        import datetime

        @event.listens_for(Engine, "before_cursor_execute")
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            conn.info.setdefault('query_start_time', []).append(datetime.datetime.now())
            
            # Attempt to format the query for easier debugging (Copy/Paste to PGAdmin)
            # Note: This is a best-effort approximation for logging purposes.
            try:
                if parameters and not executemany:
                    # Handle clear substitution for simple cases
                    formatted_sql = statement
                    
                    if isinstance(parameters, dict):
                         # Handle %(name)s style
                         formatted_params = {}
                         for key, p in parameters.items():
                            if isinstance(p, str):
                                formatted_params[key] = f"'{p}'"
                            elif isinstance(p, (datetime.date, datetime.datetime)):
                                formatted_params[key] = f"'{p}'"
                            elif p is None:
                                formatted_params[key] = "NULL"
                            else:
                                formatted_params[key] = str(p)
                         formatted_sql = statement % formatted_params
                         
                    elif isinstance(parameters, (list, tuple)):
                        # Handle %s style
                        formatted_params = []
                        for p in parameters:
                            if isinstance(p, str):
                                formatted_params.append(f"'{p}'")
                            elif isinstance(p, (datetime.date, datetime.datetime)):
                                formatted_params.append(f"'{p}'")
                            elif p is None:
                                formatted_params.append("NULL")
                            else:
                                formatted_params.append(str(p))
                        formatted_sql = statement % tuple(formatted_params)
                    
                    logging.info(f"\n[DEBUG SQL]:\n{formatted_sql};\n")
                else:
                     # Fallback for executemany or no params
                     logging.info(f"\n[DEBUG SQL RAW]:\n{statement} \nParams: {parameters}\n")
            except Exception:
                # If formatting fails, just log raw
                logging.info(f"\n[DEBUG SQL RAW]:\n{statement} \nParams: {parameters}\n")

        logging.info("Advanced SQL Logging enabled (Copy-Paste friendly)")

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
    app.include_router(news_router)
    app.include_router(live_data_router)
    app.include_router(journal_router)
    app.include_router(system_router)

    # Startup event
    @app.on_event("startup")
    async def startup_event():
        """Initialize database tables."""
        try:
            Base.metadata.create_all(bind=engine)
            logging.info("Database tables initialized")
        except Exception as e:
            logging.error(f"Failed to initialize database tables: {e}")
            logging.warning("Application starting without verified DB connection")
        
        # Start Polygon WebSocket Manager
        websocket_manager.start()
        logging.info("Stock WebSocket Manager started")

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
