
import os
import sys
from datetime import datetime, timezone
from sqlalchemy import text
from app.core.database import SessionLocal

def debug_ycbd():
    db = SessionLocal()
    try:
        print("Checking YCBD aggregates...")
        # Check last 50 minute aggregates
        query = text("""
            SELECT timestamp, is_pre_market, is_after_market, volume, open, high, low, close
            FROM stock_aggregates 
            WHERE ticker = 'YCBD' AND timespan = 'minute'
            ORDER BY timestamp DESC 
            LIMIT 50
        """)
        res = db.execute(query).fetchall()
        
        if not res:
            print("No data found for YCBD")
            return

        print("Timestamp (Naive/UTC) | Pre | Post | Vol | Price")
        print("-" * 60)
        for r in res:
            print(f"{r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[7]}")
            
        print("\nChecking Liquidity Hunt Events for YCBD...")
        query_events = text("""
            SELECT event_date, summary, indicators
            FROM scanner_events
            WHERE ticker = 'YCBD' AND scanner_type = 'liquidity_hunt'
            ORDER BY event_date DESC
            LIMIT 10
        """)
        events = db.execute(query_events).fetchall()
        for e in events:
            print(f"Date: {e[0]} | Summary: {e[1]}")
            print(f"  Indicators: {e[2]}")

    except Exception as ex:
        print(f"Error: {ex}")
    finally:
        db.close()

if __name__ == "__main__":
    debug_ycbd()
