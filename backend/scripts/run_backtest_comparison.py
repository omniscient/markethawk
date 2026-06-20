#!/usr/bin/env python3
"""
Backtest comparison run: 5 scanners × 3 strategy profiles.

Usage (inside the backend container):
  python scripts/run_backtest_comparison.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
                                             [--universe-id N] [--max-hold N]

Output:
  backend/docs/backtest/comparison-{end_date}.md
  (mounted read-only in dev; run without override: docker-compose -f docker-compose.yml exec backend ...)
"""

import argparse
import calendar
import sys
import time
import uuid as _uuid
from datetime import date
from pathlib import Path

# Module-level import so tests can patch scripts.run_backtest_comparison.run_backtest
from app.tasks.backtest import run_backtest  # noqa: E402

SCANNERS = [
    "trend_pullback",
    "oversold_bounce",
    "pocket_pivot",
    "pre_market_volume_spike",
    "liquidity_hunt",
]

STRATEGY_DEFINITIONS = [
    {
        "name": "backtest-tight-2pct-2to1",
        "entry_type": "market",
        "stop_pct": 2.0,
        "risk_reward_ratio": 2.0,
        "limit_offset_pct": 0.0,
        "allowed_sessions": ["regular"],
    },
    {
        "name": "backtest-loose-4pct-1.5to1",
        "entry_type": "market",
        "stop_pct": 4.0,
        "risk_reward_ratio": 1.5,
        "limit_offset_pct": 0.0,
        "allowed_sessions": ["regular"],
    },
    {
        "name": "backtest-pullback-limit-2pct-2to1",
        "entry_type": "limit",
        "stop_pct": 2.0,
        "risk_reward_ratio": 2.0,
        "limit_offset_pct": -0.5,
        "allowed_sessions": ["regular", "pre"],
    },
]

POLL_INTERVAL_SECONDS = 5
TIMEOUT_SECONDS = 30 * 60  # 30 minutes
LOW_SAMPLE_THRESHOLD = 20


def _today() -> date:
    return date.today()


def _default_date_range() -> tuple[date, date]:
    """Return (start, end) for trailing 12 months ending at last completed month."""
    today = _today()
    first_this_month = today.replace(day=1)
    if first_this_month.month == 1:
        prior_month = first_this_month.replace(year=first_this_month.year - 1, month=12)
    else:
        prior_month = first_this_month.replace(month=first_this_month.month - 1)
    end = prior_month.replace(
        day=calendar.monthrange(prior_month.year, prior_month.month)[1]
    )
    start = today.replace(year=today.year - 1, day=1)
    return start, end


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run 5×3 backtest comparison and write a Markdown report."
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=None,
        help="Start date YYYY-MM-DD (default: 12 months ago, first of month)",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=None,
        help="End date YYYY-MM-DD (default: last day of prior month)",
    )
    parser.add_argument(
        "--universe-id",
        type=int,
        default=1,
        dest="universe_id",
        help="StockUniverse id (default: 1)",
    )
    parser.add_argument(
        "--max-hold",
        type=int,
        default=10,
        dest="max_hold",
        help="Max hold sessions per trade (default: 10)",
    )
    return parser.parse_args(argv)


def _seed_strategies(db) -> list[int]:
    """Get-or-create the 3 backtest TradingStrategy rows. Returns list of IDs in definition order."""
    from app.models.trading_strategy import TradingStrategy

    ids = []
    for defn in STRATEGY_DEFINITIONS:
        row = (
            db.query(TradingStrategy)
            .filter(TradingStrategy.name == defn["name"])
            .first()
        )
        if row is None:
            row = TradingStrategy(
                name=defn["name"],
                entry_type=defn["entry_type"],
                stop_pct=defn["stop_pct"],
                risk_reward_ratio=defn["risk_reward_ratio"],
                limit_offset_pct=defn["limit_offset_pct"],
                allowed_sessions=defn["allowed_sessions"],
                paper_mode=True,
                requires_approval=False,
                risk_per_trade_pct=1.0,
                direction="long_only",
                max_trades_per_day=99,
                max_concurrent_positions=99,
            )
            db.add(row)
            db.flush()  # populate row.id before moving to next strategy
        ids.append(row.id)
    return ids


def _parse_run_uuids(run_uuids: list) -> list:
    """Convert any mix of str/UUID to UUID objects.

    BacktestRun.uuid is UUID(as_uuid=True); Postgres requires uuid.UUID objects
    (not strings) in .in_() queries.
    """
    return [_uuid.UUID(str(u)) for u in run_uuids]


