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

scan_last_success_timestamp = Gauge(
    "scan_last_success_timestamp",
    "Unix timestamp of the last successful scan completion",
    ["scanner_type"],
    multiprocess_mode="livemax",
)

scan_data_to_detection_seconds = Histogram(
    "scan_data_to_detection_seconds",
    "Seconds between the freshest bar used and ScannerEvent creation time",
    ["scanner_type"],
    buckets=[30, 60, 120, 300, 600, 900, 1800, 3600],
)

scan_failed_tickers_ratio = Gauge(
    "scan_failed_tickers_ratio",
    "Fraction of tickers that failed in the most recent scan run (0.0–1.0)",
    ["scanner_type"],
    multiprocess_mode="livemax",
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

# ── Provider health (#388, ADR-0013) ────────────────────────────────────────
# Set only by the API process at scrape time (refresh_provider_health_gauges in
# app/core/provider_health.py) from the cross-process Redis health record, so
# "livemostrecent" is the right multiprocess aggregation.
provider_request_latency_p95_seconds = Gauge(
    "provider_request_latency_p95_seconds",
    "Rolling 15-minute p95 latency of provider REST requests (seconds; 0 = too few calls)",
    ["provider"],
    multiprocess_mode="livemostrecent",
)

provider_error_rate = Gauge(
    "provider_error_rate",
    "Rolling 5-minute provider request error rate (0.0–1.0; 0 = too few calls)",
    ["provider"],
    multiprocess_mode="livemostrecent",
)

provider_circuit_breaker_state = Gauge(
    "provider_circuit_breaker_state",
    "Worst provider circuit-breaker state across processes (0=closed, 1=half-open, 2=open)",
    ["provider"],
    multiprocess_mode="livemostrecent",
)

polygon_ws_connected = Gauge(
    "polygon_ws_connected",
    "Polygon per-ticker WebSocket stream (1=connected, 0=disconnected, -1=disabled by config)",
    multiprocess_mode="livemostrecent",
)

# Set by the Celery worker at the end of each scan that touched a live session day.
# "mostrecent" (not live) so the value survives prefork child recycling.
scan_provider_gap_severity = Gauge(
    "scan_provider_gap_severity",
    "Live provider-gap severity of the most recent scan run (0=none, 1=warning, 2=blocker)",
    ["scanner_type"],
    multiprocess_mode="mostrecent",
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

aggregate_staleness_hours = Gauge(
    "markethawk_aggregate_staleness_hours",
    "Worst-case staleness (hours since last bar) across tickers in a universe",
    ["universe_id"],
    multiprocess_mode="livemax",
)

aggregate_gap_days = Gauge(
    "markethawk_aggregate_gap_days",
    "Worst-case gap span (weekdays) across tickers in a universe",
    ["universe_id"],
    multiprocess_mode="livemax",
)

replay_drift_signals_total = Counter(
    "markethawk_replay_drift_signals_total",
    "Replay diff drift signals by kind",
    ["scanner_type", "kind"],
)

live_orders_total = Counter(
    "live_orders_total",
    "Total live (non-paper) bracket orders placed to IBKR",
    ["symbol", "side"],
)
