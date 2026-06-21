"""Unit tests for run_backtest_comparison.py helpers."""

import uuid as _uuid_mod
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Date-range helpers
# ---------------------------------------------------------------------------


def test_default_date_range_mid_year():
    # Today=2026-06-15 → start=2025-06-01, end=2026-05-31
    with patch(
        "scripts.run_backtest_comparison._today", return_value=date(2026, 6, 15)
    ):
        from scripts.run_backtest_comparison import _default_date_range

        start, end = _default_date_range()
    assert start == date(2025, 6, 1)
    assert end == date(2026, 5, 31)


def test_default_date_range_january_wraps_year():
    # Today=2026-01-10 → start=2025-01-01, end=2025-12-31
    with patch(
        "scripts.run_backtest_comparison._today", return_value=date(2026, 1, 10)
    ):
        from scripts.run_backtest_comparison import _default_date_range

        start, end = _default_date_range()
    assert start == date(2025, 1, 1)
    assert end == date(2025, 12, 31)


# ---------------------------------------------------------------------------
# CLI arg parsing
# ---------------------------------------------------------------------------


def test_parse_args_defaults():
    from scripts.run_backtest_comparison import _parse_args

    args = _parse_args([])
    assert args.universe_id == 1
    assert args.max_hold == 10
    assert args.start is None
    assert args.end is None


def test_parse_args_overrides():
    from scripts.run_backtest_comparison import _parse_args

    args = _parse_args(
        [
            "--start",
            "2025-01-01",
            "--end",
            "2025-12-31",
            "--universe-id",
            "3",
            "--max-hold",
            "20",
        ]
    )
    assert args.start == date(2025, 1, 1)
    assert args.end == date(2025, 12, 31)
    assert args.universe_id == 3
    assert args.max_hold == 20


# ---------------------------------------------------------------------------
# Strategy seed
# ---------------------------------------------------------------------------


def _make_db_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


def _stub_strategy(name: str, id_: int):
    s = MagicMock()
    s.id = id_
    s.name = name
    return s


def test_seed_strategies_creates_all_three_when_absent():
    from scripts.run_backtest_comparison import _seed_strategies

    db = _make_db_not_found()
    ids = _seed_strategies(db)
    assert len(ids) == 3
    assert db.add.call_count == 3
    assert db.flush.call_count == 3


def test_seed_strategies_idempotent_when_rows_exist():
    from scripts.run_backtest_comparison import STRATEGY_DEFINITIONS, _seed_strategies

    db = MagicMock()
    stubs = [
        _stub_strategy(d["name"], i + 10) for i, d in enumerate(STRATEGY_DEFINITIONS)
    ]
    db.query.return_value.filter.return_value.first.side_effect = stubs
    ids = _seed_strategies(db)
    assert ids == [10, 11, 12]
    db.add.assert_not_called()


def test_seed_strategies_returns_three_ids():
    from scripts.run_backtest_comparison import STRATEGY_DEFINITIONS, _seed_strategies

    # Use stubs so row.id is a real int (MagicMock db.flush() doesn't populate ORM ids)
    db = MagicMock()
    stubs = [
        _stub_strategy(d["name"], i + 1) for i, d in enumerate(STRATEGY_DEFINITIONS)
    ]
    db.query.return_value.filter.return_value.first.side_effect = stubs
    ids = _seed_strategies(db)
    assert len(ids) == 3
    assert all(isinstance(i, int) for i in ids)


# ---------------------------------------------------------------------------
# UUID conversion (Postgres UUID(as_uuid=True) requires UUID objects, not strings)
# ---------------------------------------------------------------------------


def test_parse_run_uuids_converts_strings():
    from scripts.run_backtest_comparison import _parse_run_uuids

    uuid_str = "12345678-1234-5678-1234-567812345678"
    result = _parse_run_uuids([uuid_str])
    assert result == [_uuid_mod.UUID(uuid_str)]
    assert all(isinstance(u, _uuid_mod.UUID) for u in result)


def test_parse_run_uuids_accepts_uuid_objects():
    from scripts.run_backtest_comparison import _parse_run_uuids

    uid = _uuid_mod.uuid4()
    result = _parse_run_uuids([uid])
    assert result == [uid]


# ---------------------------------------------------------------------------
# Enqueue + poll
# ---------------------------------------------------------------------------


def test_enqueue_runs_creates_15_rows():
    from scripts.run_backtest_comparison import SCANNERS, _enqueue_runs

    db = MagicMock()
    created_runs = []

    def capturing_add(obj):
        obj.id = None
        created_runs.append(obj)

    def fake_flush():
        for run in created_runs:
            if run.id is None:
                run.id = len(created_runs)

    db.add.side_effect = capturing_add
    db.flush.side_effect = fake_flush
    db.refresh.side_effect = lambda obj: None

    with patch("scripts.run_backtest_comparison.run_backtest") as mock_task:
        mock_task.delay.return_value.id = "celery-id"
        runs = _enqueue_runs(
            db=db,
            strategy_ids=[1, 2, 3],
            universe_id=1,
            start_date=date(2025, 6, 1),
            end_date=date(2026, 5, 31),
            max_hold_sessions=10,
        )

    assert len(runs) == 15  # 5 scanners × 3 strategies
    dispatched_scanners = [
        c.kwargs["scanner_type"] for c in mock_task.delay.call_args_list
    ]
    for scanner in SCANNERS:
        assert dispatched_scanners.count(scanner) == 3


def test_poll_returns_when_all_completed():
    from scripts.run_backtest_comparison import _poll_until_done

    db = MagicMock()
    runs = [MagicMock(uuid=_uuid_mod.uuid4(), status="completed") for _ in range(15)]
    db.query.return_value.filter.return_value.all.return_value = runs

    run_uuids = [str(r.uuid) for r in runs]
    result = _poll_until_done(db=db, run_uuids=run_uuids, timeout=30)
    assert len(result) == 15


