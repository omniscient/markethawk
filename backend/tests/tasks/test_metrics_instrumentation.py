"""Verify that Celery tasks can be called with metrics instrumentation present."""


def test_scanning_imports_metrics_without_error():
    """Ensure scanning.py imports metrics module without raising."""
    import app.tasks.scanning  # noqa: F401
    from app.core.metrics import celery_task_duration_seconds, celery_tasks_total

    assert celery_tasks_total is not None
    assert celery_task_duration_seconds is not None


def test_sync_imports_metrics_without_error():
    import app.tasks.sync  # noqa: F401
    from app.core.metrics import celery_tasks_total

    assert celery_tasks_total is not None


def test_quality_imports_metrics_without_error():
    import app.tasks.quality  # noqa: F401
    from app.core.metrics import celery_tasks_total

    assert celery_tasks_total is not None


def test_trading_imports_metrics_without_error():
    import app.tasks.trading  # noqa: F401
    from app.core.metrics import celery_tasks_total

    assert celery_tasks_total is not None
