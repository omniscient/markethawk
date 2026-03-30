from polygon import RESTClient
import os
from dotenv import load_dotenv

load_dotenv()

client = RESTClient(os.getenv("POLYGON_API_KEY"))

def inspect_snapshot():
    try:
        # Get snapshot for EEIQ specifically
        snapshot = client.get_snapshot_ticker("stocks", "EEIQ")
        print(f"Ticker: {snapshot.ticker}")
        print(f"Attributes of snapshot: {dir(snapshot)}")
        print(f"todays_change_percent: {snapshot.todays_change_percent}")
        
        if hasattr(snapshot, 'day'):
            print(f"Day: {snapshot.day}")
            print(f"Day attributes: {dir(snapshot.day)}")
            
        if hasattr(snapshot, 'min'):
            print(f"Min: {snapshot.min}")
            print(f"Min attributes: {dir(snapshot.min)}")
            # Try some common volume names
            for attr in ['v', 'volume', 'av', 'accumulated_volume', 'dav', 'daily_accumulated_volume']:
                if hasattr(snapshot.min, attr):
                    print(f"Min.{attr}: {getattr(snapshot.min, attr)}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_snapshot()
