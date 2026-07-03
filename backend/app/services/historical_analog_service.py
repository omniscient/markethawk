from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.services.explanation_feature_extractor import ExplanationFeatureExtractor


class HistoricalAnalogService:
    """Find deterministic historical analogs for scanner events."""

    _WEIGHTS = {
        "scanner_type": 0.20,
        "criterion_overlap": 0.30,
        "normalized_values": 0.25,
        "confidence": 0.10,
        "market_context": 0.10,
        "warning_cleanliness": 0.05,
    }

    def __init__(self, extractor: ExplanationFeatureExtractor | None = None) -> None:
        self._extractor = extractor or ExplanationFeatureExtractor()

    def find_similar_events(
        self,
        db: Session,
        *,
        target_event_id: int,
        limit: int = 5,
        min_sample_size: int = 5,
        scanner_type: str | None = None,
        same_scanner_only: bool = True,
        prior_only: bool = True,
        complete_only: bool = True,
    ) -> dict[str, Any]:
        target = (
            db.query(ScannerEvent).filter(ScannerEvent.id == target_event_id).first()
        )
        if target is None:
            raise ValueError(f"ScannerEvent {target_event_id} was not found")

        scanner_type_filter = scanner_type
        if same_scanner_only and scanner_type_filter is None:
            scanner_type_filter = target.scanner_type
        target_row = self._extractor.extract_event(target)[0]
        candidates = self._candidate_rows(
            db,
            target=target,
            scanner_type=scanner_type_filter,
            same_scanner_only=same_scanner_only,
            prior_only=prior_only,
            complete_only=complete_only,
        )
        snapshot_counts = self._captured_snapshot_counts(
            db,
            [event.id for event, _summary in candidates],
        )

        analogs = []
        for candidate, summary in candidates:
            candidate_row = self._extractor.extract_event(candidate, summary)[0]
            score_components = self._score_components(target_row, candidate_row)
            similarity_score = sum(
                score_components[name] * weight
                for name, weight in self._WEIGHTS.items()
            )
            analogs.append(
                {
                    "event_id": candidate.id,
                    "ticker": candidate.ticker,
                    "event_date": _serialize(candidate.event_date),
                    "scanner_type": candidate.scanner_type,
                    "similarity_score": round(similarity_score, 4),
                    "score_components": score_components,
                    "matched_criteria": sorted(
                        _criterion_ids(target_row) & _criterion_ids(candidate_row)
                    ),
                    "outcome_summary": _summary_payload(summary),
                    "captured_snapshot_count": snapshot_counts.get(candidate.id, 0),
                    "warning_count": candidate_row.get("data_quality_warning_count", 0),
                }
            )

        analogs.sort(
            key=lambda analog: (
                -analog["similarity_score"],
                analog["event_date"] or "",
                analog["event_id"],
            )
        )
        analogs = analogs[:limit]

        return {
            "target_event_id": target.id,
            "target_scanner_type": target.scanner_type,
            "sample_size": len(candidates),
            "filters": {
                "scanner_type": scanner_type_filter,
                "same_scanner_only": same_scanner_only,
                "prior_only": prior_only,
                "complete_only": complete_only,
            },
            "warnings": self._warnings(
                sample_size=len(candidates),
                min_sample_size=min_sample_size,
                target_row=target_row,
                analogs=analogs,
            ),
            "analogs": analogs,
        }

    def _candidate_rows(
        self,
        db: Session,
        *,
        target: ScannerEvent,
        scanner_type: str | None,
        same_scanner_only: bool,
        prior_only: bool,
        complete_only: bool,
    ) -> list[tuple[ScannerEvent, ScannerOutcomeSummary]]:
        query = (
            db.query(ScannerEvent, ScannerOutcomeSummary)
            .join(
                ScannerOutcomeSummary,
                ScannerOutcomeSummary.scanner_event_id == ScannerEvent.id,
            )
            .filter(ScannerEvent.id != target.id)
        )
        if prior_only:
            query = query.filter(ScannerEvent.event_date < target.event_date)
        if same_scanner_only and scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)
        elif scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)
        if complete_only:
            query = query.filter(ScannerOutcomeSummary.is_complete.is_(True))
        return query.order_by(ScannerEvent.event_date.desc(), ScannerEvent.id.asc()).all()

    def _captured_snapshot_counts(
        self,
        db: Session,
        event_ids: list[int],
    ) -> dict[int, int]:
        if not event_ids:
            return {}
        rows = (
            db.query(
                ScannerOutcomeSnapshot.scanner_event_id,
                func.count(ScannerOutcomeSnapshot.id),
            )
            .filter(
                ScannerOutcomeSnapshot.scanner_event_id.in_(event_ids),
                ScannerOutcomeSnapshot.status == "captured",
            )
            .group_by(ScannerOutcomeSnapshot.scanner_event_id)
            .all()
        )
        return {int(event_id): int(count) for event_id, count in rows}

    def _score_components(
        self,
        target: dict[str, Any],
        candidate: dict[str, Any],
    ) -> dict[str, float]:
        components = {
            "scanner_type": _scanner_type_similarity(
                target.get("scanner_type"),
                candidate.get("scanner_type"),
            ),
            "criterion_overlap": _jaccard(
                _criterion_ids(target),
                _criterion_ids(candidate),
            ),
            "normalized_values": _numeric_similarity(
                target,
                candidate,
                prefixes=("criterion_", "confidence_"),
                suffixes=("_observed", "_threshold", "_importance"),
                include_keys={"signal_quality_score"},
            ),
            "confidence": _confidence_similarity(target, candidate),
            "market_context": _market_context_similarity(target, candidate),
            "warning_cleanliness": _warning_cleanliness(target, candidate),
        }
        return {name: round(value, 4) for name, value in components.items()}

    def _warnings(
        self,
        *,
        sample_size: int,
        min_sample_size: int,
        target_row: dict[str, Any],
        analogs: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        warnings: list[dict[str, str]] = []
        if sample_size == 0:
            warnings.append(
                {
                    "code": "no_historical_analogs",
                    "message": (
                        "No complete prior analogs were available for this target event."
                    ),
                }
            )
        if sample_size < min_sample_size:
            warnings.append(
                {
                    "code": "weak_sample_size",
                    "message": (
                        f"Only {sample_size} analog candidates were available; "
                        f"minimum recommended sample is {min_sample_size}."
                    ),
                }
            )
        if target_row.get("has_explanation") == 0.0:
            warnings.append(
                {
                    "code": "target_missing_explanation",
                    "message": "Target event has no scanner explanation payload.",
                }
            )
        if analogs and analogs[0]["similarity_score"] < 0.4:
            warnings.append(
                {
                    "code": "weak_similarity",
                    "message": "Top analog similarity is below the recommended threshold.",
                }
            )
        return warnings


def _criterion_ids(row: dict[str, Any]) -> set[str]:
    return set(row.get("criteria_passed_ids") or []) | set(
        row.get("criteria_failed_ids") or []
    )


def _scanner_type_similarity(target: Any, candidate: Any) -> float:
    if target == candidate:
        return 1.0
    target_family = str(target or "").split("_", maxsplit=1)[0]
    candidate_family = str(candidate or "").split("_", maxsplit=1)[0]
    return 0.5 if target_family and target_family == candidate_family else 0.0


def _jaccard(target: set[str], candidate: set[str]) -> float:
    if not target and not candidate:
        return 1.0
    union = target | candidate
    if not union:
        return 0.0
    return len(target & candidate) / len(union)


def _numeric_similarity(
    target: dict[str, Any],
    candidate: dict[str, Any],
    *,
    prefixes: tuple[str, ...],
    suffixes: tuple[str, ...],
    include_keys: set[str] | None = None,
) -> float:
    include_keys = include_keys or set()
    similarities = []
    for key in sorted(set(target) & set(candidate)):
        if key in include_keys or (
            key.startswith(prefixes) and key.endswith(suffixes)
        ):
            target_value = _to_float(target.get(key))
            candidate_value = _to_float(candidate.get(key))
            if target_value is None or candidate_value is None:
                continue
            scale = max(abs(target_value), abs(candidate_value), 1.0)
            similarities.append(max(0.0, 1.0 - abs(target_value - candidate_value) / scale))
    return sum(similarities) / len(similarities) if similarities else 0.0


def _confidence_similarity(target: dict[str, Any], candidate: dict[str, Any]) -> float:
    numeric = _numeric_similarity(
        target,
        candidate,
        prefixes=("confidence_",),
        suffixes=("",),
        include_keys={"signal_quality_score"},
    )
    category = _categorical_similarity(
        target,
        candidate,
        keys=[
            key
            for key in set(target) & set(candidate)
            if key.startswith("confidence_") and key.endswith("_category")
        ],
    )
    if numeric and category:
        return (numeric + category) / 2
    return numeric or category


def _market_context_similarity(
    target: dict[str, Any],
    candidate: dict[str, Any],
) -> float:
    keys = ["severity", "regime"]
    keys.extend(
        key
        for key in set(target) & set(candidate)
        if key.endswith("_category")
        and not key.startswith("confidence_")
        and ("source" in key or "unit" in key or "lookback" in key)
    )
    return _categorical_similarity(target, candidate, keys=keys)


def _categorical_similarity(
    target: dict[str, Any],
    candidate: dict[str, Any],
    *,
    keys: list[str],
) -> float:
    compared = []
    for key in keys:
        target_value = target.get(key)
        candidate_value = candidate.get(key)
        if target_value is None and candidate_value is None:
            continue
        compared.append(1.0 if target_value == candidate_value else 0.0)
    return sum(compared) / len(compared) if compared else 0.0


def _warning_cleanliness(target: dict[str, Any], candidate: dict[str, Any]) -> float:
    warning_count = int(target.get("data_quality_warning_count") or 0) + int(
        candidate.get("data_quality_warning_count") or 0
    )
    return 1.0 / (1.0 + warning_count)


def _summary_payload(summary: ScannerOutcomeSummary) -> dict[str, Any]:
    return {
        "reference_price": _serialize(summary.reference_price),
        "mfe_pct": _serialize(summary.mfe_pct),
        "mfe_time_minutes": summary.mfe_time_minutes,
        "mae_pct": _serialize(summary.mae_pct),
        "mae_time_minutes": summary.mae_time_minutes,
        "mfe_mae_ratio": _serialize(summary.mfe_mae_ratio),
        "r_multiple": _serialize(summary.r_multiple),
        "eod_pct_change": _serialize(summary.eod_pct_change),
        "follow_through": summary.follow_through,
        "gap_filled": summary.gap_filled,
        "is_complete": summary.is_complete,
    }


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int | float | Decimal):
        return float(value)
    return None


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value
