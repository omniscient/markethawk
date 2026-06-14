"""Unit tests for the metrics registry module."""

from prometheus_client import REGISTRY


def test_prometheus_client_importable():
    import prometheus_client

    assert prometheus_client is not None


def test_all_metric_names_registered():
    from app.core.metrics import (
        active_websocket_connections,
        celery_task_duration_seconds,
        celery_tasks_total,
        db_pool_checked_out,
        db_pool_overflow,
        db_pool_size,
        http_request_duration_seconds,
        http_requests_total,
        ibkr_connection_status,
        polygon_api_calls_total,
        scan_duration_seconds,
        scanner_events_total,
    )

    # prometheus_client strips the _total suffix from Counter internal _name
    assert http_requests_total._name == "http_requests"
    assert http_request_duration_seconds._name == "http_request_duration_seconds"
    assert scanner_events_total._name == "scanner_events"
    assert scan_duration_seconds._name == "scan_duration_seconds"
    assert polygon_api_calls_total._name == "polygon_api_calls"
    assert ibkr_connection_status._name == "ibkr_connection_status"
    assert celery_tasks_total._name == "celery_tasks"
    assert celery_task_duration_seconds._name == "celery_task_duration_seconds"
    assert active_websocket_connections._name == "active_websocket_connections"
    assert db_pool_size._name == "db_pool_size"
    assert db_pool_checked_out._name == "db_pool_checked_out"
    assert db_pool_overflow._name == "db_pool_overflow"


def test_scanner_events_counter_incrementable():
    from app.core.metrics import scanner_events_total

    label_vals = {"scanner_type": "pre_market_volume_spike"}
    before = REGISTRY.get_sample_value("scanner_events_total", label_vals) or 0.0
    scanner_events_total.labels(scanner_type="pre_market_volume_spike").inc()
    after = REGISTRY.get_sample_value("scanner_events_total", label_vals) or 0.0
    assert after == before + 1


def test_ibkr_connection_status_settable():
    from app.core.metrics import ibkr_connection_status

    ibkr_connection_status.set(1)
    assert REGISTRY.get_sample_value("ibkr_connection_status") == 1.0
    ibkr_connection_status.set(0)
    assert REGISTRY.get_sample_value("ibkr_connection_status") == 0.0


def test_slo_metrics_registered():
    """New SLO metrics must be importable and of the correct prometheus_client type."""
    from prometheus_client import Gauge, Histogram

    from app.core.metrics import (
        scan_data_to_detection_seconds,
        scan_failed_tickers_ratio,
        scan_last_success_timestamp,
    )

    assert isinstance(scan_last_success_timestamp, Gauge)
    assert scan_last_success_timestamp._name == "scan_last_success_timestamp"
    # multiprocess_mode="livemax" ensures the most-recent write survives across
    # Celery worker processes — verify the kwarg was not omitted.
    assert scan_last_success_timestamp._multiprocess_mode == "livemax"

    assert isinstance(scan_data_to_detection_seconds, Histogram)
    assert scan_data_to_detection_seconds._name == "scan_data_to_detection_seconds"

    assert isinstance(scan_failed_tickers_ratio, Gauge)
    assert scan_failed_tickers_ratio._name == "scan_failed_tickers_ratio"
    assert scan_failed_tickers_ratio._multiprocess_mode == "livemax"


def test_slo_gauge_settable():
    """scan_last_success_timestamp and scan_failed_tickers_ratio must accept .labels().set()."""
    from app.core.metrics import scan_failed_tickers_ratio, scan_last_success_timestamp

    scan_last_success_timestamp.labels(scanner_type="pre_market_volume_spike").set(
        1234567890.0
    )
    assert (
        REGISTRY.get_sample_value(
            "scan_last_success_timestamp",
            {"scanner_type": "pre_market_volume_spike"},
        )
        == 1234567890.0
    )

    scan_failed_tickers_ratio.labels(scanner_type="pre_market_volume_spike").set(0.05)
    assert (
        REGISTRY.get_sample_value(
            "scan_failed_tickers_ratio",
            {"scanner_type": "pre_market_volume_spike"},
        )
        == 0.05
    )
