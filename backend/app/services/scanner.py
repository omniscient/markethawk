"""
Scanner Service - Pre-market volume scanning logic.
"""

import logging
from datetime import datetime
from typing import Dict, Any, List

import pandas as pd
from sqlalchemy.orm import Session

from app.models.volume_event import VolumeEvent
from app.services.stock_data import StockDataService


class ScannerService:
    """Service for running stock scanners."""

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
                        "previous_close": float(hist_data["Close"].iloc[-1]),
                        "pre_market_high": pre_market_data.get("pre_market_high"),
                        "pre_market_low": pre_market_data.get("pre_market_low"),
                        "market_cap_at_event": info.get("marketCap"),
                        "criteria_met": criteria_met,
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
