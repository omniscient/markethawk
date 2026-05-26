import inspect
import pytest
from live_scanner.provider import LiveDataProvider


def test_protocol_has_subscribe():
    assert hasattr(LiveDataProvider, "subscribe")


def test_protocol_has_unsubscribe():
    assert hasattr(LiveDataProvider, "unsubscribe")


def test_protocol_has_fetch_seed_data():
    assert hasattr(LiveDataProvider, "fetch_seed_data")


def test_protocol_has_disconnect():
    assert hasattr(LiveDataProvider, "disconnect")
