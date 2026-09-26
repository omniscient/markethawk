"""Cross-process provider health record (#388, ADR-0013)."""

import json
import time
from unittest.mock import MagicMock, PropertyMock, patch

import fakeredis
import pytest
from prometheus_client import REGISTRY

from app.core import provider_health as ph

NOW = 1_780_000_020.0  # fixed epoch seconds (20 s into a minute bucket)


@pytest.fixture
def fake_redis(monkeypatch):
    server = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(ph, "get_redis", lambda: server)
    monkeypatch.setattr(ph, "_redis_backoff_until", 0.0)
    # get_provider_health ORs in the process-global breaker; never inherit an
    # open breaker from an earlier test.
    ph.POLYGON_BREAKER.close()
    server.flushall()
    yield server
    ph.POLYGON_BREAKER.close()


def _record(n, ok=True, latency=0.05, now=NOW):
    for _ in range(n):
        ph.record_provider_call("polygon", "aggs", ok=ok, latency_s=latency, now=now)


def test_error_rate_over_window(fake_redis):
    _record(15)
    _record(5, ok=False)
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.calls_error_window == 20
    assert snap.errors_error_window == 5
    assert snap.error_rate == pytest.approx(0.25)
    assert snap.redis_available is True


def test_error_rate_zero_below_min_calls(fake_redis):
    _record(1)
    _record(1, ok=False)
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.errors_error_window == 1
    assert snap.error_rate == 0.0


def test_latency_p95_uses_bucket_upper_bound(fake_redis):
    _record(18, latency=0.05)
    _record(2, latency=3.0)
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.latency_p95_seconds == 5.0


def test_latency_p95_fast_calls(fake_redis):
    _record(19, latency=0.05)
    _record(1, latency=3.0)
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.latency_p95_seconds == 0.1


def test_latency_overflow_bucket(fake_redis):
    _record(20, latency=45.0)
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.latency_p95_seconds == 60.0


def test_old_calls_leave_error_window_but_not_latency_window(fake_redis):
    _record(20, ok=False, latency=3.0, now=NOW - 400)
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.calls_error_window == 0
    assert snap.error_rate == 0.0
    assert snap.calls_latency_window == 20
    assert snap.latency_p95_seconds == 5.0


def test_breaker_open_in_other_worker_is_seen(fake_redis):
    fake_redis.hset(
        "mh:provider_health:polygon:breaker",
        "celery-worker:42",
        json.dumps({"state": "open", "ts": NOW - 10}),
    )
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.breaker_state == "open"
    assert snap.breaker_open_workers == ["celery-worker:42"]


def test_open_entry_older_than_reset_timeout_reads_half_open(fake_redis):
    fake_redis.hset(
        "mh:provider_health:polygon:breaker",
        "api:7",
        json.dumps({"state": "open", "ts": NOW - 120}),
    )
    snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.breaker_state == "half-open"
    assert snap.breaker_open_workers == []


def test_stale_breaker_entry_ignored(fake_redis):
    fake_redis.hset(
        "mh:provider_health:polygon:breaker",
        "gone:1",
        json.dumps({"state": "open", "ts": NOW - 400}),
    )
    assert ph.get_provider_health("polygon", now=NOW).breaker_state == "closed"


def test_record_breaker_state_writes_worker_entry(fake_redis):
    ph.record_breaker_state("polygon", "open", now=NOW)
    raw = fake_redis.hgetall("mh:provider_health:polygon:breaker")
    assert ph.worker_id() in raw
    assert json.loads(raw[ph.worker_id()])["state"] == "open"


def test_local_breaker_fast_path_without_redis(monkeypatch):
    monkeypatch.setattr(ph, "get_redis", lambda: None)
    breaker_cls = type(ph.POLYGON_BREAKER)
    with patch.object(
        breaker_cls, "current_state", new_callable=PropertyMock, return_value="open"
    ):
        snap = ph.get_provider_health("polygon", now=NOW)
    assert snap.redis_available is False
    assert snap.breaker_state == "open"
    assert snap.breaker_open_workers == [ph.worker_id()]


def test_redis_failure_is_swallowed_and_backs_off(monkeypatch):
    broken = MagicMock()
    broken.pipeline.side_effect = ConnectionError("redis down")
    calls = {"n": 0}

    def _get():
        calls["n"] += 1
        return broken

    monkeypatch.setattr(ph, "get_redis", _get)
    monkeypatch.setattr(ph, "_redis_backoff_until", 0.0)
    ph.record_provider_call("polygon", "aggs", ok=True, latency_s=0.1)  # no raise
    ph.record_provider_call("polygon", "aggs", ok=True, latency_s=0.1)
    assert calls["n"] == 1  # second write skipped during backoff


def test_track_provider_call_records_failure_and_reraises(fake_redis):
    with pytest.raises(ConnectionError):
        with ph.track_provider_call("polygon", "aggs"):
            raise ConnectionError("egress blocked")
    with ph.track_provider_call("polygon", "aggs"):
        pass
    snap = ph.get_provider_health("polygon")
    assert snap.errors_error_window == 1
    assert snap.calls_error_window == 2


def test_track_provider_call_is_failure_predicate(fake_redis):
    with pytest.raises(ValueError):
        with ph.track_provider_call("polygon", "aggs", is_failure=lambda exc: False):
            raise ValueError("NOT_AUTHORIZED")
    snap = ph.get_provider_health("polygon")
    assert snap.errors_error_window == 0
    assert snap.calls_error_window == 1


def test_refresh_gauges_sets_values(fake_redis):
    fake_redis.hset(
        "mh:provider_health:polygon:breaker",
        "w:1",
        json.dumps({"state": "open", "ts": time.time()}),
    )
    ph.refresh_provider_health_gauges(ws_connected=False)
    assert (
        REGISTRY.get_sample_value(
            "provider_circuit_breaker_state", {"provider": "polygon"}
        )
        == 2
    )
    assert REGISTRY.get_sample_value("polygon_ws_connected") == 0
    ph.refresh_provider_health_gauges(ws_connected=None)
    assert REGISTRY.get_sample_value("polygon_ws_connected") == -1
