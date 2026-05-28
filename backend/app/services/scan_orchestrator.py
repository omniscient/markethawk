import json
import uuid as _uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from typing import Any, Awaitable, Callable, Optional, Tuple

import redis as _redis

ScannerFn = Callable[[list[str], Any, date], Awaitable[list[dict]]]

_REGISTRY: dict[str, "ScannerDescriptor"] = {}


@dataclass(frozen=True)
class ScannerDescriptor:
    key: str
    display_name: str
    description: str
    run: ScannerFn
    supports_date_range: bool = True


def register(descriptor: "ScannerDescriptor") -> "ScannerDescriptor":
    _REGISTRY[descriptor.key] = descriptor
    return descriptor


def get_all() -> list["ScannerDescriptor"]:
    return list(_REGISTRY.values())


async def run(
    scanner_type: str,
    tickers: list[str],
    db: Any,
    event_date: date,
    scanner_run: Optional[Any] = None,
) -> list[dict]:
    descriptor = _REGISTRY.get(scanner_type)
    if descriptor is None:
        raise ValueError(
            f"Unknown scanner type: {scanner_type!r}. Registered: {list(_REGISTRY)}"
        )
    return await descriptor.run(tickers, db, event_date, scanner_run=scanner_run)


def compute_next_run(scanner_type: str) -> Optional[datetime]:
    """Return next scheduled fire time, or None if scanner_type is not scheduled."""
    if scanner_type not in {"liquidity_hunt", "liquidity_hunt_pre", "liquidity_hunt_post"}:
        return None
    now = datetime.now(timezone.utc)
    candidate = now.replace(minute=0, second=0, microsecond=0, hour=2)
    if candidate <= now:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def get_scan_progress(
    redis_url: str,
    universe_id: int,
    scanner_type: str,
) -> Optional[dict]:
    """Return the Redis progress payload for an in-flight scan, or None."""
    try:
        r = _redis.Redis.from_url(redis_url, decode_responses=True)
        state = r.get(f"universe:{universe_id}:scan:{scanner_type}")
        return json.loads(state) if state else None
    except Exception:
        return None


def request_scan_cancel(redis_url: str, scan_id: str) -> None:
    """Set the Redis cancel flag that the worker polls at each day boundary."""
    r = _redis.Redis.from_url(redis_url, decode_responses=True)
    r.set(f"scan_cancel:{scan_id}", "1", ex=3600)


def enqueue_scan(db: Any, request: Any) -> Tuple[Any, Any]:
    """Create a ScannerRun row and dispatch the Celery task.

    Returns (scanner_run, async_result).
    Raises ValueError if universe has no active tickers.
    The concurrency guard (check_concurrency / 409) stays in the router because
    it raises HTTPException — a FastAPI concern not appropriate in the service layer.
    """
    from app.tasks import run_universe_scan
    from app.models.scanner_run import ScannerRun
    from app.services.scanner import ScannerService

    start_date, end_date = ScannerService.resolve_date_range(
        request.start_date, request.end_date
    )
    ticker_count = ScannerService.count_active_tickers(db, request.universe_id)
    if ticker_count == 0:
        raise ValueError("No tickers found in the selected universe")

    scan_id = str(_uuid.uuid4())
    scanner_run = ScannerRun(
        uuid=_uuid.UUID(scan_id),
        scanner_type=request.scanner_type,
        universe_id=request.universe_id,
        status="queued",
        stocks_scanned=ticker_count,
        scan_start_date=start_date,
        scan_end_date=end_date,
    )
    db.add(scanner_run)
    db.commit()
    db.refresh(scanner_run)

    async_result = run_universe_scan.delay(
        scan_id=scan_id,
        scanner_type=request.scanner_type,
        universe_id=request.universe_id,
        start_date_iso=start_date.isoformat(),
        end_date_iso=end_date.isoformat(),
    )

    scanner_run.celery_task_id = async_result.id
    db.commit()
    return scanner_run, async_result
