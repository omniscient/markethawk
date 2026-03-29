"""
Scanner Service - Pre-market volume scanning logic.
"""

import logging
from datetime import datetime, date
from typing import Dict, Any, List

import pandas as pd
from sqlalchemy.orm import Session

import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_

from app.models.volume_event import VolumeEvent
from app.models.stock_aggregate import StockAggregate
from app.models.monitored_stock import MonitoredStock
from app.services.stock_data import StockDataService


class ScannerService:
    """Service for running stock scanners."""

    @staticmethod
    def calculate_day_metrics(ticker: str, event_date: date, db: Session) -> Dict[str, Any]:
        """Calculate detailed price metrics for different sessions of a given day."""
        metrics = {
            "pre_market_high": 0.0, "pre_market_low": 0.0, "pre_market_open": 0.0, "pre_market_close": 0.0,
            "regular_high": 0.0, "regular_low": 0.0, "opening_price": 0.0, "closing_price": 0.0,
            "post_market_high": 0.0, "post_market_low": 0.0, "post_market_open": 0.0, "post_market_close": 0.0,
            "total_day_high": 0.0, "total_day_low": 0.0, "total_volume": 0
        }
        
        # Get all minute aggregates for the day
        day_start = datetime.combine(event_date, datetime.min.time())
        day_end = datetime.combine(event_date, datetime.max.time())
        
        aggs = (
            db.query(StockAggregate)
            .filter(
                StockAggregate.ticker == ticker,
                StockAggregate.timestamp >= day_start,
                StockAggregate.timestamp <= day_end,
                StockAggregate.timespan == 'minute'
            )
            .order_by(StockAggregate.timestamp.asc())
            .all()
        )
        
        if not aggs:
            return metrics
            
        pre_aggs = [a for a in aggs if a.is_pre_market]
        reg_aggs = [a for a in aggs if not a.is_pre_market and not a.is_after_market]
        post_aggs = [a for a in aggs if a.is_after_market]
        
        # Total Day
        metrics["total_day_high"] = float(max(a.high for a in aggs))
        metrics["total_day_low"] = float(min(a.low for a in aggs))
        metrics["total_volume"] = sum(a.volume for a in aggs)
        
        # Pre Market
        if pre_aggs:
            metrics["pre_market_high"] = float(max(a.high for a in pre_aggs))
            metrics["pre_market_low"] = float(min(a.low for a in pre_aggs))
            metrics["pre_market_open"] = float(pre_aggs[0].open)
            metrics["pre_market_close"] = float(pre_aggs[-1].close)
            
        # Regular Market
        if reg_aggs:
            metrics["regular_high"] = float(max(a.high for a in reg_aggs))
            metrics["regular_low"] = float(min(a.low for a in reg_aggs))
            metrics["opening_price"] = float(reg_aggs[0].open)
            metrics["closing_price"] = float(reg_aggs[-1].close)
            
        # Post Market
        if post_aggs:
            metrics["post_market_high"] = float(max(a.high for a in post_aggs))
            metrics["post_market_low"] = float(min(a.low for a in post_aggs))
            metrics["post_market_open"] = float(post_aggs[0].open)
            metrics["post_market_close"] = float(post_aggs[-1].close)
            
        return metrics

    @staticmethod
    async def run_liquidity_hunt_scan(
        tickers: List[str], db: Session
    ) -> List[Dict[str, Any]]:
        """
        Run Extended Hours Liquidity Hunt scan using DB Aggregates across all history.
        Strategy: High extended-hours activity + price spike + retrace to origin.
        Optimized to use stock_aggregates table and scan entire available timeline.
        """
        results = []
        
        try:
            # Step 1: Find all (ticker, date) combinations with high pre-market volume
            candidates = (
                db.query(
                    StockAggregate.ticker,
                    func.date(StockAggregate.timestamp).label('event_date'),
                    func.sum(StockAggregate.volume).label('total_vol'),
                    func.max(StockAggregate.high).label('high_price'),
                    func.max(StockAggregate.timestamp).label('last_extended_hours_time')
                )
                .filter(
                    or_(StockAggregate.is_pre_market == True, StockAggregate.is_after_market == True),
                    StockAggregate.ticker.in_(tickers)
                )
                .group_by(StockAggregate.ticker, func.date(StockAggregate.timestamp))
                .having(func.sum(StockAggregate.volume) > 50000)
                .all()
            )

            # Pre-fetch market caps
            monitored_stocks = db.query(MonitoredStock.ticker, MonitoredStock.market_cap).filter(MonitoredStock.ticker.in_(tickers)).all()
            market_cap_map = {ms.ticker: ms.market_cap for ms in monitored_stocks}

            for cand in candidates:
                ticker = cand.ticker
                raw_event_date = cand.event_date
                event_date = datetime.strptime(raw_event_date, '%Y-%m-%d').date() if isinstance(raw_event_date, str) else raw_event_date
                
                # Fetch detailed day metrics
                day_metrics = ScannerService.calculate_day_metrics(ticker, event_date, db)
                
                pre_market_volume = float(cand.total_vol)
                pre_market_high = float(cand.high_price)
                
                # Start of the event day for relative lookups
                day_start = datetime.combine(event_date, datetime.min.time())

                # Step 2: Get Previous Close
                prev_close_row = (
                    db.query(StockAggregate.close)
                    .filter(StockAggregate.ticker == ticker, StockAggregate.timestamp < day_start)
                    .order_by(desc(StockAggregate.timestamp))
                    .limit(1).first()
                )
                previous_close = float(prev_close_row[0]) if prev_close_row else 0
                if previous_close == 0: continue

                # Historical data for volume/accumulation check
                hist_data = (
                    db.query(StockAggregate.close, StockAggregate.volume)
                    .filter(StockAggregate.ticker == ticker, StockAggregate.timestamp < day_start, StockAggregate.is_pre_market == False)
                    .order_by(desc(StockAggregate.timestamp))
                    .limit(20).all()
                )
                
                closes = [float(h[0]) for h in hist_data]
                volumes = [float(h[1]) for h in hist_data]
                
                is_accumulating = True
                is_significant_volume = True
                
                if len(hist_data) >= 5:
                    min_close, max_close = min(closes), max(closes)
                    is_accumulating = (previous_close / min_close < 1.15) and (previous_close / max_close > 0.85)
                    if len(volumes) >= 2:
                        avg_vol_2d = sum(volumes[:2]) / 2
                        is_significant_volume = pre_market_volume > (avg_vol_2d * 0.8)

                # Criteria
                is_spike = pre_market_high > (previous_close * 1.02)
                
                # Calculate extras
                current_price = day_metrics["closing_price"] or day_metrics["pre_market_close"] or previous_close
                fade_from_high_pct = 0
                if day_metrics["regular_high"] > 0:
                    fade_from_high_pct = (day_metrics["regular_high"] - current_price) / day_metrics["regular_high"] * 100
                
                day_range_pct = 0
                if day_metrics["regular_low"] > 0:
                    day_range_pct = (day_metrics["regular_high"] - day_metrics["regular_low"]) / day_metrics["regular_low"] * 100
                
                gap_pct = (day_metrics["opening_price"] - previous_close) / previous_close * 100 if day_metrics["opening_price"] > 0 else 0

                criteria_met = {
                    "high_activity": True,
                    "price_spike": bool(is_spike),
                    "accumulation_phase": bool(is_accumulating),
                    "significant_volume": bool(is_significant_volume),
                    "fade_from_high_pct": round(fade_from_high_pct, 4)
                }

                if is_spike and is_accumulating and is_significant_volume:
                    avg_vol_20d = sum(volumes) / len(volumes) if len(volumes) > 0 else 1
                    rel_vol = pre_market_volume / avg_vol_20d
                    
                    event_data = {
                        "ticker": ticker,
                        "event_date": event_date,
                        "event_type": "liquidity_hunt",
                        "pre_market_volume": pre_market_volume,
                        "avg_volume_20d": int(avg_vol_20d),
                        "relative_volume": round(rel_vol, 2),
                        "volume_spike_ratio": round(rel_vol, 2),
                        "previous_close": previous_close,
                        "pre_market_high": pre_market_high,
                        "pre_market_low": day_metrics["pre_market_low"],
                        "opening_price": day_metrics["opening_price"],
                        "closing_price": day_metrics["closing_price"],
                        "regular_high": day_metrics["regular_high"],
                        "regular_low": day_metrics["regular_low"],
                        "post_market_high": day_metrics["post_market_high"],
                        "post_market_low": day_metrics["post_market_low"],
                        "total_day_high": day_metrics["total_day_high"],
                        "total_day_low": day_metrics["total_day_low"],
                        "fade_from_high_pct": round(fade_from_high_pct, 4),
                        "day_range_pct": round(day_range_pct, 4),
                        "gap_pct": round(gap_pct, 4),
                        "price_change_pct": (current_price - previous_close) / previous_close * 100,
                        "price_gap_pct": gap_pct,
                        "market_cap_at_event": market_cap_map.get(ticker),
                        "criteria_met": criteria_met,
                    }

                    # Store in DB
                    existing_event = db.query(VolumeEvent).filter(
                        VolumeEvent.ticker == ticker,
                        VolumeEvent.event_date == event_date,
                        VolumeEvent.event_type == "liquidity_hunt"
                    ).first()

                    if not existing_event:
                        volume_event = VolumeEvent(**event_data)
                        db.add(volume_event)
                        db.flush()
                        event_data['id'] = volume_event.id
                    else:
                        for key, value in event_data.items():
                            setattr(existing_event, key, value)
                        event_data['id'] = existing_event.id
                    
                    results.append(event_data)

        except Exception as e:
            logging.error(f"Error in historical liquidity hunt scan: {e}")
            
        db.commit()
        return results

    @staticmethod
    async def run_pre_market_scan(
        tickers: List[str], db: Session
    ) -> List[Dict[str, Any]]:
        """Run extended hours (pre+post) volume spike scanner."""
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
                    # Get current stock info
                    info = await StockDataService.get_stock_info(ticker)
                    
                    previous_close = float(hist_data["Close"].iloc[-1])
                    event_date = datetime.now().date()
                    
                    # Fetch metrics for today
                    day_metrics = ScannerService.calculate_day_metrics(ticker, event_date, db)
                    
                    current_price = day_metrics["closing_price"] or day_metrics["pre_market_close"] or previous_close
                    fade_from_high_pct = 0
                    if day_metrics["regular_high"] > 0:
                        fade_from_high_pct = (day_metrics["regular_high"] - current_price) / day_metrics["regular_high"] * 100
                    
                    day_range_pct = 0
                    if day_metrics["regular_low"] > 0:
                        day_range_pct = (day_metrics["regular_high"] - day_metrics["regular_low"]) / day_metrics["regular_low"] * 100
                    
                    gap_pct = (day_metrics["opening_price"] - previous_close) / previous_close * 100 if day_metrics["opening_price"] > 0 else 0

                    event = {
                        "ticker": ticker,
                        "event_date": event_date,
                        "event_type": "pre_market_volume_spike",
                        "pre_market_volume": pre_market_volume,
                        "avg_volume_20d": int(avg_volume_20d),
                        "avg_volume_50d": int(avg_volume_50d) if not pd.isna(avg_volume_50d) else None,
                        "relative_volume": round(relative_volume, 2),
                        "volume_spike_ratio": round(pre_market_volume / avg_volume_20d, 2),
                        "previous_close": previous_close,
                        "pre_market_high": day_metrics["pre_market_high"],
                        "pre_market_low": day_metrics["pre_market_low"],
                        "opening_price": day_metrics["opening_price"],
                        "closing_price": day_metrics["closing_price"],
                        "regular_high": day_metrics["regular_high"],
                        "regular_low": day_metrics["regular_low"],
                        "post_market_high": day_metrics["post_market_high"],
                        "post_market_low": day_metrics["post_market_low"],
                        "total_day_high": day_metrics["total_day_high"],
                        "total_day_low": day_metrics["total_day_low"],
                        "fade_from_high_pct": round(fade_from_high_pct, 4),
                        "day_range_pct": round(day_range_pct, 4),
                        "gap_pct": round(gap_pct, 4),
                        "price_change_pct": (current_price - previous_close) / previous_close * 100,
                        "price_gap_pct": gap_pct,
                        "market_cap_at_event": info.get("marketCap"),
                        "criteria_met": criteria_met,
                    }

                    # Save to database
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
                        for key, value in event.items():
                            setattr(existing_event, key, value)
                        event['id'] = existing_event.id
                    
                    results.append(event)

            except Exception as e:
                logging.error(f"Error scanning {ticker}: {e}")
                continue

        db.commit()
        return results
