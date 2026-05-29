from datetime import date
from typing import Any, Optional

from app.services.scan_orchestrator import ScannerDescriptor, register


async def _run(
    tickers: list[str], db: Any, event_date: date, scanner_run: Optional[Any] = None
) -> list[dict]:
    from app.services.scanner import ScannerService

    return await ScannerService.run_oversold_bounce_scan(
        tickers, db, event_date=event_date, scanner_run=scanner_run
    )


register(
    ScannerDescriptor(
        key="oversold_bounce",
        display_name="Oversold Bounce",
        description="Identifies oversold stocks showing early reversal signals.",
        run=_run,
        supports_date_range=True,
    )
)
