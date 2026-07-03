from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session

from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_summary import ScannerOutcomeSummary


class ExplanationTraitPerformanceService:
    """Aggregate outcome performance by scanner explanation traits."""

    def aggregate(
        self,
        db: Session,
        *,
        scanner_type: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        min_sample_size: int = 5,
    ) -> dict[str, Any]:
        rows = self._query_rows(
            db,
            scanner_type=scanner_type,
            start_date=start_date,
            end_date=end_date,
        )
        buckets: dict[tuple[str, str], _TraitBucket] = {}

        for event, summary in rows:
            for trait in _traits_for_event(event):
                key = (trait["trait_type"], trait["trait_key"])
                bucket = buckets.get(key)
                if bucket is None:
                    bucket = _TraitBucket(
                        trait_type=trait["trait_type"],
                        trait_key=trait["trait_key"],
                        trait_label=trait["trait_label"],
                    )
                    buckets[key] = bucket
                bucket.add(event, summary)

        traits = [
            bucket.to_payload(min_sample_size=min_sample_size)
            for bucket in buckets.values()
        ]
        traits.sort(
            key=lambda trait: (
                -trait["sample_size"],
                trait["trait_type"],
                trait["trait_key"],
            )
        )

        return {
            "event_count": len(rows),
            "filters": {
                "scanner_type": scanner_type,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "min_sample_size": min_sample_size,
            },
            "traits": traits,
        }

    def _query_rows(
        self,
        db: Session,
        *,
        scanner_type: str | None,
        start_date: date | None,
        end_date: date | None,
    ) -> list[tuple[ScannerEvent, ScannerOutcomeSummary]]:
        query = (
            db.query(ScannerEvent, ScannerOutcomeSummary)
            .join(
                ScannerOutcomeSummary,
                ScannerOutcomeSummary.scanner_event_id == ScannerEvent.id,
            )
            .filter(ScannerOutcomeSummary.is_complete.is_(True))
        )
        if scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)
        if start_date:
            query = query.filter(ScannerEvent.event_date >= start_date)
        if end_date:
            query = query.filter(ScannerEvent.event_date <= end_date)
        return query.order_by(ScannerEvent.event_date.asc(), ScannerEvent.id.asc()).all()


@dataclass
class _TraitBucket:
    trait_type: str
    trait_key: str
    trait_label: str
    event_ids: list[int] = field(default_factory=list)
    eod_pct_changes: list[float] = field(default_factory=list)
    follow_through_values: list[bool] = field(default_factory=list)
    mfe_values: list[float] = field(default_factory=list)
    mae_values: list[float] = field(default_factory=list)

    def add(
        self,
        event: ScannerEvent,
        summary: ScannerOutcomeSummary,
    ) -> None:
        self.event_ids.append(event.id)
        eod = _to_float(summary.eod_pct_change)
        if eod is not None:
            self.eod_pct_changes.append(eod)
        if summary.follow_through is not None:
            self.follow_through_values.append(bool(summary.follow_through))
        mfe = _to_float(summary.mfe_pct)
        if mfe is not None:
            self.mfe_values.append(mfe)
        mae = _to_float(summary.mae_pct)
        if mae is not None:
            self.mae_values.append(mae)

    def to_payload(self, *, min_sample_size: int) -> dict[str, Any]:
        sample_size = len(self.event_ids)
        wins = sum(1 for value in self.eod_pct_changes if value > 0)
        win_denominator = len(self.eod_pct_changes)
        follow_denominator = len(self.follow_through_values)

        return {
            "trait_type": self.trait_type,
            "trait_key": self.trait_key,
            "trait_label": self.trait_label,
            "sample_size": sample_size,
            "event_ids": sorted(self.event_ids),
            "win_rate_pct": _pct(wins, win_denominator),
            "follow_through_rate_pct": _pct(
                sum(1 for value in self.follow_through_values if value),
                follow_denominator,
            ),
            "avg_mfe_pct": _rounded_mean(self.mfe_values),
            "avg_mae_pct": _rounded_mean(self.mae_values),
            "win_rate_ci_95_pct": _wilson_interval(wins, win_denominator),
            "warnings": _warnings(sample_size, min_sample_size),
        }


def _traits_for_event(event: ScannerEvent) -> list[dict[str, str]]:
    explanation = event.explanation or {}
    traits: list[dict[str, str]] = []

    for criterion_id, criterion in (explanation.get("criteria_passed") or {}).items():
        traits.append(
            {
                "trait_type": "criterion_passed",
                "trait_key": criterion_id,
                "trait_label": criterion.get("label") or criterion_id,
            }
        )
    for criterion_id, criterion in (explanation.get("criteria_failed") or {}).items():
        traits.append(
            {
                "trait_type": "criterion_failed",
                "trait_key": criterion_id,
                "trait_label": criterion.get("label") or criterion_id,
            }
        )
    for warning in explanation.get("data_quality_warnings") or []:
        code = str(warning.get("code") or "quality_gate_warning")
        traits.append(
            {
                "trait_type": "warning",
                "trait_key": code,
                "trait_label": warning.get("message") or code,
            }
        )
    for name, value in (explanation.get("confidence_inputs") or {}).items():
        bucket = _confidence_bucket(value)
        if bucket is None:
            continue
        traits.append(
            {
                "trait_type": "confidence_input",
                "trait_key": f"{name}:{bucket}",
                "trait_label": f"{name} = {bucket}",
            }
        )
    return traits


def _confidence_bucket(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    number = _to_float(value)
    if number is None:
        return str(value)
    normalized = number / 100 if number > 1 and number <= 100 else number
    if 0 <= normalized < 1 / 3:
        return "low"
    if normalized < 2 / 3:
        return "medium"
    if normalized <= 1:
        return "high"
    return "numeric_present"


def _warnings(sample_size: int, min_sample_size: int) -> list[dict[str, str]]:
    if sample_size >= min_sample_size:
        return []
    return [
        {
            "code": "weak_sample_size",
            "message": (
                f"Only {sample_size} events matched this trait; "
                f"minimum recommended sample is {min_sample_size}."
            ),
        }
    ]


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator * 100, 2)


def _rounded_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 4)


def _wilson_interval(successes: int, n: int) -> dict[str, float | None]:
    if n == 0:
        return {"lower": None, "upper": None}
    z = 1.96
    p = successes / n
    denominator = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)
    return {
        "lower": round((centre - margin) / denominator * 100, 2),
        "upper": round((centre + margin) / denominator * 100, 2),
    }


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int | float | Decimal):
        return float(value)
    return None
