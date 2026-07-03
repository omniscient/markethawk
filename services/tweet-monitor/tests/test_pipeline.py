"""Unit tests for SignalPipeline promotion behavior."""

import os
import sys
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.pipeline import SignalPipeline


def test_promote_persists_social_callout_explanation():
    captured = {}

    class FakeDb:
        def add(self, event):
            captured["event"] = event

        def flush(self):
            captured["event"].id = 42

        def rollback(self):
            raise AssertionError("rollback should not be called")

    signal = SimpleNamespace(
        id=7,
        tweet_id="12345",
        tweet_url="https://x.example/status/12345",
        posted_at=datetime(2026, 6, 2, 13, 30),
        full_text="$AAPL long entry 185 target 195",
        confidence=0.92,
        account=SimpleNamespace(handle="market_pro"),
        direction="long",
        tickers=["AAPL"],
        price_levels={"AAPL": {"entry": 185.0, "target": 195.0}},
        promoted=False,
        scanner_event_id=None,
        promotion_reason=None,
    )

    event_id = SignalPipeline(promotion_threshold=0.7)._promote(
        FakeDb(), signal, "AAPL"
    )

    assert event_id == 42
    explanation = captured["event"].explanation
    assert explanation["schema_version"] == "scanner_explanation.v1"
    assert "social_callout.above_confidence_threshold" in explanation[
        "criteria_passed"
    ]
    assert explanation["confidence_inputs"]["tweet_id"] == "12345"
