"""
Scanner Service - Pre-market volume scanning logic.
"""

import logging
import asyncio
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from app.utils.session import get_market_today
from typing import Dict, Any, List

import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_

from app.models.scanner_event import ScannerEvent
from app.models.stock_aggregate import StockAggregate
from app.models.monitored_stock import MonitoredStock
from app.models.ticker_reference import TickerReference
from app.models.stock_split import StockSplit
from app.services.stock_data import StockDataService
from app.services.catalyst_parser import CatalystParser
from app.services.event_helpers import generate_event_summary, compute_event_severity


class ScannerService:
    """Service for running stock scanners."""

    _SCAN_SEMAPHORE = asyncio.Semaphore(10)

    @staticmethod
    def calculate_day_metrics_from_aggs(aggs: List[StockAggregate]) -> Dict[str, Any]:
        """Calculate detailed price metrics from a list of minute aggregates."""
        metrics = {
            "pre_market_high": 0.0, "pre_market_low": 0.0, "pre_market_open": 0.0, "pre_market_close": 0.0,
            "regular_high": 0.0, "regular_low": 0.0, "opening_price": 0.0, "closing_price": 0.0,
            "post_market_high": 0.0, "post_market_low": 0.0, "post_market_open": 0.0, "post_market_close": 0.0,
            "total_day_high": 0.0, "total_day_low": 0.0, "total_volume": 0
        }
        
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
    def calculate_day_metrics(ticker: str, event_date: date, db: Session) -> Dict[str, Any]:
        """Calculate detailed price metrics for different sessions of a given day."""
        metrics = {
            "pre_market_high": 0.0, "pre_market_low": 0.0, "pre_market_open": 0.0, "pre_market_close": 0.0,
            "regular_high": 0.0, "regular_low": 0.0, "opening_price": 0.0, "closing_price": 0.0,
            "post_market_high": 0.0, "post_market_low": 0.0, "post_market_open": 0.0, "post_market_close": 0.0,
            "total_day_high": 0.0, "total_day_low": 0.0, "total_volume": 0
        }
        
        # Get all minute aggregates for the day
        _ET = ZoneInfo("America/New_York")
        day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)
        day_end_et = datetime.combine(event_date, datetime.max.time(), tzinfo=_ET)
        
        # Convert to UTC and strip tzinfo for DB comparison (since DB stores naive UTC)
        day_start_utc = day_start_et.astimezone(timezone.utc).replace(tzinfo=None)
        day_end_utc = day_end_et.astimezone(timezone.utc).replace(tzinfo=None)
        
        aggs = (
            db.query(StockAggregate)
            .filter(
                StockAggregate.ticker == ticker,
                StockAggregate.timestamp >= day_start_utc,
                StockAggregate.timestamp <= day_end_utc,
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
    def _get_batch_enrichment_data(tickers: List[str], event_date: date, db: Session) -> Dict[str, Dict[str, Any]]:
        """Fetch common enrichment data for a list of tickers in one batch."""
        # 1. Fetch MonitoredStock records
        monitored_records = db.query(MonitoredStock).filter(MonitoredStock.ticker.in_(tickers)).all()
        monitored_map = {r.ticker: r for r in monitored_records}
        
        # 2. Fetch TickerReference records
        ref_records = db.query(TickerReference).filter(TickerReference.ticker.in_(tickers)).all()
        ref_map = {r.ticker: r for r in ref_records}
        
        # 3. Recent Splits
        six_months_prior = event_date - timedelta(days=180)
        split_records = db.query(StockSplit).filter(
            StockSplit.ticker.in_(tickers),
            StockSplit.execution_date <= event_date,
            StockSplit.execution_date >= six_months_prior
        ).order_by(desc(StockSplit.execution_date)).all()
        
        split_map = {}
        for s in split_records:
            if s.ticker not in split_map:
                split_map[s.ticker] = s.execution_date.isoformat()
        
        # 4. Catalyst lookup via optimized batch analyzer
        catalyst_batch = CatalystParser.batch_analyze(tickers, event_date, db)
        
        batch_data = {}
        for ticker in tickers:
            t_upper = ticker.upper()
            monitored = monitored_map.get(t_upper)
            ref = ref_map.get(t_upper)
            cat = catalyst_batch.get(t_upper, {"tags": [], "summary": None})
            
            batch_data[t_upper] = {
                "market_cap": float(monitored.market_cap) if monitored and monitored.market_cap else None,
                "outstanding_shares": float(ref.share_class_shares_outstanding) if ref and ref.share_class_shares_outstanding else None,
                "recent_split_date": split_map.get(t_upper),
                "catalyst_tags": cat.get("tags", []),
                "catalyst_summary": cat.get("summary"),
            }
            
        return batch_data

    @staticmethod
    def _save_event(
        db: Session,
        ticker: str,
        event_date: date,
        scanner_type: str,
        indicators: Dict[str, Any],
        criteria_met: Dict[str, Any],
        enrichment: Dict[str, Any],
        previous_close: float = None,
        opening_price: float = None,
        closing_price: float = None
    ) -> Dict[str, Any]:
        """Generalized method to save or update a ScannerEvent."""
        
        # Calculate summary and severity
        summary = generate_event_summary(scanner_type, indicators)
        severity = compute_event_severity(scanner_type, indicators)
        
        # Prepare data dict
        event_dict = {
            "ticker": ticker,
            "event_date": event_date,
            "scanner_type": scanner_type,
            "summary": summary,
            "severity": severity,
            "previous_close": previous_close,
            "opening_price": opening_price,
            "closing_price": closing_price,
            "indicators": indicators,
            "criteria_met": criteria_met,
            "metadata": enrichment
        }
        
        # Check for existing event
        existing = db.query(ScannerEvent).filter(
            ScannerEvent.ticker == ticker,
            ScannerEvent.event_date == event_date,
            ScannerEvent.scanner_type == scanner_type
        ).first()
        
        if existing:
            for key, value in event_dict.items():
                if key == "metadata":
                    setattr(existing, "metadata_", value)
                else:
                    setattr(existing, key, value)
            db.flush()
            event_dict["id"] = existing.id
        else:
            # SQLAlchemy model uses 'metadata_' to avoid conflict with Base.metadata
            model_data = event_dict.copy()
            model_data["metadata_"] = model_data.pop("metadata")
            new_event = ScannerEvent(**model_data)
            db.add(new_event)
            db.flush()
            event_dict["id"] = new_event.id

            # Trigger alert evaluation for new events
            from app.tasks import evaluate_scanner_alerts
            evaluate_scanner_alerts.delay(new_event.id)
            
        return event_dict

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

            # Pre-fetch static ticker enrichment data (H5 fix)
            all_involved_tickers = list(set(c.ticker for c in candidates))
            monitored_map = {r.ticker: r for r in db.query(MonitoredStock).filter(MonitoredStock.ticker.in_(all_involved_tickers)).all()}
            ref_map = {r.ticker: r for r in db.query(TickerReference).filter(TickerReference.ticker.in_(all_involved_tickers)).all()}

            for cand in candidates:
                ticker = cand.ticker
                raw_event_date = cand.event_date
                event_date = datetime.strptime(raw_event_date, '%Y-%m-%d').date() if isinstance(raw_event_date, str) else raw_event_date
                
                # Fetch detailed day metrics
                day_metrics = ScannerService.calculate_day_metrics(ticker, event_date, db)
                
                pre_market_volume = float(cand.total_vol)
                pre_market_high = float(cand.high_price)
                
                # Start of the event day for relative lookups (UTC boundary)
                _ET = ZoneInfo("America/New_York")
                day_start_et = datetime.combine(event_date, datetime.min.time(), tzinfo=_ET)
                day_start_utc = day_start_et.astimezone(timezone.utc).replace(tzinfo=None)

                # Step 2: Get Previous Close
                prev_close_row = (
                    db.query(StockAggregate.close)
                    .filter(StockAggregate.ticker == ticker, StockAggregate.timestamp < day_start_utc)
                    .order_by(desc(StockAggregate.timestamp))
                    .limit(1).first()
                )
                previous_close = float(prev_close_row[0]) if prev_close_row else 0
                if previous_close == 0: continue

                # Historical data for volume/accumulation check
                hist_data = (
                    db.query(StockAggregate.close, StockAggregate.volume)
                    .filter(StockAggregate.ticker == ticker, StockAggregate.timestamp < day_start_utc, StockAggregate.is_pre_market == False)
                    .order_by(desc(StockAggregate.timestamp))
                    .limit(20).all()
                )
                
                closes = [float(h[0]) for h in hist_data]
                volumes = [float(h[1]) for h in hist_data]
                
                is_accumulating = True
                is_significant_volume = True
                
                if len(hist_data) >= 5:
                    min_close, max_close = min(closes), max(closes)
                    # Relaxed accumulation: within 25% of recent range
                    is_accumulating = (previous_close / min_close < 1.25) and (previous_close / max_close > 0.75)
                    if len(volumes) >= 2:
                        avg_vol_2d = sum(volumes[:2]) / 2
                        # User requirement: keep 80% threshold
                        is_significant_volume = pre_market_volume > (avg_vol_2d * 0.8)

                # Criteria: 2% spike in extended hours
                is_spike = pre_market_high > (previous_close * 1.02)
                
                # Check for "Retrace" (The "Hunt" part)
                # If it's a hunt, we expect the gain to be short-lived.
                # Use opening_price or pre_market_close to see if it held.
                current_price = day_metrics["closing_price"] or day_metrics["pre_market_close"] or previous_close
                gap_pct = (day_metrics["opening_price"] - previous_close) / previous_close * 100 if day_metrics["opening_price"] > 0 else 0
                
                # Retrace logic: The price should have given back at least 50% of the movement from pre-market high
                # OR is currently less than 4% above previous close despite a large spike.
                spike_amount = pre_market_high - previous_close
                retrace_amount = pre_market_high - (day_metrics["opening_price"] or current_price)
                is_retrace = False
                if spike_amount > 0:
                     retrace_ratio = retrace_amount / spike_amount
                     is_retrace = retrace_ratio > 0.5 or (day_metrics["opening_price"] < previous_close * 1.04)

                if is_spike and is_accumulating and is_significant_volume and is_retrace:
                    # Prevent division by zero or nonsensical defaults for RVOL
                    avg_vol_20d = sum(volumes) / len(volumes) if len(volumes) > 0 else None
                    if not avg_vol_20d or avg_vol_20d < 1000: # Ignore if extremely thin history
                        continue
                        
                    rel_vol = pre_market_volume / avg_vol_20d
                    
                    fade_from_high_pct = (day_metrics["regular_high"] - current_price) / day_metrics["regular_high"] * 100 if day_metrics["regular_high"] > 0 else 0
                    day_range_pct = (day_metrics["regular_high"] - day_metrics["regular_low"]) / day_metrics["regular_low"] * 100 if day_metrics["regular_low"] > 0 else 0

                    indicators = {
                        "pre_market_volume": pre_market_volume,
                        "avg_volume_20d": int(avg_vol_20d),
                        "relative_volume": round(rel_vol, 2),
                        "volume_spike_ratio": round(rel_vol, 2),
                        "pre_market_high": pre_market_high,
                        "gap_pct": round(gap_pct, 4),
                        "fade_from_high_pct": round(fade_from_high_pct, 4),
                        "day_range_pct": round(day_range_pct, 4),
                        "retrace_ratio": round(retrace_ratio, 2) if spike_amount > 0 else 0
                    }

                    criteria_met = {
                        "high_activity": True,
                        "price_spike": bool(is_spike),
                        "accumulation_phase": bool(is_accumulating),
                        "significant_volume": bool(is_significant_volume),
                        "retrace_fail": bool(is_retrace)
                    }

                    # Enrichment (batched news + pre-fetched static data)
                    cat_info = CatalystParser.analyze(ticker, event_date, db)
                    monitored = monitored_map.get(ticker)
                    ref = ref_map.get(ticker)
                    
                    # Fetch split for this specific date (harder to batch across all candidates efficiently)
                    six_months_prior = event_date - timedelta(days=180)
                    recent_split = db.query(StockSplit).filter(
                        StockSplit.ticker == ticker,
                        StockSplit.execution_date <= event_date,
                        StockSplit.execution_date >= six_months_prior
                    ).order_by(desc(StockSplit.execution_date)).first()
                    recent_split_date = recent_split.execution_date.isoformat() if recent_split else None

                    enrichment = {
                        "market_cap": float(monitored.market_cap) if monitored and monitored.market_cap else None,
                        "outstanding_shares": float(ref.share_class_shares_outstanding) if ref and ref.share_class_shares_outstanding else None,
                        "recent_split_date": recent_split_date,
                        "catalyst_tags": cat_info.get("tags", []),
                        "catalyst_summary": cat_info.get("summary"),
                    }
                    if enrichment["outstanding_shares"]:
                        indicators["float_rotation_pct"] = round((pre_market_volume / enrichment["outstanding_shares"] * 100), 4)

                    # Save using helper
                    event_dict = ScannerService._save_event(
                        db=db,
                        ticker=ticker,
                        event_date=event_date,
                        scanner_type="liquidity_hunt",
                        indicators=indicators,
                        criteria_met=criteria_met,
                        enrichment=enrichment,
                        previous_close=previous_close,
                        opening_price=day_metrics["opening_price"],
                        closing_price=day_metrics["closing_price"]
                    )
                    
                    results.append(event_dict)

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
        event_date = get_market_today()
        
        # Pre-fetch enrichment for all tickers
        enrichment_batch = await asyncio.to_thread(ScannerService._get_batch_enrichment_data, tickers, event_date, db)

        async def fetch_ticker_data(ticker: str):
            """Fetch external data in parallel with rate limiting."""
            async with ScannerService._SCAN_SEMAPHORE:
                try:
                    hist_data = await asyncio.to_thread(StockDataService.get_historical_data, ticker, "60d")
                    if hist_data.empty:
                        return ticker, None, None
                        
                    pre_market_data = await asyncio.to_thread(StockDataService.get_pre_market_data, ticker)
                    return ticker, hist_data, pre_market_data
                except Exception as e:
                    logging.error(f"Error fetching data for {ticker}: {e}")
                    return ticker, None, None

        # Execute all network providers in parallel (H4 fix)
        data_tasks = [fetch_ticker_data(t) for t in tickers]
        fetched_results = await asyncio.gather(*data_tasks)

        # Process results sequentially using the single DB Session (Session is not thread-safe)
        for ticker, hist_data, pre_market_data in fetched_results:
            if hist_data is None or hist_data.empty or pre_market_data is None:
                continue
                
            try:
                # Calculate indicators
                avg_volume_20d = hist_data["Volume"].rolling(20).mean().iloc[-1]
                avg_volume_50d = hist_data["Volume"].rolling(50).mean().iloc[-1] if len(hist_data) >= 50 else None
                pre_market_volume = pre_market_data.get("pre_market_volume", 0)
                relative_volume = (pre_market_volume / avg_volume_20d if avg_volume_20d > 0 else 0)

                criteria_met = {
                    "volume_spike": pre_market_volume > (avg_volume_20d * 4),
                    "minimum_volume": pre_market_volume > 100000,
                    "liquidity": avg_volume_20d > 500000,
                }

                if all(criteria_met.values()):
                    previous_close = float(hist_data["Close"].iloc[-1])
                    day_metrics = ScannerService.calculate_day_metrics(ticker, event_date, db)
                    
                    current_price = day_metrics["closing_price"] or day_metrics["pre_market_close"] or previous_close
                    gap_pct = (day_metrics["opening_price"] - previous_close) / previous_close * 100 if day_metrics["opening_price"] > 0 else 0
                    fade_from_high_pct = (day_metrics["regular_high"] - current_price) / day_metrics["regular_high"] * 100 if day_metrics["regular_high"] > 0 else 0
                    day_range_pct = (day_metrics["regular_high"] - day_metrics["regular_low"]) / day_metrics["regular_low"] * 100 if day_metrics["regular_low"] > 0 else 0

                    indicators = {
                        "pre_market_volume": pre_market_volume,
                        "avg_volume_20d": int(avg_volume_20d),
                        "avg_volume_50d": int(avg_volume_50d) if avg_volume_50d and not pd.isna(avg_volume_50d) else None,
                        "relative_volume": round(relative_volume, 2),
                        "volume_spike_ratio": round(pre_market_volume / avg_volume_20d, 2),
                        "gap_pct": round(gap_pct, 4),
                        "fade_from_high_pct": round(fade_from_high_pct, 4),
                        "day_range_pct": round(day_range_pct, 4)
                    }

                    enrichment = enrichment_batch.get(ticker.upper(), {})
                    if enrichment.get("outstanding_shares"):
                        indicators["float_rotation_pct"] = round((pre_market_volume / enrichment["outstanding_shares"] * 100), 4)

                    event_dict = ScannerService._save_event(
                        db=db,
                        ticker=ticker,
                        event_date=event_date,
                        scanner_type="pre_market_volume_spike",
                        indicators=indicators,
                        criteria_met=criteria_met,
                        enrichment=enrichment,
                        previous_close=previous_close,
                        opening_price=day_metrics["opening_price"],
                        closing_price=day_metrics["closing_price"]
                    )
                    results.append(event_dict)
            except Exception as e:
                logging.error(f"Error processing {ticker} results: {e}")

        db.commit()
        return results

    @staticmethod
    async def run_oversold_bounce_scan(
        tickers: List[str], db: Session
    ) -> List[Dict[str, Any]]:
        """Run the Oversold Bounce (Dual RSI) scan."""
        results = []
        event_date = get_market_today()
        
        # Pre-fetch enrichment
        enrichment_batch = await asyncio.to_thread(ScannerService._get_batch_enrichment_data, tickers, event_date, db)

        async def fetch_ticker_data(ticker: str):
            async with ScannerService._SCAN_SEMAPHORE:
                try:
                    hist_data = await asyncio.to_thread(StockDataService.get_historical_data, ticker, "60d")
                    return ticker, hist_data
                except Exception as e:
                    logging.error(f"Error fetching data for {ticker}: {e}")
                    return ticker, None

        # Parallel fetch
        data_tasks = [fetch_ticker_data(t) for t in tickers]
        fetched_results = await asyncio.gather(*data_tasks)

        # Sequential DB processing
        for ticker, hist_data in fetched_results:
            if hist_data is None or hist_data.empty or len(hist_data) < 10:
                continue
                
            try:
                df = hist_data.copy()
                df.sort_index(inplace=True)
                
                df['vol_ma_3'] = df['Volume'].rolling(window=3).mean()
                df['prev_close'] = df['Close'].shift(1)
                
                def calc_rsi(series, period):
                    delta = series.diff()
                    up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
                    ema_up = up.ewm(com=period - 1, adjust=False).mean()
                    ema_down = down.ewm(com=period - 1, adjust=False).mean()
                    rs = ema_up / ema_down
                    return 100 - (100 / (1 + rs))
                    
                df['rsi_2'] = calc_rsi(df['Close'], 2)
                df['rsi_5'] = calc_rsi(df['Close'], 5)
                
                df['typ_price'] = (df['High'] + df['Low'] + df['Close'] + df['Open']) / 4
                df['liq'] = df['Volume'] * df['typ_price']
                df['avg_liq_5'] = df['liq'].rolling(window=5).mean()
                
                df['tr'] = pd.DataFrame({
                    'tr1': df['High'] - df['Low'],
                    'tr2': (df['High'] - df['Close'].shift(1)).abs(),
                    'tr3': (df['Low'] - df['Close'].shift(1)).abs()
                }).max(axis=1)
                df['atr_1_prev'] = df['tr'].shift(1)
                df['prev_low'] = df['Low'].shift(1)
                
                today = df.iloc[-1]
                yesterday = df.iloc[-2]
                
                vol_ok = today['vol_ma_3'] >= 500000
                price_ok = today['prev_close'] >= 5
                short_rsi_ok = yesterday['rsi_2'] < 15 and today['rsi_2'] >= 15
                long_rsi_ok = yesterday['rsi_5'] < 27 and today['rsi_5'] >= 27
                no_gap_down = today['Open'] >= today['prev_low']
                
                if vol_ok and price_ok and short_rsi_ok and long_rsi_ok and no_gap_down:
                    day_metrics = ScannerService.calculate_day_metrics(ticker, event_date, db)
                    current_price = day_metrics["closing_price"] or day_metrics["pre_market_close"] or float(today['Close'])
                    gap_pct = (float(today['Open']) - float(today['prev_close'])) / float(today['prev_close']) * 100 if float(today['prev_close']) > 0 else 0
                    fade_from_high_pct = (day_metrics["regular_high"] - current_price) / day_metrics["regular_high"] * 100 if day_metrics["regular_high"] > 0 else 0
                    day_range_pct = (day_metrics["regular_high"] - day_metrics["regular_low"]) / day_metrics["regular_low"] * 100 if day_metrics["regular_low"] > 0 else 0

                    indicators = {
                        "rsi_2": float(today['rsi_2']),
                        "rsi_5": float(today['rsi_5']),
                        "vol_ma_3": int(today['vol_ma_3']),
                        "atr_target": float(today['atr_1_prev']),
                        "avg_liquidity_5d": float(today['avg_liq_5']),
                        "gap_pct": round(gap_pct, 4),
                        "fade_from_high_pct": round(fade_from_high_pct, 4),
                        "day_range_pct": round(day_range_pct, 4),
                        "relative_volume": 1.0 # Fallback for stats
                    }

                    criteria_met = {
                        "volume_ma_3_ok": True,
                        "price_ge_5": True,
                        "rsi_2_crossed": True,
                        "rsi_5_crossed": True,
                        "no_gap_down": True
                    }
                    
                    enrichment = enrichment_batch.get(ticker.upper(), {})
                    event_dict = ScannerService._save_event(
                        db=db,
                        ticker=ticker,
                        event_date=event_date,
                        scanner_type="oversold_bounce",
                        indicators=indicators,
                        criteria_met=criteria_met,
                        enrichment=enrichment,
                        previous_close=float(today['prev_close']),
                        opening_price=float(today['Open']),
                        closing_price=float(today['Close'])
                    )
                    results.append(event_dict)
            except Exception as e:
                logging.error(f"Error processing {ticker} oversold bounce: {e}")

        db.commit()
        return results
