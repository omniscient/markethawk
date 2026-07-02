from app.tasks.backtest import run_backtest
from app.tasks.explanations import backfill_scanner_explanations
from app.tasks.quality import (
    analyze_signal_features,
    analyze_universe_quality,
    check_aggregate_staleness,
    normalize_universe_quality,
)
from app.tasks.regime import backfill_regime_labels, update_regime_model
from app.tasks.replay import run_signal_replay
from app.tasks.scanning import (
    evaluate_scanner_alerts,
    run_liquidity_hunt_scheduled,
    run_pocket_pivot_scheduled,
    run_range_scan,
    run_universe_scan,
)
from app.tasks.sync import (
    poll_massive_news,
    start_details_crawl,
    sync_futures_aggregates,
    sync_stock_aggregates,
    sync_stock_splits,
    sync_ticker_details,
    sync_tickers_batch,
    trigger_tweet_monitor,
)
from app.tasks.trading import (
    execute_auto_trade,
    poll_auto_trade_fills,
    submit_approved_order,
)

__all__ = [
    # backtest
    "run_backtest",
    "run_signal_replay",
    "backfill_scanner_explanations",
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
    "run_pocket_pivot_scheduled",
    "run_universe_scan",
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
]
