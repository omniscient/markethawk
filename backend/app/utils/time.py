from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


def to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
