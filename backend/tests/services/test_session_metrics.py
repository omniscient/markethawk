from app.services.session_metrics import (
    calculate_day_metrics,
    calculate_day_metrics_from_aggs,
)


def test_calculate_day_metrics_from_aggs_empty_list():
    result = calculate_day_metrics_from_aggs([])
    assert result["pre_market_high"] == 0.0
    assert result["total_volume"] == 0


def test_calculate_day_metrics_imported_directly():
    assert callable(calculate_day_metrics)
