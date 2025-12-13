"""
Stock Scanner Backend API
FastAPI-based REST API for stock scanning and alert system
"""

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from celery import Celery

# Celery Configuration
CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Initialize Celery
celery = Celery("stockscanner", broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)

# Database imports
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Date, Boolean, JSON, Text, Numeric
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.dialects.postgresql import UUID
import uuid

# Financial data imports
from polygon import RESTClient
import pandas as pd
import numpy as np

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://username:password@localhost/stockscanner")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")

# Initialize Polygon client
polygon_client = RESTClient(POLYGON_API_KEY) if POLYGON_API_KEY else None

# Database setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Models
class StockUniverse(Base):
    __tablename__ = "stock_universes"
    
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    criteria = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)

class MonitoredStock(Base):
    __tablename__ = "monitored_stocks"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    company_name = Column(String(200))
    sector = Column(String(100))
    industry = Column(String(100))
    market_cap = Column(Numeric)
    universe_id = Column(Integer, index=True)
    added_date = Column(Date, nullable=False)
    last_scanned = Column(DateTime)
    scan_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True, index=True)
    stock_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class VolumeEvent(Base):
    __tablename__ = "volume_events"
    
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    event_date = Column(Date, nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    pre_market_volume = Column(Numeric, nullable=False)
    regular_volume = Column(Numeric)
    avg_volume_20d = Column(Numeric, nullable=False)
    avg_volume_50d = Column(Numeric)
    relative_volume = Column(Numeric, nullable=False)
    volume_spike_ratio = Column(Numeric, nullable=False)
    previous_close = Column(Numeric, nullable=False)
    pre_market_high = Column(Numeric)
    pre_market_low = Column(Numeric)
    opening_price = Column(Numeric)
    closing_price = Column(Numeric)
    price_change_pct = Column(Numeric)
    price_gap_pct = Column(Numeric)
    criteria_met = Column(JSON, nullable=False)
    news_count = Column(Integer, default=0)
    earnings_date = Column(Date)
    market_cap_at_event = Column(Numeric)
    raw_data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ScannerConfig(Base):
    __tablename__ = "scanner_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    scanner_type = Column(String(50), nullable=False)
    parameters = Column(JSON, nullable=False)
    criteria = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=True)
    run_frequency = Column(String(20))
    last_run = Column(DateTime)
    next_run = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Pydantic Models
class StockUniverseCreate(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    criteria: Dict[str, Any]

class StockUniverseUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    criteria: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None

class StockUniverseResponse(BaseModel):
    id: int
    uuid: uuid.UUID
    name: str
    description: Optional[str]
    criteria: Dict[str, Any]
    created_at: datetime
    is_active: bool

class ScannerRunRequest(BaseModel):
    universe_id: Optional[int] = None
    tickers: Optional[List[str]] = None
    scanner_type: str = "pre_market_volume"
    dry_run: bool = False

class ScannerRunResponse(BaseModel):
    scan_id: str
    status: str
    stocks_scanned: int
    events_detected: int
    execution_time_ms: int

class VolumeEventResponse(BaseModel):
    id: int
    uuid: uuid.UUID
    ticker: str
    event_date: date
    event_type: str
    pre_market_volume: float
    avg_volume_20d: float
    relative_volume: float
    volume_spike_ratio: float
    price_gap_pct: float
    criteria_met: Dict[str, Any]
    created_at: datetime

class MonitoredStockResponse(BaseModel):
    id: int
    ticker: str
    company_name: Optional[str]
    sector: Optional[str]
    market_cap: Optional[float]
    added_date: date
    is_active: bool

    class Config:
        from_attributes = True

# Common stocks for scanning (Mock "All Stocks" source)
# In production, this would be replaced by a real market screener API
COMMON_STOCKS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "BRK-B", "TSM", "UNH",
    "JNJ", "JPM", "V", "PG", "MA", "HD", "CVX", "MRK", "ABBV", "PEP",
    "KO", "LLY", "BAC", "COST", "AVGO", "TMO", "DIS", "WMT", "CSCO", "ACN"
]

