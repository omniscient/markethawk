# Polygon.io API Reference

## Plan Tiers and Rate Limits

| Plan | Rate Limit | Monthly Cost |
|------|-----------|-------------|
| Free | 5 requests / minute | $0 |
| Starter | 5 requests / minute | ~$29 |
| Developer | Unlimited (recommended stay under 100 req/s) | ~$99 |
| Advanced | Unlimited | ~$199 |

Check current pricing at https://polygon.io/pricing. Plans and prices change; the table above is approximate.

Real-time data (no delay) requires the Starter plan or above. The Free tier provides end-of-day data only.

---

## How This Project Uses the API

### Scan-time requests (scanner.py)

During a scan, the `ScannerService` fetches aggregates and quotes for each ticker in the active universe. Concurrency is bounded by an `asyncio.Semaphore(10)`, so at most 10 requests are in-flight simultaneously. On the Free tier, this will trip rate limits for universes larger than a handful of tickers. On a Developer plan it is comfortably within the 100 req/s guidance.

### Universe sync (discovery_service.py)

`DiscoveryService` paginates through Polygon's `/v3/reference/tickers` to build or refresh the full ticker reference table. This is a bulk operation and should be run infrequently (weekly or on demand). The service handles `429 Too Many Requests` with exponential backoff.

**Recommended sync batch behaviour on Free tier:**
- Batch size: 50 tickers
- Sleep between batches: 15 seconds (respects the 5-calls/min ceiling)
- Expected throughput: ~200 tickers/minute → 10,000 tickers takes ~50 minutes
- Best scheduled: overnight or weekends when it does not compete with scans

### News fetch (catalyst_parser.py)

`CatalystParser.analyze_batch()` fetches the 72-hour news window from the `news_articles` table (locally cached) rather than hitting the API on every scan. Articles are refreshed by a separate Celery task.

---

## Key Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `GET /v3/reference/tickers` | Universe sync — paginates all active tickers |
| `GET /v3/reference/tickers/{ticker}` | Per-ticker metadata (sector, market cap, CIK, FIGI) |
| `GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}` | OHLCV bars (historical and pre-market) |
| `GET /v2/last/trade/{ticker}` | Latest trade for real-time quote |
| `GET /v2/reference/news` | News articles (filtered by ticker and date) |
| `GET /v1/marketstatus/now` | Current market open/closed status |
| `GET /v2/snapshot/locale/us/markets/stocks/tickers/{ticker}` | Full snapshot (day stats, minute bars, last trade/quote) |

The `TickerReference` model fields (`cik`, `composite_figi`, `primary_exchange`, etc.) map directly to the `/v3/reference/tickers/{ticker}` response schema.

---

## Diagnosing Rate Limit Errors

A `429 Too Many Requests` response means the rate limit was exceeded. Steps:

1. Check Flower at http://localhost:5555 for failed tasks and their error messages.
2. Check Seq at http://localhost:5380 — search `StatusCode = 429` or filter by service `discovery_service`.
3. Check backend logs: `docker-compose logs celery-worker | grep 429`

If the 429 persists after a minute, Polygon may have applied a short block for repeated violations. Wait 10–15 minutes before retrying.

To reduce pressure immediately:
- In `discovery_service.py`: increase the sleep between batches or reduce `batch_size` (default 50).
- Pause the scheduled sync task in Flower until the block clears.

---

## Verifying API Connectivity

```bash
# Check market status (uses one API call)
curl -s "https://api.polygon.io/v1/marketstatus/now?apiKey=$POLYGON_API_KEY" | python -m json.tool

# Verify your key works
curl -s "https://api.polygon.io/v3/reference/tickers/AAPL?apiKey=$POLYGON_API_KEY" | python -m json.tool
```

Set `POLYGON_API_KEY` in `.env` — `docker-compose` exports it automatically.

---

## Best Practices

- **Cache aggressively.** `StockAggregate` and `TickerReference` store fetched data locally. Never re-fetch data that is already in the database and still valid.
- **Sync fundamentals weekly, not daily.** Company metadata (sector, market cap) changes rarely. Daily sync wastes quota.
- **Run bulk syncs off-hours.** Schedule `sync_fundamental_data` for nights or weekends to avoid competing with pre-market scans.
- **Monitor with Flower.** All Celery tasks that call the API are visible in Flower. Task failure rates indicate API problems early.
- **Use the `POLYGON_DELAYED` flag.** Setting `POLYGON_DELAYED=false` in `.env` tells the app your plan provides real-time data. Set it correctly to avoid stale-data bugs.
