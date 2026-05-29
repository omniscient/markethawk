from prometheus_client import Counter, Gauge, Histogram

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests received",
    ["method", "handler", "status_code"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "handler"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
)

scanner_events_total = Counter(
    "scanner_events_total",
    "Total scanner events emitted",
    ["scanner_type"],
)

scan_duration_seconds = Histogram(
    "scan_duration_seconds",
    "Duration of a scanner run in seconds",
    ["scanner_type"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300],
)

polygon_api_calls_total = Counter(
    "polygon_api_calls_total",
    "Total calls made to the Polygon.io API",
    ["endpoint"],
)

ibkr_connection_status = Gauge(
    "ibkr_connection_status",
    "IBKR connection status (1=connected, 0=disconnected)",
)

celery_tasks_total = Counter(
    "celery_tasks_total",
    "Total Celery tasks executed",
    ["task_name", "status"],
)

celery_task_duration_seconds = Histogram(
    "celery_task_duration_seconds",
    "Celery task execution duration in seconds",
    ["task_name"],
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 300],
)

active_websocket_connections = Gauge(
    "active_websocket_connections",
    "Number of active WebSocket connections from frontend clients",
)

db_pool_size = Gauge("db_pool_size", "SQLAlchemy connection pool configured size")
db_pool_checked_out = Gauge(
    "db_pool_checked_out", "Connections currently checked out from pool"
)
db_pool_overflow = Gauge("db_pool_overflow", "Overflow connections beyond pool_size")