def _enqueue_runs(
    db,
    strategy_ids: list[int],
    universe_id: int,
    start_date: date,
    end_date: date,
    max_hold_sessions: int,
) -> list:
    """Create 15 BacktestRun rows (5 scanners × 3 strategies) and dispatch Celery tasks."""
    from app.models.backtest_run import BacktestRun
    from app.utils.time import utc_now

    runs = []
    for scanner_type in SCANNERS:
        for strategy_id in strategy_ids:
            run = BacktestRun(
                uuid=_uuid.uuid4(),
                scanner_type=scanner_type,
                strategy_id=strategy_id,
                universe_id=universe_id,
                start_date=start_date,
                end_date=end_date,
                max_hold_sessions=max_hold_sessions,
                status="queued",
                created_at=utc_now(),
            )
            db.add(run)
            db.flush()  # obtain run.id before dispatching
            db.refresh(run)

            async_result = run_backtest.delay(
                run_id=run.id,
                scanner_type=scanner_type,
                strategy_id=strategy_id,
                universe_id=universe_id,
                start_date_iso=start_date.isoformat(),
                end_date_iso=end_date.isoformat(),
                max_hold_sessions=max_hold_sessions,
            )
            run.celery_task_id = async_result.id
            runs.append(run)

    db.commit()
    return runs


def _poll_until_done(db, run_uuids: list, timeout: int = TIMEOUT_SECONDS) -> list:
    """Poll BacktestRun.status until all reach 'completed'.

    Calls sys.exit(1) if any run fails or the timeout is exceeded.
    """
    from app.models.backtest_run import BacktestRun

    uuid_objs = _parse_run_uuids(
        run_uuids
    )  # str → UUID for Postgres UUID(as_uuid=True)
    deadline = time.monotonic() + timeout
    total = len(run_uuids)

    while True:
        db.expire_all()
        runs = db.query(BacktestRun).filter(BacktestRun.uuid.in_(uuid_objs)).all()
        failed = [r for r in runs if r.status == "failed"]
        if failed:
            for r in failed:
                print(
                    f"FAILED: {r.scanner_type} — {r.error_message}",
                    file=sys.stderr,
                )
            sys.exit(1)

        done = [r for r in runs if r.status == "completed"]
        print(f"Progress: {len(done)}/{total} completed", flush=True)
        if len(done) == total:
            return runs

        if time.monotonic() > deadline:
            print(
                f"TIMEOUT: {len(done)}/{total} completed after {timeout}s",
                file=sys.stderr,
            )
            sys.exit(1)

        time.sleep(POLL_INTERVAL_SECONDS)


def _resolve_universe(db, universe_id: int) -> tuple[str, int]:
    """Return (name, ticker_count) for the given universe. Exits on not found."""
    from app.models.stock_universe import StockUniverse
    from app.models.stock_universe_ticker import StockUniverseTicker

    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if universe is None:
        print(f"ERROR: StockUniverse id={universe_id} not found", file=sys.stderr)
        sys.exit(1)
    count = (
        db.query(StockUniverseTicker)
        .filter(StockUniverseTicker.universe_id == universe_id)
        .count()
    )
    return universe.name, count


