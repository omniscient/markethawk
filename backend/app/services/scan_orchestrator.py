from dataclasses import dataclass
from datetime import date
from typing import Any, Awaitable, Callable, Optional

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
