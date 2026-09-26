"""
Cross-process rolling-window health record for external market-data providers.

#388 / ADR-0013. Every Polygon REST call made through MassiveDataProvider records
its outcome and latency here, and POLYGON_BREAKER state changes are recorded per
process ("hostname:pid") by HealthRecordingListener. State lives in Redis as
TTL-bounded per-minute buckets — ephemeral by design, never durable state — so a
Celery scan can read a signal produced by the API process, the universe
orchestrator, or another worker. (Circuit-breaker state itself is in-process per
worker; see core/circuit_breakers.py.)

Every Redis touch is wrapped: health recording must never break or slow a
provider call. After a Redis error, writes pause for _REDIS_BACKOFF_SECONDS.
"""

import json
import logging
import os
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional, Tuple

from app.core.cache import get_redis
from app.core.circuit_breakers import POLYGON_BREAKER
from app.core.config import settings
from app.core.metrics import (
    polygon_ws_connected,
    provider_circuit_breaker_state,
    provider_error_rate,
    provider_request_latency_p95_seconds,
)

logger = logging.getLogger(__name__)

_KEY_PREFIX = "mh:provider_health"
_BUCKET_SECONDS = 60
# Upper bounds (seconds) of the latency histogram buckets; one extra +Inf bucket.
LATENCY_BUCKETS: Tuple[float, ...] = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
# Reported p95 when the 95th percentile lands in the +Inf bucket (> 30 s).
_OVERFLOW_LATENCY_SECONDS = 60.0
BREAKER_STATE_RANK = {"closed": 0, "half-open": 1, "open": 2}
_BREAKER_KEY_TTL_SECONDS = 3600
_REDIS_BACKOFF_SECONDS = 30.0
_redis_backoff_until = 0.0


def worker_id() -> str:
    """Identify this process in health records and quality-gate detail."""
    return f"{socket.gethostname()}:{os.getpid()}"


def _calls_key(provider: str, bucket_start: int) -> str:
    return f"{_KEY_PREFIX}:{provider}:calls:{bucket_start}"


def _breaker_key(provider: str) -> str:
    return f"{_KEY_PREFIX}:{provider}:breaker"


def _latency_field(latency_s: float) -> str:
    for i, bound in enumerate(LATENCY_BUCKETS):
        if latency_s <= bound:
            return f"lat_{i}"
    return f"lat_{len(LATENCY_BUCKETS)}"


def _writable_redis():
    if time.monotonic() < _redis_backoff_until:
        return None
    return get_redis()


def _note_redis_failure(exc: Exception, what: str) -> None:
    global _redis_backoff_until
    _redis_backoff_until = time.monotonic() + _REDIS_BACKOFF_SECONDS
    logger.warning(
        "provider_health: %s failed; pausing health writes for %.0fs: %s",
        what,
        _REDIS_BACKOFF_SECONDS,
        exc,
    )


