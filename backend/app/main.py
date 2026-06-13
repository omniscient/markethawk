"""
Stock Scanner Backend API
FastAPI-based REST API for stock scanning and alert system
"""

import asyncio
import hashlib
import logging
import os
import time as _time
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from prometheus_client import REGISTRY, CollectorRegistry, generate_latest
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware

from app.core.config import get_settings, settings
from app.core.database import engine
from app.core.error_tracking import ErrorTrackerFactory
from app.core.rate_limits import limiter
from app.core.tracing import OtelTraceIdFilter, instrument_fastapi, setup_otel
from app.exceptions import MarketHawkError
from app.routers import (
    alerts_router,
    auth_router,
    auto_trading_router,
    futures_router,
    health_router,
    journal_router,
    live_data_router,
    news_router,
    outcomes_router,
    scanner_router,
    stocks_router,
    system_router,
    universe_router,
    watchlist_router,
)
from app.routers.tweets import router as tweets_router
from app.services.websocket_manager import websocket_manager

# CSRF header check — module-level so it is importable by the test suite without
# triggering the full create_app() factory. Pure ASGI (not BaseHTTPMiddleware) to
# avoid the chunked-gzip termination bug described at the AuthMiddleware comment below.
CSRF_EXEMPT_PREFIXES = ("/api/auth/",)
CSRF_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CSRFMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "")
        if method not in CSRF_MUTATING_METHODS:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if any(path.startswith(p) for p in CSRF_EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        if b"x-requested-with" not in headers:
            await JSONResponse(
                status_code=403,
                content={
                    "detail": "CSRF check failed: X-Requested-With header required"
                },
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)


# Celery Configuration
# celery instance is imported from app.core.celery_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic for the FastAPI application."""
    # --- Startup ---
    import redis.asyncio as aioredis

    from app.core.database import SessionLocal
    from app.models.universe_quality_report import UniverseQualityReport

    try:
        db = SessionLocal()
        try:
            reports = (
                db.query(UniverseQualityReport)
                .filter(
                    (UniverseQualityReport.status.in_(["pending", "running"]))
                    | (
                        UniverseQualityReport.normalization_status.in_(
                            ["pending", "running"]
                        )
                    )
                )
                .all()
            )
            for report in reports:
                if report.status in ["pending", "running"]:
                    report.status = "error"
                    report.error_message = "Process interrupted by server restart."
                if report.normalization_status in ["pending", "running"]:
                    report.normalization_status = "error"
            if reports:
                db.commit()
                logging.info(
                    f"Reset {len(reports)} orphaned quality reports to error state."
                )
        except Exception as dbe:
            logging.error(f"Error resetting orphaned DB tasks: {dbe}")
        finally:
            db.close()
    except Exception as e:
        logging.error(f"Failed to initialize database tables: {e}")
        logging.warning("Application starting without verified DB connection")

    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        cursor = "0"
        keys_deleted = 0
        while True:
            cursor, keys = await r.scan(
                cursor=cursor, match="universe:*:sync", count=100
            )
            if keys:
                await r.delete(*keys)
                keys_deleted += len(keys)
            if cursor == 0 or cursor == "0" or str(cursor) == "0":
                break
        if keys_deleted > 0:
            logging.info(
                f"Cleared {keys_deleted} orphaned sync tracking keys from Redis."
            )
        await r.close()
    except Exception as re:
        logging.error(f"Failed to clean up Redis sync keys on startup: {re}")

    websocket_manager.start()
    logging.info("Stock WebSocket Manager started")

    from app.core.metrics import db_pool_checked_out, db_pool_overflow, db_pool_size

    async def _update_pool_metrics():
        while True:
            try:
                pool = engine.pool
                db_pool_size.set(pool.size())
                db_pool_checked_out.set(pool.checkedout())
                db_pool_overflow.set(pool.overflow())
            except Exception:
                pass
            await asyncio.sleep(15)

    _pool_task = asyncio.create_task(_update_pool_metrics())
    logging.info("DB pool metrics background task started")

    yield

    # --- Shutdown ---
    _pool_task.cancel()
    engine.dispose()
    logging.info("Database connection closed")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger().addFilter(OtelTraceIdFilter())

    # Centralized SQL Logging
    # Centralized SQL Logging
    if settings.LOG_LEVEL == "DEBUG":
        import datetime

        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        @event.listens_for(Engine, "before_cursor_execute")
        def before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            conn.info.setdefault("query_start_time", []).append(
                datetime.datetime.now(datetime.timezone.utc)
            )

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
                    logging.info(
                        f"\n[DEBUG SQL RAW]:\n{statement} \nParams: {parameters}\n"
                    )
            except Exception:
                # If formatting fails, just log raw
                logging.info(
                    f"\n[DEBUG SQL RAW]:\n{statement} \nParams: {parameters}\n"
                )

        logging.info("Advanced SQL Logging enabled (Copy-Paste friendly)")

    _docs_url = "/docs" if settings.DOCS_ENABLED else None
    _redoc_url = "/redoc" if settings.DOCS_ENABLED else None
    _openapi_url = "/openapi.json" if settings.DOCS_ENABLED else None

    app = FastAPI(
        title=settings.APP_NAME,
        description="Professional stock scanning and alert system",
        version=settings.APP_VERSION,
        lifespan=lifespan,
        docs_url=_docs_url,
        redoc_url=_redoc_url,
        openapi_url=_openapi_url,
    )

    setup_otel(
        endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
        service_name=settings.OTEL_SERVICE_NAME,
        engine=engine,
    )
    instrument_fastapi(app)

    _base_exempt = (
        "/api/auth/",
        "/api/health",
        "/api/ready",
        "/metrics",
        "/api/alerts/infrastructure",
    )
    _doc_prefixes = ("/docs", "/redoc", "/openapi.json")
    EXEMPT_PREFIXES = _base_exempt + (_doc_prefixes if settings.DOCS_ENABLED else ())

    # Pure ASGI auth middleware (deliberately NOT BaseHTTPMiddleware). BaseHTTPMiddleware
    # re-emits every response as a stream, which forces GZipMiddleware into chunked mode;
    # under starlette 1.0.0 that chunked-gzip body is never terminated, so browsers (which
    # send Accept-Encoding: gzip) hang waiting for the body. A pure ASGI passthrough leaves
    # the app's single-message response intact so GZip compresses it correctly.
    class AuthMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            request = Request(scope)
            if any(request.url.path.startswith(p) for p in EXEMPT_PREFIXES):
                await self.app(scope, receive, send)
                return
            token = request.cookies.get("access_token")
            if not token:
                await JSONResponse(
                    status_code=401, content={"detail": "Not authenticated"}
                )(scope, receive, send)
                return
            _settings = get_settings()
            try:
                jwt.decode(
                    token,
                    _settings.JWT_SECRET_KEY,
                    algorithms=[_settings.JWT_ALGORITHM],
                )
            except JWTError:
                await JSONResponse(
                    status_code=401, content={"detail": "Token expired or invalid"}
                )(scope, receive, send)
                return
            await self.app(scope, receive, send)

    # CSRFMiddleware added first = innermost (between AuthMiddleware and routes).
    # Inbound request flow: AuthMiddleware (401) → CSRFMiddleware (403) → route.
    app.add_middleware(CSRFMiddleware)
    # AuthMiddleware added second = outer (validates JWT before CSRF check).
    app.add_middleware(AuthMiddleware)

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Gzip middleware for large payloads — skip /metrics to avoid
    # BaseHTTPMiddleware ASGI message ordering conflict with compressed responses.
    class SelectiveGZipMiddleware(GZipMiddleware):
        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and scope.get("path", "").startswith("/metrics"):
                await self.app(scope, receive, send)
            else:
                await super().__call__(scope, receive, send)

    app.add_middleware(SelectiveGZipMiddleware, minimum_size=1000)

    # Rate limiting — added last = outermost middleware (LIFO stacking = first to process
    # inbound requests). When RATE_LIMITING_ENABLED=False, limiter.enabled=False means
    # neither middleware nor @limiter.limit() decorators enforce any limits.
    app.state.limiter = limiter
    app.add_middleware(SlowAPIASGIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
        retry_after = exc.limit.limit.get_expiry() if exc.limit else 60
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            content={
                "message": "Rate limit exceeded",
                "error_id": None,
                "retry_after": retry_after,
            },
        )

    # Prometheus HTTP metrics middleware
    from app.core.metrics import http_request_duration_seconds, http_requests_total

    # Pure ASGI metrics middleware (see AuthMiddleware note on avoiding BaseHTTPMiddleware).
    class PrometheusMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http" or scope.get("path") == "/metrics":
                await self.app(scope, receive, send)
                return
            start = _time.monotonic()
            status_code = 500

            async def send_wrapper(message):
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = message["status"]
                await send(message)

            await self.app(scope, receive, send_wrapper)
            duration = _time.monotonic() - start
            handler = scope["path"]
            method = scope["method"]
            http_requests_total.labels(
                method=method,
                handler=handler,
                status_code=str(status_code),
            ).inc()
            http_request_duration_seconds.labels(
                method=method,
                handler=handler,
            ).observe(duration)

    # Added last => outermost middleware, so it measures total request time including the
    # other layers, matching the prior @app.middleware("http") ordering.
    app.add_middleware(PrometheusMiddleware)

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics():
        if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
            from prometheus_client.multiprocess import MultiProcessCollector

            reg = CollectorRegistry()
            MultiProcessCollector(reg)
        else:
            reg = REGISTRY
        return Response(
            content=generate_latest(reg),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    # Include routers
    app.include_router(auth_router)
    app.include_router(health_router)
    app.include_router(scanner_router)
    app.include_router(universe_router)
    app.include_router(stocks_router)
    app.include_router(news_router)
    app.include_router(live_data_router)
    app.include_router(journal_router)
    app.include_router(system_router)
    app.include_router(futures_router)
    app.include_router(alerts_router)
    app.include_router(watchlist_router)
    app.include_router(auto_trading_router)
    app.include_router(outcomes_router)
    app.include_router(tweets_router)

    # Populate scan_orchestrator registry — must be after router includes.
    # importlib avoids the local variable `app` shadowing the package name.
    import importlib

    importlib.import_module("app.services.pre_market_scan")
    importlib.import_module("app.services.oversold_bounce_scan")
    importlib.import_module("app.services.liquidity_hunt")

    # Log a clear warning at startup whenever trace-exposure mode is enabled
    _expose_traces = settings.ENVIRONMENT.lower() in ("development", "debug")
    if _expose_traces:
        logging.warning(
            "⚠️  ENVIRONMENT=%s — stack traces ARE included in HTTP error responses. "
            "Never use this setting in production.",
            settings.ENVIRONMENT,
        )

    # Typed domain exception handler — must appear before the bare Exception handler.
    @app.exception_handler(MarketHawkError)
    async def markethawk_error_handler(request: Request, exc: MarketHawkError):
        status_code = 503 if exc.is_retryable else 422
        return JSONResponse(
            status_code=status_code,
            content={
                "message": str(exc),
                "error_type": type(exc).__name__,
                "retryable": exc.is_retryable,
            },
        )

    # Global Exception Handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # Fallback error ID just in case
        error_id = "ERR-UNKNOWN"
        tb_string = ""

        try:
            tb_string = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )

            # Hash traceback to generate deterministic Error ID
            error_hash = hashlib.md5(tb_string.encode("utf-8")).hexdigest()[:8]
            error_id = f"ERR-{error_hash}"

            # Send to Tracking System (Seq) - handled internally as background task
            tracker = ErrorTrackerFactory.get_tracker()
            tracker.log_error(error_id, exc, tb_string, str(request.url.path))
        except Exception as handler_exc:
            logging.error(f"Error in global_exception_handler: {handler_exc}")

        # Production-safe by default: only expose detail when explicitly in dev/debug.
        if _expose_traces:
            return JSONResponse(
                status_code=500,
                content={
                    "message": "Internal Server Error",
                    "error_id": error_id,
                    "detail": str(exc),
                    "stack_trace": tb_string,
                },
            )
        return JSONResponse(
            status_code=500,
            content={"message": "Internal Server Error", "error_id": error_id},
        )

    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
