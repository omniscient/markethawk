from unittest.mock import MagicMock


def _make_empty_db():
    """Mock DB that returns zero counts and empty lists for all universe queries."""
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.scalar.return_value = 0
    mock_q.all.return_value = []
    mock_q.first.return_value = (0, None, None)
    mock_q.distinct.return_value = mock_q
    db.query.return_value = mock_q
    return db


class TestUniverseStatsServiceExists:
    def test_module_importable(self):
        from app.services.universe_stats import UniverseStatsService

        assert callable(UniverseStatsService.compute)

    def test_compute_returns_expected_keys(self):
        from app.services.universe_stats import UniverseStatsService

        result = UniverseStatsService.compute(universe_id=1, db=_make_empty_db())
        assert set(result.keys()) == {
            "ticker_count",
            "aggregate_count",
            "min_date",
            "max_date",
            "timespans",
        }

    def test_compute_empty_universe_returns_zeros(self):
        from app.services.universe_stats import UniverseStatsService

        result = UniverseStatsService.compute(universe_id=1, db=_make_empty_db())
        assert result["ticker_count"] == 0
        assert result["aggregate_count"] == 0
        assert result["min_date"] is None
        assert result["max_date"] is None
        assert result["timespans"] == []
