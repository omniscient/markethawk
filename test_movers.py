import requests
import json

def test_movers():
    url = "http://localhost:8000/api/scanner/movers/pre-market"
    try:
        response = requests.get(url, params={"min_volume": 1000, "limit": 5})
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Status: {data['status']}")
            print(f"Movers Count: {len(data['movers'])}")
            for mover in data['movers']:
                print(f"- {mover['ticker']}: {mover['price']} ({mover['change_percent']:.2f}%) Vol: {mover['volume']}")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    test_movers()
