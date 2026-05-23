# Polygon.io for historical market data

We chose Polygon.io as the primary historical data provider over alternatives like Alpaca, Alpha Vantage, and Yahoo Finance. Polygon's API is straightforward to integrate (clean REST endpoints, consistent OHLCV format across timespans), and multiple peers in the trading dev community recommended it for minute-level aggregate data at scale. The trade-off is cost — Polygon's paid tiers are not the cheapest — but the developer experience and data reliability outweighed price.
