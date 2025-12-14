# Polygon.io Rate Limiting Guide

## 🚨 Current Situation

You're currently **rate-limited** by Polygon.io. This happens when you exceed the free tier limit of **5 API calls per minute**.

## ⏰ What to Do Now

### **Wait Period**
- **Wait 10-15 minutes** before trying the sync again
- Polygon.io's rate limit window resets after 1 minute, but repeated violations may result in longer temporary blocks

### **Check Your Rate Limit Status**
You can check your current rate limit status by making a simple API call:

```bash
curl -H "Authorization: Bearer mhg7iNgqAkNDbuREK8Gl8Cqr7irfkoA9" \
  "https://api.polygon.io/v3/reference/tickers?limit=1&active=true"
```

If you get a response, you're no longer blocked. If you get a 429 error, wait longer.

## 📊 Polygon.io Free Tier Limits

| Plan | Rate Limit | Cost |
|------|------------|------|
| **Free** | 5 calls/min | $0 |
| **Starter** | 5 calls/min | $29/mo |
| **Developer** | Unlimited* | $99/mo |
| **Advanced** | Unlimited* | $199/mo |

*Unlimited plans recommend staying under 100 requests/second

## ✅ Updated Code (Already Applied)

I've updated the sync function to respect free tier limits:

### **Changes Made:**
1. **Batch size**: Reduced from 100 → **50 tickers**
2. **Initial wait**: **5 seconds** before first API call
3. **Between batches**: **15 seconds** sleep (5 calls/min = 1 call per 12 seconds)
4. **Retry logic**: Exponential backoff (5s → 10s → 20s)

### **Expected Performance (Free Tier):**
- **50 tickers**: ~20 seconds
- **100 tickers**: ~35 seconds
- **500 tickers**: ~3 minutes
- **1,000 tickers**: ~6 minutes
- **10,000 tickers**: ~60 minutes (1 hour)

## 🎯 Recommended Approach

### **Option 1: Sync in Small Batches (Recommended for Free Tier)**

Instead of syncing all 10,000 tickers at once, sync in smaller chunks:

1. **First sync**: Limit to 100-200 tickers to test
2. **Monitor**: Check Flower dashboard for success
3. **Gradually increase**: If successful, sync more

**How to limit sync:**
Currently, the sync will try to fetch all available tickers. To limit it, you'd need to modify the code or run multiple smaller syncs over time.

### **Option 2: Upgrade to Paid Plan**

If you need to sync large datasets frequently:
- **Developer Plan ($99/mo)**: Unlimited API calls
- Best for production use
- No rate limiting headaches

### **Option 3: Use Alternative Data Sources**

For basic ticker lists, consider:
- **Yahoo Finance**: Free, no API key required (but less reliable)
- **Alpha Vantage**: Free tier with 5 calls/min (similar to Polygon)
- **IEX Cloud**: Free tier with 50,000 messages/month

## 🔍 Monitoring Your Sync

### **Check Progress in Flower**
1. Open http://localhost:5555
2. Click **Tasks** tab
3. Look for `sync_fundamental_data` task
4. View logs and progress

### **Check Backend Logs**
```bash
docker-compose logs -f celery-worker
```

Look for these log messages:
- ✅ `"Starting fundamental data sync..."`
- ⏳ `"Waiting 5 seconds before first API call..."`
- 📊 `"Fetching batch of 50 tickers..."`
- ⏳ `"Sleeping 15 seconds to respect free tier rate limits..."`
- ✅ `"✅ Fundamental sync complete! Synced X tickers."`

### **Check for Errors**
```bash
docker-compose logs celery-worker | grep -i error
```

## 🛠 Troubleshooting

### **Still Getting 429 Errors?**

1. **Increase wait time**: Edit `discovery_service.py` and change `time.sleep(15)` to `time.sleep(30)`
2. **Reduce batch size**: Change `batch_size: int = 50` to `batch_size: int = 25`
3. **Wait longer**: If you've been rate-limited multiple times, wait 30-60 minutes

### **Sync Taking Too Long?**

This is expected on free tier. Options:
- Run sync overnight
- Upgrade to paid plan
- Sync only the tickers you actually need

### **Want to Sync Specific Tickers Only?**

Modify the code to accept a ticker list instead of fetching all:

```python
# Instead of syncing all tickers, sync only specific ones
specific_tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
service.sync_details_batch(specific_tickers)
```

## 📝 Best Practices

### **For Free Tier Users:**

1. ✅ **Run syncs during off-hours** (late night/early morning)
2. ✅ **Sync incrementally** (100-200 tickers at a time)
3. ✅ **Schedule weekly syncs** instead of daily
4. ✅ **Cache data locally** (already done in your DB)
5. ✅ **Only sync tickers you actively trade**

### **For Production:**

1. ✅ **Upgrade to paid plan** ($99/mo Developer plan)
2. ✅ **Use Celery scheduled tasks** for automated syncs
3. ✅ **Implement circuit breakers** for API failures
4. ✅ **Monitor API usage** with Flower
5. ✅ **Set up alerts** for sync failures

## 🔄 When to Run Syncs

### **Fundamental Data (Sync Fundamentals)**
- **Frequency**: Weekly or monthly
- **Best time**: Weekends or after market close
- **Why**: Company fundamentals don't change daily

### **Daily Metrics (Update Metrics)**
- **Frequency**: Daily after market close
- **Best time**: After 4:30 PM ET
- **Why**: Get latest prices, volumes, and technical indicators

## 📞 Need Help?

If you continue to have issues:
1. Check Polygon.io status: https://status.polygon.io/
2. Review your API key at: https://polygon.io/dashboard
3. Contact Polygon.io support if you believe you're incorrectly rate-limited

---

**Current Status**: ⏸️ Wait 10-15 minutes, then try syncing again with the updated code.
