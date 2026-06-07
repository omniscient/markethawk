"""Unit tests for sync.py tasks — httpx.Client mocked per established convention."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# poll_massive_news — trading-hours guard
# ---------------------------------------------------------------------------


class TestPollMassiveNewsGuard:
    """Verify the weekday/hour guard without hitting the DB."""

    def _run_check_db_reached(self, weekday, hour, force=False):
        import app.tasks.sync as sync_module

        fake_now = MagicMock()
        fake_now.weekday.return_value = weekday
        fake_now.hour = hour

        db_called = [False]
        mock_db = MagicMock()
        mock_db.query.return_value.first.return_value = None  # no pref → early return

        def _track_session():
            db_called[0] = True
            return mock_db

        with (
            patch("app.tasks.sync.SessionLocal", side_effect=_track_session),
            patch("app.tasks.sync.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime
            sync_module.poll_massive_news.run(force=force)

        return db_called[0]

    def test_saturday_skips_db(self):
        assert not self._run_check_db_reached(weekday=5, hour=10)

    def test_sunday_skips_db(self):
        assert not self._run_check_db_reached(weekday=6, hour=10)

    def test_monday_before_2am_skips_db(self):
        assert not self._run_check_db_reached(weekday=0, hour=1)

    def test_friday_at_20_skips_db(self):
        assert not self._run_check_db_reached(weekday=4, hour=20)

    def test_force_bypasses_guard(self):
        import app.tasks.sync as sync_module

        db = MagicMock()
        db.query.return_value.first.return_value = None

        with patch("app.tasks.sync.SessionLocal", return_value=db):
            sync_module.poll_massive_news.run(force=True)

        db.query.assert_called()


# ---------------------------------------------------------------------------
# sync_tickers_batch — upsert loop
# ---------------------------------------------------------------------------


class TestSyncTickersBatch:
    def _build_client(self, results, next_url=None, status_code=200):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = {"results": results, "next_url": next_url}
        response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = response
        return mock_client

    def _run(self, results, next_url=None, status_code=200):
        import app.tasks.sync as sync_module

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        mock_client = self._build_client(results, next_url, status_code)

        def _retry_reraises(exc=None, **kw):
            raise (exc or Exception("retry"))

        with (
            patch("app.tasks.sync.SessionLocal", return_value=db),
            patch("app.tasks.sync.httpx.Client", return_value=mock_client),
            patch.object(
                sync_module.sync_tickers_batch, "retry", side_effect=_retry_reraises
            ),
        ):
            sync_module.sync_tickers_batch.run()

        return db, mock_client

    def test_upserts_ticker_row_for_each_result(self):
        results = [
            {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "active": True,
                "market": "stocks",
                "type": "CS",
                "primary_exchange": "XNAS",
            },
            {
                "ticker": "MSFT",
                "name": "Microsoft",
                "active": True,
                "market": "stocks",
                "type": "CS",
                "primary_exchange": "XNAS",
            },
        ]
        db, _ = self._run(results)
        assert db.add.call_count == 2
        db.commit.assert_called_once()

    def test_skips_result_without_ticker_field(self):
        results = [{"name": "No ticker here"}]
        db, _ = self._run(results)
        db.add.assert_not_called()

    def test_schedules_next_batch_when_next_url_present(self):
        import app.tasks.sync as sync_module

        results = [
            {
                "ticker": "AAPL",
                "name": "Apple",
                "active": True,
                "market": "stocks",
                "type": "CS",
                "primary_exchange": "X",
            }
        ]
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        next_url = "https://api.polygon.io/v3/reference/tickers?cursor=abc"
        mock_client = self._build_client(results, next_url)

        with (
            patch("app.tasks.sync.SessionLocal", return_value=db),
            patch("app.tasks.sync.httpx.Client", return_value=mock_client),
            patch.object(sync_module.sync_tickers_batch, "apply_async") as mock_apply,
        ):
            sync_module.sync_tickers_batch.run()

        mock_apply.assert_called_once()


# ---------------------------------------------------------------------------
# sync_stock_splits — dedup logic
# ---------------------------------------------------------------------------


class TestSyncStockSplits:
    def _build_client(self, results, status_code=200):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = {"results": results}
        response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = response
        return mock_client

    def _run(self, results, existing_split=None):
        import app.tasks.sync as sync_module

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing_split

        mock_client = self._build_client(results)

        def _retry_reraises(exc=None, **kw):
            raise (exc or Exception("retry"))

        with (
            patch("app.tasks.sync.SessionLocal", return_value=db),
            patch("app.tasks.sync.httpx.Client", return_value=mock_client),
            patch(
                "app.services.split_adjustment.SplitAdjustmentService.apply_all_pending",
                return_value=[],
            ),
            patch.object(
                sync_module.sync_stock_splits, "retry", side_effect=_retry_reraises
            ),
        ):
            sync_module.sync_stock_splits.run()

        return db

    def test_new_split_is_inserted(self):
        results = [
            {
                "ticker": "AAPL",
                "execution_date": "2026-05-01",
                "split_from": 1,
                "split_to": 4,
            }
        ]
        db = self._run(results, existing_split=None)
        db.add.assert_called_once()

    def test_existing_split_is_not_duplicated(self):
        results = [
            {
                "ticker": "AAPL",
                "execution_date": "2026-05-01",
                "split_from": 1,
                "split_to": 4,
            }
        ]
        existing = MagicMock()
        db = self._run(results, existing_split=existing)
        db.add.assert_not_called()

    def test_missing_required_fields_skipped(self):
        results = [{"ticker": "AAPL"}]  # missing execution_date, split_from, split_to
        db = self._run(results)
        db.add.assert_not_called()


# ---------------------------------------------------------------------------
# sync_stock_aggregates — bulk-insert path
# ---------------------------------------------------------------------------


class TestSyncStockAggregates:
    def _run(self, aggs=None, raises=None):
        import app.tasks.sync as sync_module

        db = MagicMock()
        db.query.return_value.filter.return_value.delete = MagicMock(return_value=0)

        def _retry_reraises(exc=None, **kw):
            raise (exc or Exception("retry"))

        with (
            patch("app.tasks.sync.SessionLocal", return_value=db),
            patch(
                "app.services.stock_data.StockDataService.get_aggregates",
                side_effect=raises or (lambda **kw: aggs or []),
            ),
            patch("app.utils.session.classify_session", return_value=(False, False)),
            patch.object(
                sync_module.sync_stock_aggregates, "retry", side_effect=_retry_reraises
            ),
        ):
            sync_module.sync_stock_aggregates.run(
                ticker="AAPL",
                from_date="2026-06-01",
                to_date="2026-06-05",
            )

        return db

    def test_no_aggs_returns_early_without_insert(self):
        db = self._run(aggs=[])
        db.bulk_save_objects.assert_not_called()

    def test_aggs_are_bulk_inserted(self):
        agg = {
            "timestamp": datetime(2026, 6, 2, 9, 30, tzinfo=timezone.utc),
            "open": 100.0,
            "high": 105.0,
            "low": 99.0,
            "close": 103.0,
            "volume": 50000,
            "vwap": 102.0,
            "transactions": 300,
        }
        db = self._run(aggs=[agg])
        db.bulk_save_objects.assert_called_once()
        inserted = db.bulk_save_objects.call_args[0][0]
        assert len(inserted) == 1
        assert inserted[0].ticker == "AAPL"

    def test_existing_range_deleted_before_insert(self):
        agg = {
            "timestamp": datetime(2026, 6, 2, 9, 30, tzinfo=timezone.utc),
            "open": 100.0,
            "high": 105.0,
            "low": 99.0,
            "close": 103.0,
            "volume": 50000,
            "vwap": 102.0,
            "transactions": 300,
        }
        db = self._run(aggs=[agg])
        db.query.return_value.filter.return_value.delete.assert_called_once()


# ---------------------------------------------------------------------------
# trigger_tweet_monitor — success and retry
# ---------------------------------------------------------------------------


class TestTriggerTweetMonitor:
    def test_success_returns_response_json(self):
        import app.tasks.sync as sync_module

        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {"status": "ok", "tweets": 3}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = response

        with patch("app.tasks.sync.httpx.Client", return_value=mock_client):
            result = sync_module.trigger_tweet_monitor.run()

        assert result == {"status": "ok", "tweets": 3}
        mock_client.post.assert_called_once_with("http://tweet-monitor:8000/poll")

    def test_http_error_triggers_retry(self):
        import app.tasks.sync as sync_module

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = Exception("connection refused")

        def _retry_reraises(exc=None, **kw):
            raise exc

        with (
            patch("app.tasks.sync.httpx.Client", return_value=mock_client),
            patch.object(
                sync_module.trigger_tweet_monitor, "retry", side_effect=_retry_reraises
            ),
        ):
            with pytest.raises(Exception, match="connection refused"):
                sync_module.trigger_tweet_monitor.run()