def test_poll_exits_on_failed_run():
    from scripts.run_backtest_comparison import _poll_until_done

    db = MagicMock()
    runs = [MagicMock(uuid=_uuid_mod.uuid4(), status="completed") for _ in range(14)]
    failed = MagicMock(
        uuid=_uuid_mod.uuid4(),
        status="failed",
        scanner_type="trend_pullback",
        error_message="crash",
    )
    runs.append(failed)
    db.query.return_value.filter.return_value.all.return_value = runs

    with pytest.raises(SystemExit):
        _poll_until_done(db=db, run_uuids=[str(r.uuid) for r in runs], timeout=30)


def test_poll_exits_on_timeout():
    from scripts.run_backtest_comparison import _poll_until_done

    db = MagicMock()
    stuck = [MagicMock(uuid=_uuid_mod.uuid4(), status="running")]
    db.query.return_value.filter.return_value.all.return_value = stuck

    with patch("time.sleep"), patch("time.monotonic", side_effect=[0.0, 3601.0]):
        with pytest.raises(SystemExit):
            _poll_until_done(db=db, run_uuids=[str(stuck[0].uuid)], timeout=1)


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _full_stats(expectancy_r=0.3, total_trades=30):
    from scripts.run_backtest_comparison import SCANNERS, STRATEGY_DEFINITIONS

    stats = {}
    for scanner in SCANNERS:
        for defn in STRATEGY_DEFINITIONS:
            stats[(scanner, defn["name"])] = {
                "total_trades": total_trades,
                "win_rate": 0.55,
                "profit_factor": 1.8,
                "expectancy_r": expectancy_r,
                "max_drawdown_r": -2.5,
            }
    return stats


def test_render_markdown_contains_all_section_headers():
    from scripts.run_backtest_comparison import _render_markdown

    md = _render_markdown(
        stats=_full_stats(),
        universe_id=1,
        universe_name="Main Liquid Universe",
        ticker_count=50,
        start_date=date(2025, 6, 1),
        end_date=date(2026, 5, 31),
        max_hold_sessions=10,
    )
    assert "## Expectancy (R)" in md
    assert "## Profit Factor" in md
    assert "## Win Rate (%)" in md
    assert "## Max Drawdown (%)" in md
    assert "## Trade Count" in md
    assert "## Findings" in md
    assert "universe_id:" in md  # YAML frontmatter present
    assert "generated_at:" in md


def test_render_markdown_low_sample_flag():
    from scripts.run_backtest_comparison import _render_markdown

    md = _render_markdown(
        stats=_full_stats(total_trades=5),  # below LOW_SAMPLE_THRESHOLD (20)
        universe_id=1,
        universe_name="Test",
        ticker_count=10,
        start_date=date(2025, 6, 1),
        end_date=date(2026, 5, 31),
        max_hold_sessions=10,
    )
    assert "⚠*" in md


def test_render_markdown_no_low_sample_flag_above_threshold():
    from scripts.run_backtest_comparison import _render_markdown

    md = _render_markdown(
        stats=_full_stats(total_trades=25),  # above threshold
        universe_id=1,
        universe_name="Test",
        ticker_count=10,
        start_date=date(2025, 6, 1),
        end_date=date(2026, 5, 31),
        max_hold_sessions=10,
    )
    assert "⚠*" not in md


def test_render_markdown_findings_positive_expectancy():
    from scripts.run_backtest_comparison import (
        SCANNERS,
        STRATEGY_DEFINITIONS,
        _render_markdown,
    )

    stats = {}
    for scanner in SCANNERS:
        for defn in STRATEGY_DEFINITIONS:
            if (
                scanner == "trend_pullback"
                and defn["name"] == "backtest-tight-2pct-2to1"
            ):
                stats[(scanner, defn["name"])] = {
                    "total_trades": 30,
                    "win_rate": 0.6,
                    "profit_factor": 2.0,
                    "expectancy_r": 0.5,
                    "max_drawdown_r": -1.0,
                }
            else:
                stats[(scanner, defn["name"])] = {
                    "total_trades": 30,
                    "win_rate": 0.4,
                    "profit_factor": 0.8,
                    "expectancy_r": -0.2,
                    "max_drawdown_r": -3.0,
                }
    md = _render_markdown(
        stats=stats,
        universe_id=1,
        universe_name="Test",
        ticker_count=50,
        start_date=date(2025, 6, 1),
        end_date=date(2026, 5, 31),
        max_hold_sessions=10,
    )
    findings_section = md.split("## Findings")[1]
    assert "trend_pullback" in findings_section
    assert "backtest-tight-2pct-2to1" in findings_section


def test_render_markdown_findings_none_positive():
    from scripts.run_backtest_comparison import _render_markdown

    md = _render_markdown(
        stats=_full_stats(expectancy_r=-0.1),
        universe_id=1,
        universe_name="Test",
        ticker_count=10,
        start_date=date(2025, 6, 1),
        end_date=date(2026, 5, 31),
        max_hold_sessions=10,
    )
    assert "No combos with positive expectancy" in md


def test_render_markdown_pre_market_note_present():
    from scripts.run_backtest_comparison import _render_markdown

    md = _render_markdown(
        stats=_full_stats(),
        universe_id=1,
        universe_name="Test",
        ticker_count=10,
        start_date=date(2025, 6, 1),
        end_date=date(2026, 5, 31),
        max_hold_sessions=10,
    )
    assert "pre_market_volume_spike" in md.split("## Expectancy")[0]  # note in preamble
