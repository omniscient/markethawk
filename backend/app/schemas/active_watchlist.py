"""
Active Watchlist Pydantic schemas.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import validate_symbol_for_security_type


class ActiveWatchlistAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., min_length=1, max_length=20)
    security_type: Literal["STK", "FUT"] = "STK"
    exchange: Optional[str] = Field(None, max_length=20)
    notes: Optional[str] = Field(None, max_length=500)

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("exchange")
    @classmethod
    def upper_exchange(cls, v: Optional[str]) -> Optional[str]:
        return v.strip().upper() if v else v

    @model_validator(mode="after")
    def validate_symbol_pattern(self) -> "ActiveWatchlistAdd":
        # Equity vs futures-root pattern dispatched on security_type (F-INPUT-02).
        # symbol is already stripped+uppercased by upper_symbol above.
        validate_symbol_for_security_type(self.symbol, self.security_type)
        return self

    @model_validator(mode="after")
    def default_exchange(self) -> "ActiveWatchlistAdd":
        if self.security_type == "FUT" and not self.exchange:
            self.exchange = "CME"
        elif self.security_type == "STK" and not self.exchange:
            self.exchange = "SMART"
        return self


class ActiveWatchlistUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: Optional[str] = Field(None, max_length=500)


class ActiveWatchlistItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    security_type: str
    exchange: Optional[str]
    notes: Optional[str]
    added_at: datetime
