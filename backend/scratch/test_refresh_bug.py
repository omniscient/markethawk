import asyncio
from app.core.database import SessionLocal
from app.services.stock_data import StockDataService
import logging

async def test_refresh():
    logging.basicConfig(level=logging.INFO)
    db = SessionLocal()
    try:
        ticker = "YCBD"
        timespan = "hour"
        print(f"Testing refresh for {ticker} {timespan}...")
        result = await StockDataService.refresh_stock_data(db, ticker, timespan=timespan)
        print(f"Result: {result}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test_refresh())
