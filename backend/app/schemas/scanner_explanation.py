import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCANNER_EXPLANATION_SCHEMA_VERSION = "scanner_explanation.v1"

_CRITERION_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_ALLOWED_OPERATORS = {">", ">=", "<", "<=", "==", "!=", "exists"}
_WARNING_SEVERITY_MAP = {
    "info": "low",
    "low": "low",
    "warning": "medium",
    "medium": "medium",
    "error": "high",
    "critical": "high",
    "high": "high",
}


class CriterionExplanation(BaseModel):
    label: str
    observed: Any = None
    threshold: Any = None
    operator: str
    unit: Optional[str] = None
    source: Optional[str] = None
    lookback: Optional[str] = None
    importance: Optional[float] = Field(default=None, ge=0, le=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, value: str) -> str:
        if value not in _ALLOWED_OPERATORS:
            raise ValueError(f"operator must be one of {sorted(_ALLOWED_OPERATORS)}")
        return value


class DataQualityWarning(BaseModel):
    code: str
    severity: Literal["low", "medium", "high"]
    message: str
    affected_inputs: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value: Any) -> str:
        normalized = _WARNING_SEVERITY_MAP.get(str(value).lower())
        if normalized is None:
            raise ValueError("severity must be low, medium, or high")
        return normalized


class ExplanationEvidence(BaseModel):
    reconstructed: bool
    reconstruction_quality: Optional[Literal["best_effort", "partial"]] = None
    generated_at: Optional[datetime] = None
    generator_version: str = "explanation_builder.v1"
    market_data_asof: Optional[datetime] = None
    provider: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class ScannerExplanation(BaseModel):
    schema_version: Literal["scanner_explanation.v1"]
    why: List[str] = Field(min_length=1)
    criteria_passed: Dict[str, CriterionExplanation] = Field(default_factory=dict)
    criteria_failed: Dict[str, CriterionExplanation] = Field(default_factory=dict)
    confidence_inputs: Dict[str, Any] = Field(default_factory=dict)
    data_quality_warnings: List[DataQualityWarning] = Field(default_factory=list)
    evidence: ExplanationEvidence

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_criterion_ids(self) -> "ScannerExplanation":
        for key in [*self.criteria_passed.keys(), *self.criteria_failed.keys()]:
            if not _CRITERION_ID_RE.match(key):
                raise ValueError(
                    f"criterion id '{key}' must be scanner-qualified, like premarket.volume_spike"
                )
        return self


def validate_scanner_explanation(payload: Dict[str, Any]) -> Dict[str, Any]:
    return ScannerExplanation.model_validate(payload).model_dump(mode="json")
