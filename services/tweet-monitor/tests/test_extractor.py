"""Unit tests for TickerExtractor and PriceLevelExtractor."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.extractor import TickerExtractor, PriceLevelExtractor

te = TickerExtractor()
pe = PriceLevelExtractor()


class TestTickerExtractor:
    def test_basic_cashtag(self):
        tickers = te.extract("$AAPL on watch")
        assert tickers == ["AAPL"]

    def test_multiple_cashtags(self):
        tickers = te.extract("$TSLA and $NVDA both look good today")
        assert "TSLA" in tickers
        assert "NVDA" in tickers

    def test_deduplication(self):
        tickers = te.extract("$AAPL setup $AAPL break above")
        assert tickers.count("AAPL") == 1

    def test_excluded_tickers(self):
        tickers = te.extract("$SPX $VIX making moves, $AAPL watch")
        assert "SPX" not in tickers
        assert "VIX" not in tickers
        assert "AAPL" in tickers

    def test_no_cashtag(self):
        tickers = te.extract("AAPL is looking good today")
        assert tickers == []

    def test_lowercase_ignored(self):
        tickers = te.extract("$aapl on watch")
        assert tickers == []

    def test_single_letter_excluded(self):
        tickers = te.extract("$A stock on watch")
        assert "A" not in tickers

    def test_six_letter_not_matched(self):
        # Regex matches 1-5 uppercase letters after $
        tickers = te.extract("$TOOLONG setup")
        assert "TOOLONG" not in tickers

    def test_order_preserved(self):
        tickers = te.extract("$AMD entry 150 $TSLA watch 250")
        assert tickers[0] == "AMD"
        assert tickers[1] == "TSLA"


class TestPriceLevelExtractor:
    def test_entry_price(self):
        levels = pe.extract("$AAPL entry at $185.50", ["AAPL"])
        assert levels == {"AAPL": {"entry": 185.5}}

    def test_target_price(self):
        levels = pe.extract("$TSLA target 265", ["TSLA"])
        assert levels == {"TSLA": {"target": 265.0}}

    def test_stop_price(self):
        levels = pe.extract("$NVDA stop 900", ["NVDA"])
        assert levels == {"NVDA": {"stop": 900.0}}

    def test_multiple_levels(self):
        levels = pe.extract("$AAPL entry 185 target 195 stop 180", ["AAPL"])
        assert levels["AAPL"]["entry"] == 185.0
        assert levels["AAPL"]["target"] == 195.0
        assert levels["AAPL"]["stop"] == 180.0

    def test_no_tickers_returns_empty(self):
        levels = pe.extract("entry at 185", [])
        assert levels == {}

    def test_no_price_keywords_returns_empty(self):
        levels = pe.extract("$AAPL looks great today", ["AAPL"])
        assert levels == {}

    def test_decimal_price(self):
        levels = pe.extract("$AMD entry @ 150.75", ["AMD"])
        assert levels == {"AMD": {"entry": 150.75}}

    def test_dollar_sign_in_price(self):
        levels = pe.extract("$AAPL entry at $190", ["AAPL"])
        assert levels["AAPL"]["entry"] == 190.0

    def test_associates_with_primary_ticker(self):
        # Multiple tickers — prices associate with first one
        levels = pe.extract("$AAPL $TSLA entry 185 target 195", ["AAPL", "TSLA"])
        assert "AAPL" in levels
        assert "TSLA" not in levels

    def test_break_above_keyword(self):
        levels = pe.extract("$AAPL break above 190", ["AAPL"])
        assert levels.get("AAPL", {}).get("break") == pytest.approx(190.0) or \
               levels.get("AAPL", {}).get("above") == pytest.approx(190.0)
