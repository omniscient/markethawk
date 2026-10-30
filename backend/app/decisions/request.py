"""DecisionRequest — the immutable, point-in-time input a provider is asked to answer."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated, Any, Literal, Mapping, Optional, Tuple
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.decisions.schema import (
    BoundedFloat,
    FrozenContract,
    Sha256Hex,
    UtcDatetime,
    sha256_hex,
)

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()

QualityGateVerdictValue = Literal["trusted", "warning", "blocked", "skipped"]
# First seven mirror app.schemas.quality_gate.QualityIssueCode by value (not import);
# "no_assessment" is local and marks the null-gate ref (spec §3.3).
QualityIssueCodeValue = Literal[
    "missing_bars",
    "split_dividend_anomaly",
    "stale_quote",
    "provider_gap",
    "session_mismatch",
    "survivorship_bias",
    "insufficient_lookback",
    "no_assessment",
]
ProvenanceRef = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/\-]{0,127}$")
]
Ticker = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9.\-]{0,9}$")]
NonNegativeFloat = Annotated[
    float, Field(ge=0, le=1_000_000_000.0, allow_inf_nan=False)
]
NonNegativeInt = Annotated[int, Field(ge=0, le=1_000_000_000_000)]


def persisted_assessment_sha256(persisted: Mapping[str, Any]) -> str:
    """Digest of the JSONB payload written to ``ScannerRun.quality_gate``.

    ``persisted`` is the already-JSON-native dict
    (``json.loads(json.dumps(assessment.model_dump(), default=str))``); it is hashed with
    the package's canonical JSON so the digest matches what is on the row.
    """
    return sha256_hex(dict(persisted))


class QualityGateRef(FrozenContract):
    schema_version: Literal["quality_gate.v1"] = "quality_gate.v1"
    verdict: QualityGateVerdictValue
    trusted: bool
    issue_codes: Tuple[QualityIssueCodeValue, ...] = Field(max_length=8)
    generated_at: UtcDatetime
    source_run_uuid: Optional[UUID] = None
    assessment_sha256: Sha256Hex

    @model_validator(mode="after")
    def _no_assessment_shape(self) -> "QualityGateRef":
        if "no_assessment" in self.issue_codes and (
            self.verdict != "skipped"
            or self.trusted
            or self.issue_codes != ("no_assessment",)
            or self.assessment_sha256 != EMPTY_SHA256
        ):
            raise ValueError("no_assessment ref must be the designated null-gate shape")
        return self

    @classmethod
    def no_assessment(
        cls, *, as_of: datetime, source_run_uuid: Optional[UUID] = None
    ) -> "QualityGateRef":
        """The designated ref for a run with no gate assessment (nightly/live scans)."""
        return cls(
            schema_version="quality_gate.v1",
            verdict="skipped",
            trusted=False,
            issue_codes=("no_assessment",),
            generated_at=as_of,
            source_run_uuid=source_run_uuid,
            assessment_sha256=EMPTY_SHA256,
        )


class DecisionMarketSnapshot(FrozenContract):
    """Numeric/enum-only market state. ``observed_at`` is the newest datum's timestamp."""

    observed_at: UtcDatetime
    ticker: Ticker
    session: Optional[Literal["pre_market", "regular", "post_market"]] = None
    last_price: Optional[NonNegativeFloat] = None
    prev_close: Optional[NonNegativeFloat] = None
    gap_pct: Optional[BoundedFloat] = None
    volume: Optional[NonNegativeInt] = None
    avg_volume: Optional[NonNegativeFloat] = None
    relative_volume: Optional[NonNegativeFloat] = None
    vwap: Optional[NonNegativeFloat] = None
    day_high: Optional[NonNegativeFloat] = None
    day_low: Optional[NonNegativeFloat] = None


class DecisionRunLineage(FrozenContract):
    scanner_event_uuid: Optional[UUID] = None
    scanner_run_uuid: Optional[UUID] = None
    feature_provenance_ref: ProvenanceRef


class DecisionRequest(FrozenContract):
    request_id: UUID
    schema_ref: Sha256Hex
    as_of: UtcDatetime
    market_snapshot: DecisionMarketSnapshot
    event_run_lineage: DecisionRunLineage
    quality_gate: QualityGateRef
