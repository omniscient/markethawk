"""
Tests for /api/live_data endpoints.

Live-data routes proxy IBKR WebSocket streams and require an active broker
connection that is unavailable in CI. Covered at the integration level by the
docker-status agent and manual QA; unit tests are skipped here.
"""
import pytest


@pytest.mark.skip(reason="requires live IBKR connection — tested via manual QA")
def test_live_data_placeholder():
    pass
