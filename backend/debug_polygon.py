
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("POLYGON_API_KEY")

def check_ticker_list():
    base_url = "https://api.polygon.io/v3/reference/tickers"
    url = f"{base_url}?market=stocks&active=true&limit=1"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    
    print(f"Fetching 1 ticker from list...")
    with httpx.Client() as client:
        response = client.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            return
            
        data = response.json()
        results = data.get("results", [])
        if results:
            t = results[0]
            print("\n--- Keys in List Result ---")
            for k in t.keys():
                print(k)
            print("\n--- Values ---")
            print(f"type: {t.get('type')}")
            print(f"market_cap: {t.get('market_cap')}") # Check if this exists
            print(f"name: {t.get('name')}")

if __name__ == "__main__":
    if not API_KEY:
        print("POLYGON_API_KEY not found in env")
    else:
        check_ticker_list()
