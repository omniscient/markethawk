from app.services.scan_enrichment import (
    _SECTOR_ETF_MAP,
    _SECTOR_ETF_SYMBOLS,
    _get_batch_enrichment_data,
    _get_batch_enrichment_data_impl,
)


def test_sector_etf_map_has_technology():
    assert _SECTOR_ETF_MAP["Technology"] == "XLK"


def test_sector_etf_symbols_is_list():
    assert isinstance(_SECTOR_ETF_SYMBOLS, list)
    assert "XLK" in _SECTOR_ETF_SYMBOLS


def test_enrichment_functions_are_callable():
    assert callable(_get_batch_enrichment_data)
    assert callable(_get_batch_enrichment_data_impl)
