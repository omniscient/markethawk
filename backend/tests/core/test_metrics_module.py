"""Unit tests for the metrics registry module."""
from prometheus_client import REGISTRY


def test_prometheus_client_importable():
    import prometheus_client
    assert prometheus_client is not None


def test_instrumentator_importable():
    from prometheus_fastapi_instrumentator import Instrumentator
    assert Instrumentator is not None


def test_all_metric_names_registered():
    from app.core.metrics import (
        scanner_events_total,
        scan_duration_seconds,
        polygon_api_calls_total,
        ibkr_connection_status,
        celery_tasks_total,
        celery_task_duration_seconds,
        active_websocket_connections,
        db_pool_size,
        db_pool_checked_out,
        db_pool_overflow,
    )
    assert scanner_events_total._name == "scanner_events_total"
    assert scan_duration_seconds._name == "scan_duration_seconds"
    assert polygon_api_calls_total._name == "polygon_api_calls_total"
    assert ibkr_connection_status._name == "ibkr_connection_status"
    assert celery_tasks_total._name == "celery_tasks_total"
    assert celery_task_duration_seconds._name == "celery_task_duration_seconds"
    assert active_websocket_connections._name == "active_websocket_connections"
    assert db_pool_size._name == "db_pool_size"
    assert db_pool_checked_out._name == "db_pool_checked_out"
    assert db_pool_overflow._name == "db_pool_overflow"


def test_scanner_events_counter_incrementable():
    from app.core.metrics import scanner_events_total
    label_vals = {"scanner_type": "pre_market_volume_spike"}
    before = REGISTRY.get_sample_value("scanner_events_total_total", label_vals) or 0.0
    scanner_events_total.labels(scanner_type="pre_market_volume_spike").inc()
    after = REGISTRY.get_sample_value("scanner_events_total_total", label_vals) or 0.0
    assert after == before + 1


def test_ibkr_connection_status_settable():
    from app.core.metrics import ibkr_connection_status
    ibkr_connection_status.set(1)
    assert REGISTRY.get_sample_value("ibkr_connection_status") == 1.0
    ibkr_connection_status.set(0)
    assert REGISTRY.get_sample_value("ibkr_connection_status") == 0.0
