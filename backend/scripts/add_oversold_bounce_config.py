import uuid

from app.core.database import SessionLocal
from app.models.scanner_config import ScannerConfig


def add_config():
    db = SessionLocal()
    try:
        # Check if exists
        existing = (
            db.query(ScannerConfig)
            .filter(ScannerConfig.scanner_type == "oversold_bounce")
            .first()
        )
        if existing:
            print("Config already exists.")
            return

        config = ScannerConfig(
            uuid=uuid.uuid4(),
            name="Oversold Bounce (Dual RSI)",
            description="Looks for stocks bouncing out of extremely oversold conditions on the daily timeframe using Dual RSI (2-period and 5-period).",
            scanner_type="oversold_bounce",
            parameters={
                "rsi_period_short": 2,
                "short_rsi_trigger": 15,
                "rsi_period_long": 5,
                "long_rsi_trigger": 27,
                "min_avg_volume_3d": 500000,
                "min_prev_close": 5.0,
            },
            criteria=[
                {
                    "name": "Volume Filter",
                    "description": "3-day moving average of volume >= 500k",
                },
                {
                    "name": "Price Filter",
                    "description": "Previous day's close >= $5.00",
                },
                {
                    "name": "Short RSI (2) Cross",
                    "description": "RSI(2) was < 15 yesterday and is >= 15 today",
                },
                {
                    "name": "Long RSI (5) Cross",
                    "description": "RSI(5) was < 27 yesterday and is >= 27 today",
                },
                {
                    "name": "No Gap Down",
                    "description": "Today's open is >= yesterday's low",
                },
            ],
            is_active=True,
            run_frequency="daily",
        )

        db.add(config)
        db.commit()
        print("Successfully added oversold_bounce config.")
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    add_config()
