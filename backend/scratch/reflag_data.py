
from app.core.database import SessionLocal
from sqlalchemy import text
import sys

def reflag_all_data():
    db = SessionLocal()
    try:
        print("Reflagging all minute aggregates to correct US/Eastern timezone...")
        # Postgres SQL for bulk update
        sql = """
        UPDATE stock_aggregates
        SET is_pre_market = (
            (EXTRACT(HOUR FROM timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern') >= 4 AND 
             EXTRACT(HOUR FROM timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern') < 9) OR
            (EXTRACT(HOUR FROM timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern') = 9 AND 
             EXTRACT(MINUTE FROM timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern') < 30)
        ),
        is_after_market = (
            (EXTRACT(HOUR FROM timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern') = 16 AND 
             EXTRACT(MINUTE FROM timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern') >= 1) OR
            (EXTRACT(HOUR FROM timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern') > 16 AND 
             EXTRACT(HOUR FROM timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern') < 20)
        )
        WHERE timespan = 'minute';
        """
        result = db.execute(text(sql))
        db.commit()
        print(f"✅ Success. Rows affected: {result.rowcount}")
    except Exception as e:
        print(f"❌ Error during reflagging: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    reflag_all_data()