# FastAPI App
app = FastAPI(
    title="Stock Scanner API",
    description="Professional stock scanning and alert system",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Stock Data Service
class StockDataService:
    @staticmethod
    async def get_historical_data(ticker: str, period: str = "30d") -> pd.DataFrame:
        """Get historical stock data from Polygon.io"""
        try:
            if not polygon_client:
                logging.error("Polygon client not initialized - check POLYGON_API_KEY")
                return pd.DataFrame()
            
            # Convert period to days
            days = int(period.replace("d", "")) if "d" in period else 30
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # Fetch daily aggregates from Polygon
            aggs = polygon_client.get_aggs(
                ticker=ticker.upper(),
                multiplier=1,
                timespan="day",
                from_=start_date.strftime("%Y-%m-%d"),
                to=end_date.strftime("%Y-%m-%d"),
                limit=50000
            )
            
            if not aggs:
                return pd.DataFrame()
            
            # Convert to DataFrame
            data = []
            for agg in aggs:
                data.append({
                    'Date': datetime.fromtimestamp(agg.timestamp / 1000),
                    'Open': agg.open,
                    'High': agg.high,
                    'Low': agg.low,
                    'Close': agg.close,
                    'Volume': agg.volume
                })
            
            df = pd.DataFrame(data)
            df.set_index('Date', inplace=True)
            return df
            
        except Exception as e:
            logging.error(f"Error fetching data for {ticker}: {e}")
            return pd.DataFrame()
    
    @staticmethod
    async def get_pre_market_data(ticker: str) -> Dict[str, Any]:
        """Get pre-market data from Polygon.io"""
        try:
            if not polygon_client:
                logging.error("Polygon client not initialized - check POLYGON_API_KEY")
                return {}
            
            today = datetime.now()
            
            # Fetch minute-level data for extended hours
            aggs = polygon_client.get_aggs(
                ticker=ticker.upper(),
                multiplier=1,
                timespan="minute",
                from_=today.strftime("%Y-%m-%d"),
                to=today.strftime("%Y-%m-%d"),
                limit=50000
            )
            
            if not aggs:
                return {}
            
            # Filter for pre-market hours (4:00 AM - 9:30 AM ET)
            pre_market_data = []
            for agg in aggs:
                agg_time = datetime.fromtimestamp(agg.timestamp / 1000)
                hour = agg_time.hour
                minute = agg_time.minute
                
                # Pre-market: 4:00 AM to 9:30 AM
                if (hour >= 4 and hour < 9) or (hour == 9 and minute < 30):
                    pre_market_data.append(agg)
            
            if not pre_market_data:
                return {}
            
            return {
                "pre_market_volume": sum(agg.volume for agg in pre_market_data),
                "pre_market_high": max(agg.high for agg in pre_market_data),
                "pre_market_low": min(agg.low for agg in pre_market_data),
                "pre_market_open": pre_market_data[0].open if pre_market_data else None
            }
            
        except Exception as e:
            logging.error(f"Error fetching pre-market data for {ticker}: {e}")
            return {}
    
    @staticmethod
    async def get_stock_info(ticker: str) -> Dict[str, Any]:
        """Get stock details from Polygon.io"""
        try:
            if not polygon_client:
                logging.error("Polygon client not initialized - check POLYGON_API_KEY")
                return {}
            
            details = polygon_client.get_ticker_details(ticker.upper())
            
            if not details:
                return {}
            
            return {
                "longName": details.name,
                "shortName": details.name,
                "sector": getattr(details, 'sic_description', '') or '',
                "industry": getattr(details, 'sic_description', '') or '',
                "marketCap": getattr(details, 'market_cap', None),
                "currentPrice": None  # Will be fetched from latest quote if needed
            }
            
        except Exception as e:
            logging.error(f"Error fetching stock info for {ticker}: {e}")
            return {}

# Scanner Service
class ScannerService:
    @staticmethod
    async def run_pre_market_scan(tickers: List[str], db: Session) -> List[Dict[str, Any]]:
        """Run pre-market volume spike scanner"""
        results = []
        
        for ticker in tickers:
            try:
                # Get historical data
                hist_data = await StockDataService.get_historical_data(ticker, "60d")
                
                if hist_data.empty:
                    continue
                
                # Calculate metrics
                avg_volume_20d = hist_data['Volume'].rolling(20).mean().iloc[-1]
                avg_volume_50d = hist_data['Volume'].rolling(50).mean().iloc[-1]
                
                # Get pre-market data
                pre_market_data = await StockDataService.get_pre_market_data(ticker)
                
                if not pre_market_data:
                    continue
                
                pre_market_volume = pre_market_data.get("pre_market_volume", 0)
                relative_volume = pre_market_volume / avg_volume_20d if avg_volume_20d > 0 else 0
                
                # Check criteria
                criteria_met = {
                    "volume_spike": pre_market_volume > (avg_volume_20d * 4),
                    "minimum_volume": pre_market_volume > 100000,
                    "liquidity": avg_volume_20d > 500000,
                    "low_preceding_volume": False  # To be implemented
                }
                
                # Check if all criteria are met
                if all(criteria_met.values()):
                    # Get current stock info using Polygon.io
                    info = await StockDataService.get_stock_info(ticker)
                    
                    event = {
                        "ticker": ticker,
                        "event_date": datetime.now().date(),
                        "event_type": "pre_market_volume_spike",
                        "pre_market_volume": pre_market_volume,
                        "avg_volume_20d": int(avg_volume_20d),
                        "avg_volume_50d": int(avg_volume_50d) if not pd.isna(avg_volume_50d) else None,
                        "relative_volume": round(relative_volume, 2),
                        "volume_spike_ratio": round(pre_market_volume / avg_volume_20d, 2),
                        "previous_close": float(hist_data['Close'].iloc[-1]),
                        "pre_market_high": pre_market_data.get("pre_market_high"),
                        "pre_market_low": pre_market_data.get("pre_market_low"),
                        "market_cap_at_event": info.get("marketCap"),
                        "criteria_met": criteria_met
                    }
                    
                    results.append(event)
                    
                    # Save to database
                    volume_event = VolumeEvent(**event)
                    db.add(volume_event)
                    
            except Exception as e:
                logging.error(f"Error scanning {ticker}: {e}")
                continue
        
        db.commit()
        return results

# API Endpoints
@app.post("/api/scanner/run", response_model=ScannerRunResponse)
async def run_scanner(
    request: ScannerRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Run scanner on demand"""
    start_time = datetime.now()
    
    # Get tickers to scan
    tickers = request.tickers
    if not tickers and request.universe_id:
        # Get tickers from universe
        stocks = db.query(MonitoredStock).filter(
            MonitoredStock.universe_id == request.universe_id,
            MonitoredStock.is_active == True
        ).all()
        tickers = [stock.ticker for stock in stocks]
    
    if not tickers:
        raise HTTPException(status_code=400, detail="No tickers provided or found in universe")
    
    # Run scanner
    scan_id = str(uuid.uuid4())
    results = await ScannerService.run_pre_market_scan(tickers, db)
    
    execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
    
    return ScannerRunResponse(
        scan_id=scan_id,
        status="completed",
        stocks_scanned=len(tickers),
        events_detected=len(results),
        execution_time_ms=execution_time
    )

@app.get("/api/scanner/results", response_model=List[VolumeEventResponse])
async def get_scanner_results(
    ticker: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Get scanner results with filtering"""
    query = db.query(VolumeEvent)
    
    if ticker:
        query = query.filter(VolumeEvent.ticker == ticker.upper())
    
    if event_type:
        query = query.filter(VolumeEvent.event_type == event_type)
    
    results = query.order_by(VolumeEvent.created_at.desc()).limit(limit).offset(offset).all()
    
    return results

@app.post("/api/universe/create", response_model=StockUniverseResponse)
async def create_stock_universe(
    universe: StockUniverseCreate,
    db: Session = Depends(get_db)
):
    """Create a new stock universe"""
    db_universe = StockUniverse(**universe.dict())
    db.add(db_universe)
    db.commit()
    db.refresh(db_universe)
    
    return db_universe

@app.put("/api/universe/{universe_id}", response_model=StockUniverseResponse)
async def update_stock_universe(
    universe_id: int,
    universe_update: StockUniverseUpdate,
    db: Session = Depends(get_db)
):
    """Update a stock universe"""
    db_universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not db_universe:
        raise HTTPException(status_code=404, detail="Universe not found")
    
    update_data = universe_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_universe, key, value)
    
    db.commit()
    db.refresh(db_universe)
    return db_universe

@app.delete("/api/universe/{universe_id}")
async def delete_stock_universe(
    universe_id: int,
    db: Session = Depends(get_db)
):
    """Delete (soft delete) a stock universe"""
    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise HTTPException(status_code=404, detail="Universe not found")
    
    universe.is_active = False
    db.commit()
    return {"message": "Universe deleted successfully"}

@app.get("/api/universe/list", response_model=List[StockUniverseResponse])
async def list_stock_universes(
    db: Session = Depends(get_db)
):
    """List all stock universes"""
    universes = db.query(StockUniverse).filter(StockUniverse.is_active == True).all()
    return universes

@app.post("/api/universe/{universe_id}/refresh")
async def refresh_universe_stocks(
    universe_id: int,
    db: Session = Depends(get_db)
):
    """
    Refresh stocks in a universe based on criteria.
    Scans common stocks and adds those matching the universe criteria.
    """
    universe = db.query(StockUniverse).filter(StockUniverse.id == universe_id).first()
    if not universe:
        raise HTTPException(status_code=404, detail="Universe not found")
    
    # Clear existing stocks for this universe
    db.query(MonitoredStock).filter(MonitoredStock.universe_id == universe_id).delete()
    
    added_count = 0
    scanned_count = 0
    criteria = universe.criteria or {}
    
    # Get filter criteria
    min_market_cap = criteria.get("min_market_cap")
    max_market_cap = criteria.get("max_market_cap")
    target_sector = criteria.get("sector")
    min_price = criteria.get("min_price")
    max_price = criteria.get("max_price")
    
    for ticker in COMMON_STOCKS:
        scanned_count += 1
        try:
            # Fetch stock info from Polygon.io
            info = await StockDataService.get_stock_info(ticker)
            
            # Apply filters based on criteria
            should_add = True
            
            market_cap = info.get("marketCap")
            current_price = info.get("currentPrice")
            sector = info.get("sector")
            
            if min_market_cap and market_cap and market_cap < min_market_cap:
                should_add = False
            if max_market_cap and market_cap and market_cap > max_market_cap:
                should_add = False
            if target_sector and sector and target_sector.lower() not in sector.lower():
                should_add = False
            if min_price and current_price and current_price < min_price:
                should_add = False
            if max_price and current_price and current_price > max_price:
                should_add = False
            
            if should_add:
                monitored_stock = MonitoredStock(
                    ticker=ticker,
                    universe_id=universe_id,
                    added_date=datetime.now().date(),
                    is_active=True,
                    company_name=info.get("longName") or info.get("shortName") or ticker,
                    sector=sector,
                    industry=info.get("industry"),
                    market_cap=market_cap,
                    stock_metadata={"source": "auto_refresh", "current_price": current_price}
                )
                db.add(monitored_stock)
                added_count += 1
                
        except Exception as e:
            logging.warning(f"Error processing {ticker}: {e}")
            continue
    
    db.commit()
    
    return {
        "status": "completed",
        "scanned": scanned_count,
        "added": added_count,
        "message": f"Successfully refreshed universe. Added {added_count} stocks."
    }

@app.get("/api/universe/{universe_id}/stocks", response_model=List[MonitoredStockResponse])
async def get_universe_stocks(
    universe_id: int,
    db: Session = Depends(get_db)
):
    """List all stocks in a universe"""
    stocks = db.query(MonitoredStock).filter(
        MonitoredStock.universe_id == universe_id,
        MonitoredStock.is_active == True
    ).all()
    return stocks

@app.get("/api/stocks/historical/{ticker}")
async def get_historical_data(
    ticker: str,
    period: str = "30d",
    db: Session = Depends(get_db)
):
    """Get historical stock data"""
    try:
        data = await StockDataService.get_historical_data(ticker.upper(), period)
        
        if data.empty:
            raise HTTPException(status_code=404, detail="No data found for ticker")
        
        # Convert to JSON-serializable format
        data_dict = data.reset_index().to_dict('records')
        for record in data_dict:
            record['Date'] = record['Date'].strftime('%Y-%m-%d')
            for key in ['Open', 'High', 'Low', 'Close', 'Volume']:
                if key in record:
                    record[key] = float(record[key]) if pd.notna(record[key]) else None
        
        return {
            "ticker": ticker.upper(),
            "period": period,
            "data_points": len(data_dict),
            "data": data_dict
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    }

# Startup and shutdown events
@app.on_event("startup")
async def startup_event():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)
    logging.info("Database tables initialized")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup resources"""
    engine.dispose()
    logging.info("Database connection closed")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)