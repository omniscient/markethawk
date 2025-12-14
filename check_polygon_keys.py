import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("POLYGON_API_KEY")
url = "https://api.polygon.io/v3/reference/tickers?market=stocks&active=true&limit=1"
headers = {"Authorization": f"Bearer {api_key}"}

response = requests.get(url, headers=headers)
data = response.json()

if "results" in data and len(data["results"]) > 0:
    print("Keys in Ticker Object:")
    for key, value in data["results"][0].items():
        print(f"{key}: {value}")
else:
    print("No results found or error:", data)
