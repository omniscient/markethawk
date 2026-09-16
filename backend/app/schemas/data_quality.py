"""
Data quality gate preflight API request schemas (issue #493).
"""

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict


class TimespanRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timespan: Literal["minute", "hour", "day", "week", "month"]
    multiplier: int = 1


class DataRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timespans: Optional[List[TimespanRequirement]] = None


class GateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    universe_id: int
    policy: Literal["strict", "advisory", "off"]
    consumer: Literal["scanner", "auto_trading", "backtesting", "scorecard", "ui"]
    scanner_type: Optional[str] = None
    ticker: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    requirements: Optional[DataRequirements] = None
