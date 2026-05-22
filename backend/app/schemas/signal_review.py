"""
Pydantic schemas for signal review endpoints.
"""

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, field_validator


VALID_VERDICTS = {"confirmed", "rejected", "enhanced"}
VALID_REJECT_REASONS = {"noise", "too_late", "stale_data", "split_artifact", "threshold_too_loose", "other"}


class SignalReviewCreate(BaseModel):
    scanner_event_id: int
    verdict: str
    reject_reason: Optional[str] = None
    notes: Optional[str] = None
    enhance_suggestion: Optional[Dict[str, Any]] = None

    @field_validator("verdict")
    @classmethod
    def verdict_must_be_valid(cls, v: str) -> str:
        if v not in VALID_VERDICTS:
            raise ValueError(f"verdict must be one of {VALID_VERDICTS}")
        return v

    @field_validator("reject_reason")
    @classmethod
    def reject_reason_must_be_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_REJECT_REASONS:
            raise ValueError(f"reject_reason must be one of {VALID_REJECT_REASONS}")
        return v

    def model_post_init(self, __context: Any) -> None:
        if self.verdict == "rejected" and not self.reject_reason:
            raise ValueError("reject_reason is required when verdict is 'rejected'")


class SignalReviewResponse(BaseModel):
    id: int
    scanner_event_id: int
    verdict: str
    reject_reason: Optional[str]
    notes: Optional[str]
    enhance_suggestion: Optional[Dict[str, Any]]
    reviewed_at: datetime
    reviewed_by: Optional[str]
    # Joined fields from ScannerEvent (populated in GET list endpoint)
    ticker: Optional[str] = None
    event_date: Optional[str] = None
    scanner_type: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
