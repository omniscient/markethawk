"""Smoke tests: verify tasks/ package exports and Celery task names."""

import importlib

PUBLIC_TASKS = [
    # sync
    "sync_tickers_batch",
    "sync_ticker_details",
    "start_details_crawl",
    "sync_stock_aggregates",
    "poll_massive_news",
    "sync_futures_aggregates",
    "sync_stock_splits",
    "trigger_tweet_monitor",
    # scanning
    "run_universe_scan",
    "run_range_scan",
    "run_liquidity_hunt_scheduled",
    "evaluate_scanner_alerts",
    # trading
    "execute_auto_trade",
    "submit_approved_order",
    "poll_auto_trade_fills",
    # quality
    "analyze_universe_quality",
    "normalize_universe_quality",
    "analyze_signal_features",
    "check_aggregate_staleness",
    # regime
    "update_regime_model",
    "backfill_regime_labels",
    # embeddings
    "embed_news_article_source",
    "embed_scanner_event_sources",
    "embed_generated_narrative_source",
]

SUBMODULE_TASKS = {
    "app.tasks.sync": [
        "sync_tickers_batch",
        "sync_ticker_details",
        "start_details_crawl",
        "sync_stock_aggregates",
        "poll_massive_news",
        "sync_futures_aggregates",
        "sync_stock_splits",
        "trigger_tweet_monitor",
    ],
    "app.tasks.scanning": [
        "run_universe_scan",
        "run_range_scan",
        "run_liquidity_hunt_scheduled",
        "evaluate_scanner_alerts",
    ],
    "app.tasks.trading": [
        "execute_auto_trade",
        "submit_approved_order",
        "poll_auto_trade_fills",
    ],
    "app.tasks.quality": [
        "analyze_universe_quality",
        "normalize_universe_quality",
        "analyze_signal_features",
        "check_aggregate_staleness",
    ],
    "app.tasks.regime": [
        "update_regime_model",
        "backfill_regime_labels",
    ],
    "app.tasks.embeddings": [
        "embed_news_article_source",
        "embed_scanner_event_sources",
        "embed_generated_narrative_source",
    ],
}


def test_public_tasks_importable_from_top_level():
    """from app.tasks import <name> must work for all public tasks."""
    import app.tasks as tasks_pkg

    for name in PUBLIC_TASKS:
        assert hasattr(tasks_pkg, name), f"app.tasks.{name} not found"


def test_submodule_imports():
    """Each submodule must be importable and expose its task names."""
    for module_path, names in SUBMODULE_TASKS.items():
        mod = importlib.import_module(module_path)
        for name in names:
            assert hasattr(mod, name), f"{module_path}.{name} not found"


def test_celery_task_names_preserved():
    """Every public task must have name='app.tasks.<task_name>'."""
    import app.tasks as tasks_pkg

    for name in PUBLIC_TASKS:
        task = getattr(tasks_pkg, name)
        expected = f"app.tasks.{name}"
        assert task.name == expected, (
            f"Task {name}: expected name='app.tasks.{name}', got '{task.name}'"
        )


def test_private_helpers_not_in_init():
    """Private helpers must NOT be re-exported from app.tasks."""
    import app.tasks as tasks_pkg

    private = [
        "_check_entry_slippage",
        "_record_entry_fill",
        "_record_exit_fill",
        "_poll_live_orders",
        "_simulate_paper_exit",
    ]
    for name in private:
        assert not hasattr(tasks_pkg, name), (
            f"app.tasks.{name} should not be exported from __init__"
        )


def test_private_helpers_in_trading_module():
    """Private helpers must live in app.tasks.trading."""
    from app.tasks import trading as trading_mod

    private = [
        "_check_entry_slippage",
        "_record_entry_fill",
        "_record_exit_fill",
        "_poll_live_orders",
        "_simulate_paper_exit",
    ]
    for name in private:
        assert hasattr(trading_mod, name), f"app.tasks.trading.{name} not found"


def test_app_tasks_is_a_package():
    """app.tasks must be a package (directory), not a flat module."""
    import os

    import app.tasks as tasks_pkg

    pkg_file = tasks_pkg.__file__
    assert pkg_file is not None
    assert os.path.basename(pkg_file) == "__init__.py", (
        f"Expected tasks/__init__.py, got {pkg_file}"
    )


def test_celery_beat_string_names_resolve():
    """Task string names used in celery_app beat schedule must resolve via registry."""
    from app.core.celery_app import celery_app

    beat_task_names = [
        "app.tasks.poll_massive_news",
        "app.tasks.sync_stock_splits",
        "app.tasks.poll_auto_trade_fills",
        "app.tasks.run_liquidity_hunt_scheduled",
        "app.tasks.analyze_signal_features",
        "app.tasks.trigger_tweet_monitor",
        "app.tasks.update_regime_model",
        "app.tasks.check_aggregate_staleness",
    ]
    for task_name in beat_task_names:
        assert task_name in celery_app.tasks, (
            f"Beat task '{task_name}' not registered in Celery app"
        )
