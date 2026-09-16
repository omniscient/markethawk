from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_snapshot import ScannerOutcomeSnapshot
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.models.signal_cluster import SignalCluster
from app.services.historical_analog_service import HistoricalAnalogService


class AISignalBriefService:
    """Build deterministic, LLM-free signal brief payloads."""

    schema_version = "ai_signal_brief.v1"

    def __init__(self, analog_service: HistoricalAnalogService | None = None) -> None:
        self._analog_service = analog_service or HistoricalAnalogService()

    def build(self, db: Session, event: ScannerEvent) -> dict[str, Any]:
        explanation = event.explanation or {}
        summary = (
            db.query(ScannerOutcomeSummary)
            .filter(ScannerOutcomeSummary.scanner_event_id == event.id)
            .first()
        )
        snapshots = (
            db.query(ScannerOutcomeSnapshot)
            .filter(ScannerOutcomeSnapshot.scanner_event_id == event.id)
            .order_by(ScannerOutcomeSnapshot.interval_key)
            .all()
        )
        analog_result = self._analog_service.find_similar_events(
            db,
            target_event_id=event.id,
            limit=3,
            min_sample_size=5,
        )
        archetype = self._archetype_payload(db, event)
        warnings = list(explanation.get("data_quality_warnings") or [])
        warnings.extend(analog_result.get("warnings") or [])

        return {
            "schema_version": self.schema_version,
            "event_id": event.id,
            "facts": self._facts(event),
            "why": list(explanation.get("why") or []),
            "risks": self._risks(event, explanation, summary, warnings),
            "warnings": warnings,
            "analogs": analog_result.get("analogs", []),
            "outcome_context": {
                "summary": self._summary_payload(summary),
                "snapshots": [self._snapshot_payload(snapshot) for snapshot in snapshots],
            },
            "archetype": archetype,
            "forbidden_claims": [
                "Do not present this brief as investment advice.",
                "Do not claim guaranteed future returns.",
                "Do not claim an LLM inferred facts beyond this payload.",
                "Do not recommend live trade execution from this brief alone.",
            ],
        }

    def _facts(self, event: ScannerEvent) -> dict[str, Any]:
        return {
            "ticker": event.ticker,
            "event_date": event.event_date.isoformat() if event.event_date else None,
            "scanner_type": event.scanner_type,
            "severity": event.severity,
            "summary": event.summary,
            "signal_quality_score": _serialize(event.signal_quality_score),
            "regime": event.regime,
        }

    def _risks(
        self,
        event: ScannerEvent,
        explanation: dict[str, Any],
        summary: ScannerOutcomeSummary | None,
        warnings: list[dict[str, Any]],
    ) -> list[str]:
        risks = []
        if not explanation:
            risks.append("Scanner explanation is missing.")
        for criterion in (explanation.get("criteria_failed") or {}).values():
            label = criterion.get("label") or "A scanner criterion"
            risks.append(f"{label} did not pass.")
        if explanation.get("data_quality_warnings"):
            risks.append("Data quality warnings are present.")
        if summary is None or not summary.is_complete:
            risks.append("Outcome summary is incomplete or unavailable.")
        if any(warning.get("code") == "no_historical_analogs" for warning in warnings):
            risks.append("No historical analogs were available.")
        if event.signal_cluster_id is None:
            risks.append("No explanation-aware archetype is assigned yet.")
        return risks

    def _archetype_payload(
        self,
        db: Session,
        event: ScannerEvent,
    ) -> dict[str, Any] | None:
        if event.signal_cluster_id is None:
            return None
        cluster = (
            db.query(SignalCluster)
            .filter(SignalCluster.id == event.signal_cluster_id)
            .first()
        )
        if cluster is None:
            return None
        return {
            "cluster_id": cluster.id,
            "label": cluster.label,
            "event_count": cluster.event_count,
            "centroid": cluster.centroid or {},
            "return_profile": cluster.return_profile or {},
        }

    def _summary_payload(
        self,
        summary: ScannerOutcomeSummary | None,
    ) -> dict[str, Any] | None:
        if summary is None:
            return None
        return {
            "scanner_event_id": summary.scanner_event_id,
            "reference_price": _serialize(summary.reference_price),
            "mfe_pct": _serialize(summary.mfe_pct),
            "mae_pct": _serialize(summary.mae_pct),
            "mfe_mae_ratio": _serialize(summary.mfe_mae_ratio),
            "r_multiple": _serialize(summary.r_multiple),
            "eod_pct_change": _serialize(summary.eod_pct_change),
            "follow_through": summary.follow_through,
            "gap_filled": summary.gap_filled,
            "is_complete": summary.is_complete,
        }

    def _snapshot_payload(self, snapshot: ScannerOutcomeSnapshot) -> dict[str, Any]:
        return {
            "interval_key": snapshot.interval_key,
            "pct_change": _serialize(snapshot.pct_change),
            "snapshot_price": _serialize(snapshot.snapshot_price),
            "status": snapshot.status,
            "captured_at": snapshot.captured_at.isoformat()
            if snapshot.captured_at
            else None,
        }


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value
