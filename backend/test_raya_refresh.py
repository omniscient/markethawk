import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.services.stock_data import StockDataService
from app.core.database import SessionLocal

async def test_refresh():
    db = SessionLocal()
    try:
        print("Starting refresh for RAYA...")
        result = await StockDataService.refresh_stock_data(
            db=db,
            ticker="RAYA",
            timespan="minute",
            period="30d"
        )
        print(f"Result: {result}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test_refresh())