def record_provider_call(
    provider: str,
    endpoint: str,
    ok: bool,
    latency_s: float,
    now: Optional[float] = None,
) -> None:
    """Add one request outcome to the current minute bucket. Never raises."""
    r = _writable_redis()
    if r is None:
        return
    ts = time.time() if now is None else now
    bucket_start = int(ts // _BUCKET_SECONDS) * _BUCKET_SECONDS
    key = _calls_key(provider, bucket_start)
    ttl = (
        max(
            settings.PROVIDER_HEALTH_ERROR_WINDOW_SECONDS,
            settings.PROVIDER_HEALTH_LATENCY_WINDOW_SECONDS,
        )
        + 2 * _BUCKET_SECONDS
    )
    try:
        pipe = r.pipeline(transaction=False)
        pipe.hincrby(key, "total", 1)
        if not ok:
            pipe.hincrby(key, "errors", 1)
        pipe.hincrby(key, _latency_field(latency_s), 1)
        pipe.expire(key, ttl)
        pipe.execute()
    except Exception as exc:
        _note_redis_failure(exc, f"record {provider}/{endpoint}")


@contextmanager
def track_provider_call(
    provider: str,
    endpoint: str,
    is_failure: Callable[[BaseException], bool] = lambda exc: True,
) -> Iterator[None]:
    """Time the wrapped provider request and record its outcome.

    Exceptions propagate unchanged. ``is_failure`` lets callers exclude
    permanent, request-specific errors (Polygon NOT_AUTHORIZED plan limits)
    from the error rate — the same exclusion the circuit breaker applies.
    """
    start = time.monotonic()
    try:
        yield
    except Exception as exc:
        record_provider_call(
            provider,
            endpoint,
            ok=not is_failure(exc),
            latency_s=time.monotonic() - start,
        )
        raise
    record_provider_call(
        provider, endpoint, ok=True, latency_s=time.monotonic() - start
    )


def record_breaker_state(
    provider: str, state: str, now: Optional[float] = None
) -> None:
    """Record this process's breaker state ("closed"/"half-open"/"open"). Never raises."""
    r = _writable_redis()
    if r is None:
        return
    ts = time.time() if now is None else now
    try:
        r.hset(
            _breaker_key(provider),
            worker_id(),
            json.dumps({"state": state, "ts": ts}),
        )
        r.expire(_breaker_key(provider), _BREAKER_KEY_TTL_SECONDS)
    except Exception as exc:
        _note_redis_failure(exc, f"record {provider} breaker state")


@dataclass
class ProviderHealthSnapshot:
    provider: str
    calls_error_window: int = 0
    errors_error_window: int = 0
    error_rate: float = 0.0
    calls_latency_window: int = 0
    latency_p95_seconds: Optional[float] = None
    breaker_state: str = "closed"
    breaker_open_workers: List[str] = field(default_factory=list)
    redis_available: bool = True


def _p95_from_buckets(counts: List[int]) -> Optional[float]:
    """Upper bound of the LATENCY_BUCKETS bucket the 95th percentile falls in.

    The value is quantised, never interpolated: a real p95 anywhere in
    (2.5s, 5.0s] is reported as exactly 5.0. Consumers must therefore compare
    with ``>`` (see provider_degradation.assess_provider_health and the
    ``polygon-latency-elevated`` Grafana rule), not ``>=``.
    """
    total = sum(counts)
    if total == 0:
        return None
    target = 0.95 * total
    cumulative = 0
    for i, count in enumerate(counts):
        cumulative += count
        if cumulative >= target:
            if i < len(LATENCY_BUCKETS):
                return LATENCY_BUCKETS[i]
            return _OVERFLOW_LATENCY_SECONDS
    return _OVERFLOW_LATENCY_SECONDS


def _merge_breaker_states(
    raw: Optional[dict], now: float, reset_timeout: float
) -> Tuple[str, List[str]]:
    worst = "closed"
    open_workers: List[str] = []
    for wid, payload in (raw or {}).items():
        try:
            entry = json.loads(payload)
            state = str(entry["state"])
            age = now - float(entry["ts"])
        except (ValueError, KeyError, TypeError):
            continue
        if age > settings.PROVIDER_HEALTH_ERROR_WINDOW_SECONDS:
            continue  # process gone or idle — its state says nothing current
        if state == "open" and age > reset_timeout:
            state = "half-open"  # pybreaker would admit a trial call by now
        if state == "open":
            open_workers.append(wid)
        if BREAKER_STATE_RANK.get(state, 0) > BREAKER_STATE_RANK[worst]:
            worst = state
    return worst, sorted(open_workers)


def get_provider_health(
    provider: str = "polygon", now: Optional[float] = None
) -> ProviderHealthSnapshot:
    """Aggregate the rolling windows + per-process breaker states. Never raises."""
    snap = ProviderHealthSnapshot(provider=provider)
    ts = time.time() if now is None else now
    error_window = settings.PROVIDER_HEALTH_ERROR_WINDOW_SECONDS
    latency_window = settings.PROVIDER_HEALTH_LATENCY_WINDOW_SECONDS
    min_calls = settings.PROVIDER_HEALTH_MIN_CALLS
    current = int(ts // _BUCKET_SECONDS) * _BUCKET_SECONDS
    n_buckets = max(error_window, latency_window) // _BUCKET_SECONDS
    starts = [current - i * _BUCKET_SECONDS for i in range(n_buckets)]

    results = None
    r = get_redis()
    if r is not None:
        try:
            pipe = r.pipeline(transaction=False)
            for start in starts:
                pipe.hgetall(_calls_key(provider, start))
            pipe.hgetall(_breaker_key(provider))
            results = pipe.execute()
        except Exception as exc:
            logger.warning("provider_health: read failed for %s: %s", provider, exc)

    if results is None:
        snap.redis_available = False
    else:
        latency_counts = [0] * (len(LATENCY_BUCKETS) + 1)
        for start, bucket in zip(starts, results[:-1]):
            if not bucket:
                continue
            age = current - start
            total = int(bucket.get("total", 0))
            if age < error_window:
                snap.calls_error_window += total
                snap.errors_error_window += int(bucket.get("errors", 0))
            if age < latency_window:
                snap.calls_latency_window += total
                for i in range(len(latency_counts)):
                    latency_counts[i] += int(bucket.get(f"lat_{i}", 0))
        if snap.calls_error_window >= min_calls:
            snap.error_rate = snap.errors_error_window / snap.calls_error_window
        if snap.calls_latency_window >= min_calls:
            snap.latency_p95_seconds = _p95_from_buckets(latency_counts)
        # Only Polygon is instrumented today, so its reset timeout applies.
        snap.breaker_state, snap.breaker_open_workers = _merge_breaker_states(
            results[-1], ts, settings.POLYGON_CB_RESET_TIMEOUT
        )

    # Fast path: this process's own breaker, readable even without Redis.
    if provider == "polygon" and POLYGON_BREAKER.current_state == "open":
        snap.breaker_state = "open"
        me = worker_id()
        if me not in snap.breaker_open_workers:
            snap.breaker_open_workers.append(me)
    return snap


def refresh_provider_health_gauges(
    ws_connected: Optional[bool], provider: str = "polygon"
) -> ProviderHealthSnapshot:
    """Set the provider-health gauges from a fresh snapshot (called at /metrics scrape).

    ``ws_connected`` is StockWebSocketManager.feed_status(): None when the
    per-ticker stream is disabled by configuration (exported as -1).
    """
    snap = get_provider_health(provider)
    provider_error_rate.labels(provider=provider).set(snap.error_rate)
    provider_request_latency_p95_seconds.labels(provider=provider).set(
        snap.latency_p95_seconds or 0.0
    )
    provider_circuit_breaker_state.labels(provider=provider).set(
        BREAKER_STATE_RANK.get(snap.breaker_state, 0)
    )
    polygon_ws_connected.set(-1 if ws_connected is None else int(ws_connected))
    return snap
