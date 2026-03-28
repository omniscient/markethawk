"""
Routers package.
"""

from app.routers.health import router as health_router
from app.routers.scanner import router as scanner_router
from app.routers.universe import router as universe_router
from app.routers.stocks import router as stocks_router
from app.routers.news import router as news_router
from app.routers.live_data import router as live_data_router

__all__ = [
    "health_router",
    "scanner_router",
    "universe_router",
    "stocks_router",
    "news_router",
    "live_data_router",
]
