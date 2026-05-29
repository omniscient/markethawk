from datetime import date
from typing import Any, Optional

from app.services.scan_orchestrator import ScannerDescriptor, register


async def _run(
    tickers: list[str], db: Any, event_date: date, scanner_run: Optional[Any] = None
) -> list[dict]:
    from app.services.scanner import ScannerService

    return await ScannerService.run_pre_market_scan(
        tickers, db, event_date=event_date, scanner_run=scanner_run
    )


register(
    ScannerDescriptor(
        key="pre_market_volume_spike",
        display_name="Pre-Market Volume Spike",
        description="Detects stocks with >4x average volume in the pre-market window.",
        run=_run,
        supports_date_range=True,
    )
)
