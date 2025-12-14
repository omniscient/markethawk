import os
import httpx
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("POLYGON_API_KEY")
url = "https://api.polygon.io/v3/reference/tickers/AAPL"  # Detail endpoint
headers = {"Authorization": f"Bearer {api_key}"}

try:
    with httpx.Client() as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

    if "results" in data:
        print("Keys in Ticker Details Object:")
        for key, value in data["results"].items():
            print(f"{key}: {value}")
    else:
        print("No results found or error:", data)
except Exception as e:
    print(f"Error: {e}")
