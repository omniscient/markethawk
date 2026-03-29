import asyncio
import logging
import os
from app.core.database import SessionLocal
from app.services.scanner import ScannerService

# Set up logging
logging.basicConfig(level=logging.INFO)

async def test_scan():
    db = SessionLocal()
    tickers = ['JTAI', 'SGN', 'AREB', 'CETX', 'EVTV']
    print(f"Running liquidity hunt scan for: {tickers}")
    
    # Increase the threshold for the scan to find something interesting or just use the defaults
    # Actually, the method is static and doesn't take parameters for thresholds
    results = await ScannerService.run_liquidity_hunt_scan(tickers, db)
    
    print(f"Found {len(results)} events")
    for res in results[:5]:
        print(f"Ticker: {res['ticker']}, Date: {res['event_date']}, Gap: {res['gap_pct']}%, Fade: {res['fade_from_high_pct']}%")
        print(f"   RTH High: {res['regular_high']}, RTH Low: {res['regular_low']}, Total High: {res['total_day_high']}")

    db.close()

if __name__ == "__main__":
    asyncio.run(test_scan())
