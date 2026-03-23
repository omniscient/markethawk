---
name: Massive API Research
description: Research tool for querying the Massive Data API (Polygon.io).
---

# Massive API Research

This skill enables the agent to research market data, ticker details, and news using the Massive API (Polygon.io).
Use this skill when you need to find information about stocks, verify API connectivity, or explore available data points.

## Tools

### `scripts/query_api.py`

A versatile Python script to interact with the API.

**Prerequisites:**
- `POLYGON_API_KEY` must be set in the project's `.env` file or environment.
- Python environment with `requests` and `python-dotenv` installed (included in project dependencies).

**Usage Patterns:**

1.  **Search for a Company/Ticker:**
    ```powershell
    python .agent/skills/massive_api_research/scripts/query_api.py search "Microsoft"
    ```

2.  **Get Ticker Details (Market Cap, Description, etc.):**
    ```powershell
    python .agent/skills/massive_api_research/scripts/query_api.py details "MSFT"
    ```

3.  **Get Latest News for a Ticker:**
    ```powershell
    python .agent/skills/massive_api_research/scripts/query_api.py news "NVDA" --limit 3
    ```

4.  **Explore Custom Endpoints:**
    Use the `custom` command to hit any Polygon endpoint (without the base URL).
    
    *Check Market Status:*
    ```powershell
    python .agent/skills/massive_api_research/scripts/query_api.py custom "/v1/marketstatus/now"
    ```
    
    *Get Aggregates (Bars):*
    ```powershell
    python .agent/skills/massive_api_research/scripts/query_api.py custom "/v2/aggs/ticker/AAPL/range/1/day/2023-01-09/2023-01-09"
    ```

## Notes

- The "Massive API" is an internal alias for **Polygon.io** in this project.
- Field mappings such as `cik`, `composite_figi` in the `TickerReference` model correspond to the response from `/v3/reference/tickers/{ticker}`.
