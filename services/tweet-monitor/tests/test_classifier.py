"""Unit tests for TweetClassifier."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone, time

import pytest

from app.classifier import TweetClassifier, ClassificationResult

clf = TweetClassifier()

PRE_MARKET = datetime(2026, 5, 26, 11, 0, tzinfo=timezone.utc)   # 11 UTC = ~06:00 ET
REGULAR = datetime(2026, 5, 26, 16, 0, tzinfo=timezone.utc)       # 16 UTC = ~11:00 ET


def _classify(text, posted_at=PRE_MARKET, tickers=None, price_levels=None, **kwargs):
    tickers = tickers or []
    price_levels = price_levels or {}
    return clf.classify(text=text, posted_at=posted_at, tickers=tickers,
                        price_levels=price_levels, **kwargs)


class TestCallout:
    def test_basic_watch(self):
        r = _classify("$AAPL on watch for break above 190", tickers=["AAPL"])
        assert r.classification == "CALLOUT"
        assert r.confidence >= 0.7

    def test_setup_with_entry(self):
        r = _classify("$TSLA setup entry 250 target 265", tickers=["TSLA"],
                      price_levels={"TSLA": {"entry": 250, "target": 265}})
        assert r.classification == "CALLOUT"
        assert r.confidence >= 0.8

    def test_morning_watch(self):
        r = _classify("morning watch $NVDA looking good", tickers=["NVDA"])
        assert r.classification == "CALLOUT"

    def test_pre_market_bonus(self):
        r_pre = _classify("$AMD on watch", tickers=["AMD"], posted_at=PRE_MARKET)
        r_reg = _classify("$AMD on watch", tickers=["AMD"], posted_at=REGULAR)
        assert r_pre.confidence > r_reg.confidence


class TestCelebration:
    def test_told_you(self):
        r = _classify("told you $AAPL was going to run! Beautiful move!")
        assert r.classification == "CELEBRATION"

    def test_nailed_it(self):
        r = _classify("nailed it on $TSLA runners still going")
        assert r.classification == "CELEBRATION"


class TestUpdate:
    def test_still_holding(self):
        r = _classify("$NVDA still holding, added at 900")
        assert r.classification == "UPDATE"

    def test_trimmed(self):
        r = _classify("trimmed $AAPL here, took half off")
        assert r.classification == "UPDATE"


class TestRetweet:
    def test_short_retweet(self):
        r = _classify("RT", is_retweet=True)
        assert r.classification == "RETWEET"
        assert r.confidence > 0.9

    def test_long_retweet_can_be_callout(self):
        r = _classify("$AAPL on watch for break above 190 setup looks great",
                      is_retweet=True, tickers=["AAPL"])
        # Long retweet with commentary should not be forced to RETWEET
        assert r.classification != "RETWEET"


class TestUnknown:
    def test_no_keywords(self):
        r = _classify("Just had a great morning coffee")
        assert r.classification == "UNKNOWN"

    def test_short_noise(self):
        r = _classify("gm")
        assert r.classification == "UNKNOWN"
        assert r.confidence < 0.5


class TestDirection:
    def test_long_direction(self):
        r = _classify("$AAPL break above 190, long setup", tickers=["AAPL"])
        assert r.direction == "long"

    def test_short_direction(self):
        r = _classify("$SPY puts setup break below 450")
        assert r.direction == "short"

    def test_ambiguous_direction(self):
        r = _classify("$AAPL on watch")
        assert r.direction is None


class TestConfidenceFactors:
    def test_price_level_boosts_confidence(self):
        no_price = _classify("$AAPL on watch", tickers=["AAPL"])
        with_price = _classify("$AAPL on watch entry 185", tickers=["AAPL"],
                               price_levels={"AAPL": {"entry": 185.0}})
        assert with_price.confidence > no_price.confidence

    def test_short_text_penalty(self):
        r = _classify("watch", tickers=[], posted_at=REGULAR)
        assert r.confidence < 0.6

    def test_conflicting_signals_penalty(self):
        # Both callout AND celebration keywords
        r = _classify("watch $AAPL setup nailed it congrats", tickers=["AAPL"])
        assert r.confidence < 0.8
