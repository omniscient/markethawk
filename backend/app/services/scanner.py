"""
Scanner Service - Pre-market volume scanning logic.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List

import pandas as pd
from sqlalchemy.orm import Session

import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.models.volume_event import VolumeEvent
from app.models.stock_aggregate import StockAggregate
from app.models.monitored_stock import MonitoredStock
from app.services.stock_data import StockDataService


class ScannerService:
    """Service for running stock scanners."""

    @staticmethod
    async def run_liquidity_hunt_scan(
        tickers: List[str], db: Session
    ) -> List[Dict[str, Any]]:
        """
        Run Pre-market Liquidity Hunt scan using DB Aggregates across all history.
        Strategy: High pre-market activity + price spike + retrace to origin.
        Optimized to use stock_aggregates table and scan entire available timeline.
        """
        results = []
        
        try:
            # Step 1: Find all (ticker, date) combinations with high pre-market volume
            # func.date() works in both SQLite and Postgres to extract the date portion.
            
            candidates = (
                db.query(
                    StockAggregate.ticker,
                    func.date(StockAggregate.timestamp).label('event_date'),
                    func.sum(StockAggregate.volume).label('total_vol'),
                    func.max(StockAggregate.high).label('high_price'),
                    func.max(StockAggregate.timestamp).label('last_pre_market_time')
                )
                .filter(
                    StockAggregate.is_pre_market == True,
                    StockAggregate.ticker.in_(tickers)
                )
                .group_by(StockAggregate.ticker, func.date(StockAggregate.timestamp))
                .having(func.sum(StockAggregate.volume) > 50000)
                .all()
            )

            # Pre-fetch market caps to avoid per-iteration queries
            monitored_stocks = db.query(MonitoredStock.ticker, MonitoredStock.market_cap).filter(MonitoredStock.ticker.in_(tickers)).all()
            market_cap_map = {ms.ticker: ms.market_cap for ms in monitored_stocks}

            for cand in candidates:
                ticker = cand.ticker
                raw_event_date = cand.event_date
                
                # Ensure we have a date object
                if isinstance(raw_event_date, str):
                    try:
                        event_date = datetime.strptime(raw_event_date, '%Y-%m-%d').date()
                    except ValueError:
                        from dateutil.parser import parse
                        event_date = parse(raw_event_date).date()
                else:
                    event_date = raw_event_date

                pre_market_volume = float(cand.total_vol)
                pre_market_high = float(cand.high_price)
                last_time = cand.last_pre_market_time
                
                # Start of the event day for relative lookups
                day_start = datetime.combine(event_date, datetime.min.time())

                # Step 2: Get specific price points needed for logic
                
                # A. Current/Last Pre-market Price (at the end of pre-market for that day)
                current_price_row = (
                    db.query(StockAggregate.close)
                    .filter(
                        StockAggregate.ticker == ticker,
                        StockAggregate.timestamp == last_time
                    )
                    .first()
                )
                current_price = float(current_price_row[0]) if current_price_row else 0

                # B. Previous Close (last candle strictly before this day's pre-market start)
                prev_close_row = (
                    db.query(StockAggregate.close)
                    .filter(
                        StockAggregate.ticker == ticker,
                        StockAggregate.timestamp < day_start
                    )
                    .order_by(desc(StockAggregate.timestamp))
                    .limit(1)
                    .first()
                )
                previous_close = float(prev_close_row[0]) if prev_close_row else 0
                
                if previous_close == 0:
                    continue

                # --- NEW: Accumulation Phase Filter & Volume Filter ---
                # Check if the stock was "calm" in the 20 sessions preceding the event
                # AND check if the volume is significantly higher than recent average.
                hist_data = (
                    db.query(StockAggregate.close, StockAggregate.volume)
                    .filter(
                        StockAggregate.ticker == ticker,
                        StockAggregate.timestamp < day_start,
                        StockAggregate.is_pre_market == False
                    )
                    .order_by(desc(StockAggregate.timestamp))
                    .limit(20)
                    .all()
                )
                
                if len(hist_data) < 5: # Need at least a week of history
                    is_accumulating = True 
                    is_significant_volume = True # Default to true if not enough history
                else:
                    closes = [float(h[0]) for h in hist_data]
                    volumes = [float(h[1]) for h in hist_data]
                    
                    # 1. Accumulation Check
                    min_close = min(closes)
                    max_close = max(closes)
                    run_up_ratio = previous_close / min_close
                    drop_ratio = previous_close / max_close
                    is_accumulating = (run_up_ratio < 1.15) and (drop_ratio > 0.85)

                    # 2. Volume Significance Check (Last 2 sessions)
                    # We need at least 2 sessions of history
                    if len(volumes) >= 2:
                        avg_vol_2d = sum(volumes[:2]) / 2
                        # The pre-market volume alone must be higher than 80% of the average DAILY volume of last 2 days
                        # Relaxed from 100% to 80% to capture borderline cases like BON 04-11 (92%)
                        is_significant_volume = pre_market_volume > (avg_vol_2d * 0.8)
                    else:
                        is_significant_volume = True

                # --- Criteria Implementation ---
                
                # 1. High Activity (Already handled in SQL HAVING clause > 50000)
                is_high_activity = True

                # 2. Price Spike
                # High > Prev Close * 1.02
                spike_threshold = previous_close * 1.02
                is_spike = pre_market_high > spike_threshold

                # 3. Retrace / Fade from High
                # Logic Update: User wants "Retrace from High".
                # We calculate how much it faded from the peak.
                # any fade > 0% is technically a retrace, but we just capture the metric.
                if pre_market_high > 0:
                    fade_from_high_pct = (pre_market_high - current_price) / pre_market_high
                else:
                    fade_from_high_pct = 0
                
                # We do NOT filter strictly on this (unless user asks later).
                # We rely on Accumulation + Volume + Spike to identify the setup.
                
                criteria_met = {
                    "high_activity": bool(is_high_activity),
                    "price_spike": bool(is_spike),
                    "accumulation_phase": bool(is_accumulating),
                    "significant_volume": bool(is_significant_volume),
                    "fade_from_high_pct": round(fade_from_high_pct, 4)
                }

                # CRITICAL: High Activity, Price Spike, Accumulation Phase AND Significant Volume.
                # We allow both breakouts (low fade) and retraces (high fade).
                if is_high_activity and is_spike and is_accumulating and is_significant_volume:
                    market_cap = market_cap_map.get(ticker)
                    
                    avg_vol_20d = sum(volumes) / len(volumes) if len(volumes) > 0 else 0
                    rel_vol = pre_market_volume / avg_vol_20d if avg_vol_20d > 0 else 0
                    
                    event = {
                        "ticker": ticker,
                        "event_date": event_date,
                        "event_type": "liquidity_hunt",
                        "pre_market_volume": pre_market_volume,
                        "avg_volume_20d": int(avg_vol_20d),
                        "relative_volume": round(rel_vol, 2),
                        "volume_spike_ratio": round(rel_vol, 2),
                        "previous_close": previous_close,
                        "pre_market_high": pre_market_high,
                        "pre_market_low": 0, 
                        "market_cap_at_event": market_cap,
                        "criteria_met": criteria_met,
                        "price_change_pct": (current_price - previous_close) / previous_close * 100,
                        "price_gap_pct": (current_price - previous_close) / previous_close * 100,
                    }


                    # Store event in DB if it doesn't exist
                    existing_event = db.query(VolumeEvent).filter(
                        VolumeEvent.ticker == ticker,
                        VolumeEvent.event_date == event_date,
                        VolumeEvent.event_type == "liquidity_hunt"
                    ).first()

                    if not existing_event:
                        volume_event = VolumeEvent(**event)
                        db.add(volume_event)
                        db.flush() # Generate ID
                        event['id'] = volume_event.id
                    else:
                        # Update existing if it was a placeholder
                        if float(existing_event.avg_volume_20d) == 0:
                            existing_event.avg_volume_20d = event['avg_volume_20d']
                            existing_event.relative_volume = event['relative_volume']
                            existing_event.volume_spike_ratio = event['volume_spike_ratio']
                            existing_event.price_change_pct = event['price_change_pct']
                            existing_event.price_gap_pct = event['price_gap_pct']
                            existing_event.market_cap_at_event = event['market_cap_at_event']
                            existing_event.criteria_met = event['criteria_met']
                        event['id'] = existing_event.id
                    
                    results.append(event)

        except Exception as e:
            logging.error(f"Error in historical liquidity hunt scan: {e}")
            
        db.commit()
        return results

    @staticmethod
    async def run_pre_market_scan(
        tickers: List[str], db: Session
    ) -> List[Dict[str, Any]]:
        """Run pre-market volume spike scanner."""
        results = []

        for ticker in tickers:
            try:
                # Get historical data
                hist_data = await StockDataService.get_historical_data(ticker, "60d")

                if hist_data.empty:
                    continue

                # Calculate metrics
                avg_volume_20d = hist_data["Volume"].rolling(20).mean().iloc[-1]
                avg_volume_50d = hist_data["Volume"].rolling(50).mean().iloc[-1]

                # Get pre-market data
                pre_market_data = await StockDataService.get_pre_market_data(ticker)

                if not pre_market_data:
                    continue

                pre_market_volume = pre_market_data.get("pre_market_volume", 0)
                relative_volume = (
                    pre_market_volume / avg_volume_20d if avg_volume_20d > 0 else 0
                )

                # Check criteria
                criteria_met = {
                    "volume_spike": pre_market_volume > (avg_volume_20d * 4),
                    "minimum_volume": pre_market_volume > 100000,
                    "liquidity": avg_volume_20d > 500000,
                    "low_preceding_volume": False,  # To be implemented
                }

                # Check if all criteria are met
                if all(criteria_met.values()):
                    # Get current stock info using Polygon.io
                    info = await StockDataService.get_stock_info(ticker)
                    
                    previous_close = float(hist_data["Close"].iloc[-1])
                    pre_market_close = pre_market_data.get("pre_market_close")
                    current_price = pre_market_close if pre_market_close else previous_close
                    price_gap_pct = (current_price - previous_close) / previous_close * 100

                    event = {
                        "ticker": ticker,
                        "event_date": datetime.now().date(),
                        "event_type": "pre_market_volume_spike",
                        "pre_market_volume": pre_market_volume,
                        "avg_volume_20d": int(avg_volume_20d),
                        "avg_volume_50d": (
                            int(avg_volume_50d) if not pd.isna(avg_volume_50d) else None
                        ),
                        "relative_volume": round(relative_volume, 2),
                        "volume_spike_ratio": round(
                            pre_market_volume / avg_volume_20d, 2
                        ),
                        "previous_close": previous_close,
                        "pre_market_high": pre_market_data.get("pre_market_high"),
                        "pre_market_low": pre_market_data.get("pre_market_low"),
                        "market_cap_at_event": info.get("marketCap"),
                        "criteria_met": criteria_met,
                        "price_gap_pct": price_gap_pct,
                    }

                    # Save to database if it doesn't exist
                    existing_event = db.query(VolumeEvent).filter(
                        VolumeEvent.ticker == ticker,
                        VolumeEvent.event_date == event["event_date"],
                        VolumeEvent.event_type == "pre_market_volume_spike"
                    ).first()

                    if not existing_event:
                        volume_event = VolumeEvent(**event)
                        db.add(volume_event)
                        db.flush()
                        event['id'] = volume_event.id
                    else:
                        event['id'] = existing_event.id
                    
                    results.append(event)

            except Exception as e:
                logging.error(f"Error scanning {ticker}: {e}")
                continue

        db.commit()
        return results
