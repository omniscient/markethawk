
import logging
import sys
import os
import httpx
from datetime import datetime

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app.core.database import SessionLocal
from app.models.ticker_reference import TickerReference
from app.core.config import settings

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def verify_fix_logic():
    db = SessionLocal()
    ticker = "AAPL"
    
    print(f"Running manual sync logic for {ticker}...")
    
    try:
        # 1. Fetch Data
        url = f"https://api.polygon.io/v3/reference/tickers/{ticker}"
        headers = {"Authorization": f"Bearer {settings.POLYGON_API_KEY}"}
        
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            results = data.get("results", {})
            
            # 2. Update DB
            stmt = db.query(TickerReference).filter(TickerReference.ticker == ticker).first()
            if not stmt:
                print(f"Ticker {ticker} not found in DB, creating text placeholder...")
                stmt = TickerReference(ticker=ticker)
                db.add(stmt)
            
            # --- APPLIED LOGIC FROM TASKS.PY ---
            stmt.description = results.get("description")
            stmt.market_cap = results.get("market_cap")
            stmt.primary_exchange = results.get("primary_exchange")
            stmt.list_date = results.get("list_date")
            stmt.total_employees = results.get("total_employees")
            stmt.share_class_shares_outstanding = results.get("share_class_shares_outstanding")
            stmt.weighted_shares_outstanding = results.get("weighted_shares_outstanding")
            stmt.sic_code = results.get("sic_code")
            stmt.sic_description = results.get("sic_description")
            # Map SIC description to Industry as a fallback/primary
            stmt.industry = results.get("sic_description")
            # Clear out the incorrect 'CS' sector values if present
            if stmt.sector == 'CS':
                stmt.sector = None
                
            stmt.homepage_url = results.get("homepage_url")
            stmt.last_details_update = datetime.utcnow()
            # -----------------------------------

            db.commit()
            print(f"✅ Updated details for {ticker}")

    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    
    print("Checking DB...")
    db.expire_all() # Refresh
    obj = db.query(TickerReference).filter(TickerReference.ticker == ticker).first()
    
    if obj:
        print(f"Ticker: {obj.ticker}")
        print(f"Market Cap: {obj.market_cap}")
        print(f"Industry: {obj.industry}")
        print(f"Sector: {obj.sector}")
        
        if obj.market_cap and obj.market_cap > 0 and obj.industry:
            print("SUCCESS: Market Cap and Industry populated.")
        else:
            print("FAILURE: Fields missing.")
            
        if obj.sector is None or obj.sector != 'CS':
             print("SUCCESS: Sector is cleaned (not CS).")
        else:
             print("FAILURE: Sector is still CS.")

    else:
        print("Ticker not found in DB.")
        
    db.close()

if __name__ == "__main__":
    verify_fix_logic()
