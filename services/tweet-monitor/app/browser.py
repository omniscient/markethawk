"""
BrowserManager: persistent Playwright Chromium browser with cookie-based X auth.

Restart conditions:
- Health check failure (blank page / timeout)
- Session age > BROWSER_MAX_AGE_MINUTES
- Memory usage > BROWSER_MAX_MEMORY_MB
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import psutil
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

from app.config import settings

logger = logging.getLogger(__name__)

_HEALTH_CHECK_URL = "https://x.com"
_HEALTH_CHECK_SELECTOR = "body"
_HEALTH_CHECK_TIMEOUT_MS = 5_000


class BrowserManager:
    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._started_at: Optional[datetime] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            await self._launch()

    async def stop(self) -> None:
        async with self._lock:
            await self._close()

    async def _launch(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        await self._inject_cookies()
        self._started_at = datetime.now(timezone.utc)
        logger.info("Browser launched")

    async def _inject_cookies(self) -> None:
        if not settings.x_auth_token or not settings.x_csrf_token:
            logger.warning("X_AUTH_TOKEN or X_CSRF_TOKEN not set — scraping as unauthenticated")
            return
        await self._context.add_cookies([
            {
                "name": "auth_token",
                "value": settings.x_auth_token,
                "domain": ".x.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
            },
            {
                "name": "ct0",
                "value": settings.x_csrf_token,
                "domain": ".x.com",
                "path": "/",
                "secure": True,
                "httpOnly": False,
            },
        ])

    async def _close(self) -> None:
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:
            logger.warning(f"Error closing browser: {exc}")
        finally:
            self._context = None
            self._browser = None
            self._playwright = None
            self._started_at = None

    async def new_page(self) -> Page:
        """Return a new page from the persistent context, restarting if needed."""
        await self._ensure_healthy()
        return await self._context.new_page()

    async def _ensure_healthy(self) -> None:
        async with self._lock:
            if not self._context:
                logger.info("Browser not running — launching")
                await self._launch()
                return

            if self._should_restart_age():
                logger.info("Browser max age exceeded — restarting")
                await self._close()
                await self._launch()
                return

            if self._should_restart_memory():
                logger.info("Browser memory limit exceeded — restarting")
                await self._close()
                await self._launch()
                return

            if not await self._health_check():
                logger.warning("Browser health check failed — restarting")
                await self._close()
                await self._launch()

    def _should_restart_age(self) -> bool:
        if not self._started_at:
            return True
        age_minutes = (datetime.now(timezone.utc) - self._started_at).total_seconds() / 60
        return age_minutes >= settings.browser_max_age_minutes

    def _should_restart_memory(self) -> bool:
        try:
            current_process = psutil.Process()
            rss_mb = current_process.memory_info().rss / (1024 * 1024)
            return rss_mb >= settings.browser_max_memory_mb
        except Exception:
            return False

    async def _health_check(self) -> bool:
        try:
            page = await self._context.new_page()
            try:
                await page.goto(_HEALTH_CHECK_URL, timeout=_HEALTH_CHECK_TIMEOUT_MS)
                await page.wait_for_selector(_HEALTH_CHECK_SELECTOR, timeout=_HEALTH_CHECK_TIMEOUT_MS)
                return True
            finally:
                await page.close()
        except Exception as exc:
            logger.warning(f"Health check failed: {exc}")
            return False

    @property
    def age_seconds(self) -> float:
        if not self._started_at:
            return 0.0
        return (datetime.now(timezone.utc) - self._started_at).total_seconds()

    @property
    def is_running(self) -> bool:
        return self._context is not None


browser_manager = BrowserManager()