def _render_markdown(
    stats: dict,
    universe_id: int,
    universe_name: str,
    ticker_count: int,
    start_date: date,
    end_date: date,
    max_hold_sessions: int,
) -> str:
    """Render the full comparison Markdown document."""
    from datetime import datetime, timezone

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    strategy_slugs = [d["name"] for d in STRATEGY_DEFINITIONS]
    short_slugs = ["tight-2pct-2to1", "loose-4pct-1.5to1", "pullback-limit"]

    lines: list[str] = []

    # YAML frontmatter
    lines += [
        "---",
        f"universe_id: {universe_id}",
        f"universe_name: {universe_name}",
        f"ticker_count: {ticker_count}",
        f"start_date: {start_date}",
        f"end_date: {end_date}",
        f"max_hold_sessions: {max_hold_sessions}",
        "strategies:",
        f"  {strategy_slugs[0]}: {{entry: market, stop_pct: 2.0, rr: 2.0, sessions: [regular]}}",
        f"  {strategy_slugs[1]}: {{entry: market, stop_pct: 4.0, rr: 1.5, sessions: [regular]}}",
        (
            f"  {strategy_slugs[2]}: {{entry: limit, limit_offset_pct: -0.5,"
            " stop_pct: 2.0, rr: 2.0, sessions: [regular, pre]}}"
        ),
        f"generated_at: {generated_at}",
        'harness_issue: "301"',
        "---",
        "",
        (
            "> **Note — `pre_market_volume_spike`**: this scanner fires on intraday"
            " pre-market minute bars."
        ),
        (
            "> Where those are absent in the replay window the harness uses stored"
            " `ScannerEvent` rows only."
        ),
        "> Interpret its row against `trade_count`; a low count indicates limited"
        " historical data coverage.",
        "",
    ]

    header_row = "| Scanner | " + " | ".join(short_slugs) + " |"
    sep_row = "|---------|" + "|".join(["---"] * len(short_slugs)) + "|"

    def _cell(metric_key: str, fmt_str: str, scanner: str, slug: str) -> str:
        s = stats.get((scanner, slug), {})
        v = s.get(metric_key)
        if v is None:
            cell = "N/A"
        else:
            cell = format(v, fmt_str)
        trades = s.get("total_trades") or 0
        if trades < LOW_SAMPLE_THRESHOLD:
            cell += " ⚠*"
        return cell

    def _metric_table(metric_key: str, fmt_str: str, heading: str) -> list[str]:
        rows = [f"## {heading}", "", header_row, sep_row]
        for scanner in SCANNERS:
            cells = [
                _cell(metric_key, fmt_str, scanner, slug) for slug in strategy_slugs
            ]
            rows.append(f"| {scanner} | " + " | ".join(cells) + " |")
        rows.append("")
        return rows

    lines += _metric_table("expectancy_r", ".3f", "Expectancy (R)")
    lines += _metric_table("profit_factor", ".2f", "Profit Factor")
    lines += _metric_table("win_rate", ".1%", "Win Rate (%)")
    lines += _metric_table("max_drawdown_r", ".2f", "Max Drawdown (%)")

    # Trade count table — flag low-sample cells; count displayed raw
    lines += ["## Trade Count", "", header_row, sep_row]
    for scanner in SCANNERS:
        cells = []
        for slug in strategy_slugs:
            s = stats.get((scanner, slug), {})
            trades = s.get("total_trades")
            if trades is None:
                cells.append("N/A")
            elif trades < LOW_SAMPLE_THRESHOLD:
                cells.append(f"{trades} ⚠*")
            else:
                cells.append(str(trades))
        lines.append(f"| {scanner} | " + " | ".join(cells) + " |")
    lines += ["", "⚠ Cells with fewer than 20 trades are marked with *.", ""]

    # Findings
    lines += ["## Findings", ""]
    positives = []
    best: tuple | None = None
    best_exp: float | None = None

    for scanner in SCANNERS:
        for slug in strategy_slugs:
            s = stats.get((scanner, slug), {})
            exp = s.get("expectancy_r")
            trades = s.get("total_trades") or 0
            if exp is not None and exp > 0 and trades >= LOW_SAMPLE_THRESHOLD:
                positives.append(
                    f"- **{scanner}** / `{slug}` —"
                    f" expectancy_r={exp:.3f} R ({trades} trades)"
                )
                if best_exp is None or exp > best_exp:
                    best_exp = exp
                    best = (scanner, slug, exp, trades)

    if positives:
        lines.append(
            "Combos with positive expectancy (expectancy_r > 0, trade_count ≥ 20):"
        )
        lines += positives
    else:
        lines.append("No combos with positive expectancy and ≥ 20 trades.")

    lines.append("")
    if best:
        s, slug, exp, trades = best
        lines.append(
            f"Best combo: **{s}** / `{slug}`"
            f" (expectancy_r = {exp:.2f} R, {trades} trades)"
        )
    else:
        lines.append("Best combo: N/A")

    all_negative = [
        scanner
        for scanner in SCANNERS
        if all(
            (stats.get((scanner, slug), {}).get("expectancy_r") or 0) <= 0
            for slug in strategy_slugs
        )
    ]
    lines.append("")
    if all_negative:
        lines.append(
            f"Scanners negative across all strategies: {', '.join(all_negative)}"
        )
    else:
        lines.append("Scanners negative across all strategies: none")

    return "\n".join(lines) + "\n"


def main():
    args = _parse_args()

    if args.start and args.end:
        start_date, end_date = args.start, args.end
    else:
        start_date, end_date = _default_date_range()

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        print("Seeding strategies...")
        strategy_ids = _seed_strategies(db)
        print(f"  Strategy IDs: {strategy_ids}")

        universe_name, ticker_count = _resolve_universe(db, args.universe_id)
        print(f"Universe: {universe_name} ({ticker_count} tickers)")
        print(f"Date range: {start_date} → {end_date}")
        print("Enqueueing 15 backtest runs (5 scanners × 3 strategies)...")

        runs = _enqueue_runs(
            db=db,
            strategy_ids=strategy_ids,
            universe_id=args.universe_id,
            start_date=start_date,
            end_date=end_date,
            max_hold_sessions=args.max_hold,
        )
        run_uuids = [str(r.uuid) for r in runs]
        print(f"Enqueued {len(run_uuids)} runs. Polling (timeout=30 min)...")

        completed_runs = _poll_until_done(db=db, run_uuids=run_uuids)

        id_to_slug = {
            sid: defn["name"] for sid, defn in zip(strategy_ids, STRATEGY_DEFINITIONS)
        }
        stats: dict = {}
        for run in completed_runs:
            slug = id_to_slug.get(run.strategy_id)
            if slug:
                stats[(run.scanner_type, slug)] = {
                    "total_trades": run.total_trades,
                    "win_rate": run.win_rate,
                    "profit_factor": run.profit_factor,
                    "expectancy_r": run.expectancy_r,
                    "max_drawdown_r": run.max_drawdown_r,
                }

        md = _render_markdown(
            stats=stats,
            universe_id=args.universe_id,
            universe_name=universe_name,
            ticker_count=ticker_count,
            start_date=start_date,
            end_date=end_date,
            max_hold_sessions=args.max_hold,
        )

        # Output at backend/docs/backtest/ (= /app/docs/backtest/ in container)
        out_dir = Path(__file__).parent.parent / "docs" / "backtest"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"comparison-{end_date}.md"
        out_path.write_text(md, encoding="utf-8")
        print(f"\nWritten: {out_path}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
