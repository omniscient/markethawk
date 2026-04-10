from app.core.database import SessionLocal
from app.models.stock_aggregate import StockAggregate
from sqlalchemy import func

def check_ycbd_hour():
    db = SessionLocal()
    try:
        ticker = "YCBD"
        timespan = "hour"
        multiplier = 1
        
        count = db.query(func.count(StockAggregate.id)).filter(
            StockAggregate.ticker == ticker,
            StockAggregate.timespan == timespan,
            StockAggregate.multiplier == multiplier
        ).scalar()
        
        print(f"Total {timespan} bars for {ticker}: {count}")
        
        if count > 0:
            last = db.query(StockAggregate).filter(
                StockAggregate.ticker == ticker,
                StockAggregate.timespan == timespan,
                StockAggregate.multiplier == multiplier
            ).order_by(StockAggregate.timestamp.desc()).first()
            print(f"Latest bar timestamp: {last.timestamp}")
            
    finally:
        db.close()

if __name__ == "__main__":
    check_ycbd_hour()
