import os
import argparse
import json
import requests
from dotenv import load_dotenv

# Load environment variables from the root .env file
# Assuming the script is run from project root, or we find the .env relatively
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))))
dotenv_path = os.path.join(project_root, ".env")
load_dotenv(dotenv_path)

API_KEY = os.getenv("POLYGON_API_KEY")
BASE_URL = "https://api.polygon.io"

def get_headers():
    if not API_KEY:
        # Fallback: try loading from .env in current directory if earlier fail
        load_dotenv() 
        if not os.getenv("POLYGON_API_KEY"):
            raise ValueError("POLYGON_API_KEY not found in environment. Please ensure .env file exists.")
    return {"Authorization": f"Bearer {os.getenv('POLYGON_API_KEY')}"}

def search_tickers(query, limit=10):
    url = f"{BASE_URL}/v3/reference/tickers"
    params = {
        "search": query,
        "active": "true",
        "limit": limit
    }
    resp = requests.get(url, params=params, headers=get_headers())
    try:
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        return {"error": str(e), "response": resp.text}

def get_ticker_details(ticker):
    url = f"{BASE_URL}/v3/reference/tickers/{ticker.upper()}"
    resp = requests.get(url, headers=get_headers())
    try:
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        return {"error": str(e), "response": resp.text}

def get_news(ticker, limit=5):
    url = f"{BASE_URL}/v2/reference/news"
    params = {"ticker": ticker.upper(), "limit": limit}
    resp = requests.get(url, params=params, headers=get_headers())
    try:
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        return {"error": str(e), "response": resp.text}

def custom_query(endpoint, method="GET", json_data=None):
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    headers = get_headers()
    if method.upper() == "GET":
        resp = requests.get(url, headers=headers)
    else:
        resp = requests.request(method, url, headers=headers, json=json_data)
        
    try:
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        return {"error": str(e), "response": resp.text}

def main():
    parser = argparse.ArgumentParser(description="Query Massive API (Polygon.io)")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Search
    search_parser = subparsers.add_parser("search", help="Search for tickers")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", type=int, default=10, help="Results limit")

    # Details
    details_parser = subparsers.add_parser("details", help="Get ticker details")
    details_parser.add_argument("ticker", help="Ticker symbol")

    # News
    news_parser = subparsers.add_parser("news", help="Get ticker news")
    news_parser.add_argument("ticker", help="Ticker symbol")
    news_parser.add_argument("--limit", type=int, default=5, help="Results limit")

    # Custom
    custom_parser = subparsers.add_parser("custom", help="Run custom endpoint")
    custom_parser.add_argument("endpoint", help="API endpoint path (e.g. /v1/marketstatus/now)")

    args = parser.parse_args()

    try:
        result = {}
        if args.command == "search":
            result = search_tickers(args.query, args.limit)
        elif args.command == "details":
            result = get_ticker_details(args.ticker)
        elif args.command == "news":
            result = get_news(args.ticker, args.limit)
        elif args.command == "custom":
            result = custom_query(args.endpoint)
        else:
            parser.print_help()
            return

        print(json.dumps(result, indent=2))
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
