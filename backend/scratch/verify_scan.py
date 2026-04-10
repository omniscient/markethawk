
import asyncio
from app.core.database import SessionLocal
from app.services.scanner import ScannerService
from app.models.scanner_event import ScannerEvent

async def verify():
    db = SessionLocal()
    try:
        ticker = "YCBD"
        print(f"Running Liquidity Hunt scan for {ticker}...")
        results = await ScannerService.run_liquidity_hunt_scan([ticker], db)
        print(f"Scan complete. Found {len(results)} events.")
        for r in results:
            print(f"Date: {r['event_date']} | Summary: {r['summary']}")
            print(f"  Indicators: {r['indicators']}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(verify())
