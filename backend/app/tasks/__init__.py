from app.tasks.sync import (
    sync_tickers_batch,
    sync_ticker_details,
    start_details_crawl,
    sync_stock_aggregates,
    poll_massive_news,
    sync_futures_aggregates,
    sync_stock_splits,
    trigger_tweet_monitor,
)
from app.tasks.scanning import (
    evaluate_scanner_alerts,
    run_range_scan,
    run_liquidity_hunt_scheduled,
    run_universe_scan,
)
from app.tasks.trading import (
    execute_auto_trade,
    submit_approved_order,
    poll_auto_trade_fills,
)
from app.tasks.quality import (
    analyze_universe_quality,
    normalize_universe_quality,
    analyze_signal_features,
)

__all__ = [
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
    "evaluate_scanner_alerts",
    "run_range_scan",
    "run_liquidity_hunt_scheduled",
    "run_universe_scan",
    # trading
    "execute_auto_trade",
    "submit_approved_order",
    "poll_auto_trade_fills",
    # quality
    "analyze_universe_quality",
    "normalize_universe_quality",
    "analyze_signal_features",
]
