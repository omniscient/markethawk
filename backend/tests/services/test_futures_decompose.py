from app.services.futures_contracts import (
    SYMBOL_EXCHANGE_MAP,
    FuturesContractService,
    _resolve_exchange,
)


def test_symbol_exchange_map_importable_from_contracts():
    assert SYMBOL_EXCHANGE_MAP["ES"] == "CME"
    assert SYMBOL_EXCHANGE_MAP["GC"] == "COMEX"


def test_resolve_exchange_importable_from_contracts():
    assert _resolve_exchange("ES") == "CME"
    assert _resolve_exchange("NQ") == "CME"


def test_futures_contract_service_callable():
    assert callable(FuturesContractService.sync_contracts)


def test_futures_aggregates_service_callable():
    from app.services.futures_aggregates import FuturesAggregatesService

    assert callable(FuturesAggregatesService._download_contract)
    assert callable(FuturesAggregatesService._download_full_history)
    assert callable(FuturesAggregatesService._fill_data_gaps)


def test_futures_rollovers_service_callable():
    from app.services.futures_rollovers import (
        FuturesRolloversService,
        _build_time_slices,
        _detect_single_rollover,
    )

    assert callable(FuturesRolloversService._detect_rollovers)
    assert callable(_detect_single_rollover)
    assert callable(_build_time_slices)


def test_build_time_slices_empty_rollovers():
    from app.services.futures_rollovers import _build_time_slices

    result = _build_time_slices(rollovers=[], first_contract="20250321")
    assert result == [(None, None, "20250321")]


def test_future_series_service_callable():
    from app.services.futures_series import FutureSeriesService

    assert callable(FutureSeriesService.get_continuous_series)
    assert callable(FutureSeriesService._get_continuous_series_with_db)


def test_symbol_exchange_map_importable_from_facade():
    from app.services.futures_data import SYMBOL_EXCHANGE_MAP as facade_map

    assert facade_map["ES"] == "CME"
    assert facade_map["GC"] == "COMEX"
