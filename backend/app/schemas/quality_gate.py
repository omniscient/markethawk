"""
Quality Gate Pydantic contract.

Defines the versioned assessment shape produced by QualityGateService.assess().
All consumers (scanner, backtest, auto-trading, scorecard, UI) receive this contract.

Mirrors the schema specified in issue #492; created here so the #493 router
can compile before #492 is merged. The #492 implementation must be compatible
with this contract.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict


class QualityIssueCode(str, Enum):
    missing_bars = "missing_bars"
    split_dividend_anomaly = "split_dividend_anomaly"
    stale_quote = "stale_quote"
    provider_gap = "provider_gap"
    session_mismatch = "session_mismatch"
    survivorship_bias = "survivorship_bias"
    insufficient_lookback = "insufficient_lookback"


class QualityGatePolicy(str, Enum):
    strict = "strict"
    advisory = "advisory"
    off = "off"


class QualityGateVerdict(str, Enum):
    trusted = "trusted"
    warning = "warning"
    blocked = "blocked"
    skipped = "skipped"


class QualityGateScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    universe_id: Optional[int] = None
    ticker: Optional[str] = None
    scanner_type: Optional[str] = None
    timespan: Optional[str] = None


class QualityGateIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: QualityIssueCode
    severity: Literal["blocker", "warning"]
    message: str
    detail: Dict[str, Any] = {}


class QualityGateAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["quality_gate.v1"] = "quality_gate.v1"
    policy: QualityGatePolicy
    verdict: QualityGateVerdict
    trusted: bool
    scope: QualityGateScope
    score: Optional[float] = None
    grade: Optional[str] = None
    issues: List[QualityGateIssue] = []
    warnings: List[QualityGateIssue] = []
    generated_at: datetime
