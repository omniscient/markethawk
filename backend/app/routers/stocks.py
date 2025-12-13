"""
Stocks router - historical data endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import pandas as pd

from app.core.database import get_db
from app.services import StockDataService

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/historical/{ticker}")
async def get_historical_data(
    ticker: str,
    period: str = "30d",
    db: Session = Depends(get_db),
):
    """Get historical stock data."""
    try:
        data = await StockDataService.get_historical_data(ticker.upper(), period)

        if data.empty:
            raise HTTPException(status_code=404, detail="No data found for ticker")

        # Convert to JSON-serializable format
        data_dict = data.reset_index().to_dict("records")
        for record in data_dict:
            record["Date"] = record["Date"].strftime("%Y-%m-%d")
            for key in ["Open", "High", "Low", "Close", "Volume"]:
                if key in record:
                    record[key] = float(record[key]) if pd.notna(record[key]) else None

        return {
            "ticker": ticker.upper(),
            "period": period,
            "data_points": len(data_dict),
            "data": data_dict,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {str(e)}")
