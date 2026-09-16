from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot
from app.models.scanner_outcome_summary import ScannerOutcomeSummary

_SAFE_KEY_RE = re.compile(r"[^a-zA-Z0-9_]+")


class ExplanationFeatureExtractor:
    """Flatten scanner explanations into rows suitable for outcome analysis."""

    def extract_event(
        self,
        event: ScannerEvent,
        outcome_summary: ScannerOutcomeSummary | None = None,
        snapshots: Sequence[ScannerOutcomeSnapshot] | None = None,
    ) -> list[dict[str, Any]]:
        snapshot_rows = list(snapshots or [])
        if not snapshot_rows:
            snapshot_rows = [None]

        base_row = self._event_base(event)
        base_row.update(self._explanation_features(event.explanation))
        base_row.update(self._summary_features(outcome_summary))

        rows = []
        for snapshot in snapshot_rows:
            row = dict(base_row)
            row.update(self._snapshot_features(snapshot))
            rows.append(row)
        return rows

    def extract_rows_for_analysis(
        self,
        db: Session,
        *,
        scanner_type: str | None = None,
        complete_only: bool = True,
        captured_only: bool = True,
    ) -> list[dict[str, Any]]:
        query = (
            db.query(ScannerEvent, ScannerOutcomeSummary, ScannerOutcomeSnapshot)
            .join(
                ScannerOutcomeSummary,
                ScannerOutcomeSummary.scanner_event_id == ScannerEvent.id,
            )
            .join(
                ScannerOutcomeSnapshot,
                ScannerOutcomeSnapshot.scanner_event_id == ScannerEvent.id,
            )
        )
        if scanner_type:
            query = query.filter(ScannerEvent.scanner_type == scanner_type)
        if complete_only:
            query = query.filter(ScannerOutcomeSummary.is_complete.is_(True))
        if captured_only:
            query = query.filter(ScannerOutcomeSnapshot.status == "captured")

        query = query.order_by(
            ScannerEvent.event_date.asc(),
            ScannerEvent.id.asc(),
            ScannerOutcomeSnapshot.interval_key.asc(),
        )

        rows: list[dict[str, Any]] = []
        for event, summary, snapshot in query.all():
            rows.extend(self.extract_event(event, summary, [snapshot]))
        return rows

    def _event_base(self, event: ScannerEvent) -> dict[str, Any]:
        return {
            "event_id": event.id,
            "scanner_event_id": event.id,
            "scanner_event_uuid": str(event.uuid) if event.uuid else None,
            "ticker": event.ticker,
            "event_date": _serialize_value(event.event_date),
            "scanner_type": event.scanner_type,
            "severity": event.severity,
            "signal_quality_score": _to_number(event.signal_quality_score),
            "regime": event.regime,
        }

    def _explanation_features(self, explanation: dict[str, Any] | None) -> dict[str, Any]:
        if not explanation:
            return {
                "has_explanation": 0.0,
                "explanation_schema_version": None,
                "explanation_reconstructed": 0.0,
                "reconstruction_quality_category": None,
                "criteria_passed_count": 0,
                "criteria_failed_count": 0,
                "criteria_passed_ids": [],
                "criteria_failed_ids": [],
                "data_quality_warning_count": 0,
                "warning_severity_low_count": 0,
                "warning_severity_medium_count": 0,
                "warning_severity_high_count": 0,
            }

        criteria_passed = explanation.get("criteria_passed") or {}
        criteria_failed = explanation.get("criteria_failed") or {}
        evidence = explanation.get("evidence") or {}
        warnings = explanation.get("data_quality_warnings") or []
        reconstruction_quality = evidence.get("reconstruction_quality")

        features: dict[str, Any] = {
            "has_explanation": 1.0,
            "explanation_schema_version": explanation.get("schema_version"),
            "explanation_reconstructed": _to_number(evidence.get("reconstructed")) or 0.0,
            "reconstruction_quality_category": reconstruction_quality,
            "criteria_passed_count": len(criteria_passed),
            "criteria_failed_count": len(criteria_failed),
            "criteria_passed_ids": sorted(criteria_passed),
            "criteria_failed_ids": sorted(criteria_failed),
            "data_quality_warning_count": len(warnings),
            "warning_severity_low_count": 0,
            "warning_severity_medium_count": 0,
            "warning_severity_high_count": 0,
        }
        if reconstruction_quality:
            features[f"reconstruction_quality_{_safe_key(reconstruction_quality)}"] = 1.0

        for criterion_id, criterion in criteria_passed.items():
            features.update(
                self._criterion_features(criterion_id, criterion, passed=True)
            )
        for criterion_id, criterion in criteria_failed.items():
            features.update(
                self._criterion_features(criterion_id, criterion, passed=False)
            )
        for name, value in (explanation.get("confidence_inputs") or {}).items():
            self._assign_scalar_or_category(features, f"confidence_{_safe_key(name)}", value)
        for warning in warnings:
            code = _safe_key(warning.get("code") or "quality_gate_warning")
            features[f"warning_{code}"] = 1.0
            severity = warning.get("severity")
            severity_key = f"warning_severity_{_safe_key(severity)}_count"
            if severity_key in features:
                features[severity_key] += 1
        return features

    def _criterion_features(
        self,
        criterion_id: str,
        criterion: dict[str, Any],
        *,
        passed: bool,
    ) -> dict[str, Any]:
        prefix = f"criterion_{_safe_key(criterion_id)}"
        features: dict[str, Any] = {
            f"{prefix}_passed": 1.0 if passed else 0.0,
            f"{prefix}_label": criterion.get("label"),
            f"{prefix}_operator_category": criterion.get("operator"),
            f"{prefix}_unit_category": criterion.get("unit"),
            f"{prefix}_source_category": criterion.get("source"),
            f"{prefix}_lookback_category": criterion.get("lookback"),
        }
        self._assign_scalar_or_category(
            features,
            f"{prefix}_observed",
            criterion.get("observed"),
        )
        self._assign_scalar_or_category(
            features,
            f"{prefix}_threshold",
            criterion.get("threshold"),
        )
        self._assign_scalar_or_category(
            features,
            f"{prefix}_importance",
            criterion.get("importance"),
        )
        return features

    def _summary_features(
        self,
        summary: ScannerOutcomeSummary | None,
    ) -> dict[str, Any]:
        if summary is None:
            return {
                "outcome_reference_price": None,
                "outcome_mfe_pct": None,
                "outcome_mfe_time_minutes": None,
                "outcome_mae_pct": None,
                "outcome_mae_time_minutes": None,
                "outcome_mfe_mae_ratio": None,
                "outcome_r_multiple": None,
                "outcome_eod_pct_change": None,
                "outcome_follow_through": None,
                "outcome_gap_filled": None,
                "outcome_is_complete": 0.0,
            }
        return {
            "outcome_reference_price": _to_number(summary.reference_price),
            "outcome_mfe_pct": _to_number(summary.mfe_pct),
            "outcome_mfe_time_minutes": summary.mfe_time_minutes,
            "outcome_mae_pct": _to_number(summary.mae_pct),
            "outcome_mae_time_minutes": summary.mae_time_minutes,
            "outcome_mfe_mae_ratio": _to_number(summary.mfe_mae_ratio),
            "outcome_r_multiple": _to_number(summary.r_multiple),
            "outcome_eod_pct_change": _to_number(summary.eod_pct_change),
            "outcome_follow_through": _to_number(summary.follow_through),
            "outcome_gap_filled": _to_number(summary.gap_filled),
            "outcome_is_complete": _to_number(summary.is_complete) or 0.0,
        }

    def _snapshot_features(
        self,
        snapshot: ScannerOutcomeSnapshot | None,
    ) -> dict[str, Any]:
        if snapshot is None:
            return {
                "interval_key": None,
                "pct_change": None,
                "snapshot_reference_price": None,
                "snapshot_price": None,
                "snapshot_pct_change": None,
                "snapshot_high_since_signal": None,
                "snapshot_low_since_signal": None,
                "snapshot_volume_since_signal": None,
                "snapshot_status": None,
                "snapshot_captured_at": None,
            }
        return {
            "interval_key": snapshot.interval_key,
            "pct_change": _to_number(snapshot.pct_change),
            "snapshot_reference_price": _to_number(snapshot.reference_price),
            "snapshot_price": _to_number(snapshot.snapshot_price),
            "snapshot_pct_change": _to_number(snapshot.pct_change),
            "snapshot_high_since_signal": _to_number(snapshot.high_since_signal),
            "snapshot_low_since_signal": _to_number(snapshot.low_since_signal),
            "snapshot_volume_since_signal": snapshot.volume_since_signal,
            "snapshot_status": snapshot.status,
            "snapshot_captured_at": _serialize_value(snapshot.captured_at),
        }

    def _assign_scalar_or_category(
        self,
        target: dict[str, Any],
        key: str,
        value: Any,
    ) -> None:
        number = _to_number(value)
        if number is not None:
            target[key] = number
            return
        if value is None:
            target[key] = None
            return
        target[f"{key}_category"] = str(value)


def _safe_key(value: Any) -> str:
    raw = str(value or "unknown").strip().lower()
    normalized = _SAFE_KEY_RE.sub("_", raw).strip("_")
    return normalized or "unknown"


def _to_number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, (float, Decimal)):
        return float(value)
    return None


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
