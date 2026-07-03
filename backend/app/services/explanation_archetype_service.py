from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session

from app.models.scanner_event import ScannerEvent
from app.models.scanner_outcome_summary import ScannerOutcomeSummary
from app.models.signal_analysis_run import SignalAnalysisRun
from app.models.signal_cluster import SignalCluster
from app.utils.time import utc_now


class ExplanationArchetypeService:
    """Generate deterministic explanation-aware signal archetypes."""

    def generate(
        self,
        db: Session,
        *,
        scanner_type: str | None = None,
        min_sample_size: int = 20,
    ) -> dict[str, Any]:
        rows = self._query_rows(db, scanner_type=scanner_type)
        if len(rows) < min_sample_size:
            return {
                "status": "insufficient_data",
                "event_count": len(rows),
                "filters": {
                    "scanner_type": scanner_type,
                    "min_sample_size": min_sample_size,
                },
                "warnings": [
                    {
                        "code": "insufficient_archetype_sample",
                        "message": (
                            f"Only {len(rows)} complete events were available; "
                            f"minimum required sample is {min_sample_size}."
                        ),
                    }
                ],
                "archetypes": [],
            }

        grouped = self._group_rows(rows)
        run = SignalAnalysisRun(
            status="completed",
            scanner_type=scanner_type,
            event_count=len(rows),
            completed_at=utc_now(),
        )
        db.add(run)
        db.flush()

        archetypes = []
        for cluster_index, group in enumerate(self._rank_groups(grouped)):
            label = group.label()
            cluster = SignalCluster(
                analysis_run_id=run.id,
                cluster_index=cluster_index,
                label=label,
                centroid=group.centroid(),
                return_profile=group.return_profile(),
                event_count=len(group.event_ids),
            )
            db.add(cluster)
            db.flush()
            for event in group.events:
                event.signal_cluster_id = cluster.id
            archetypes.append(group.payload(cluster, cluster_index, label))

        db.commit()
        return {
            "status": "completed",
            "analysis_run_id": run.id,
            "event_count": len(rows),
            "filters": {
                "scanner_type": scanner_type,
                "min_sample_size": min_sample_size,
            },
            "warnings": [],
            "archetypes": archetypes,
        }

    def _query_rows(
        self,
        db: Session,
        *,
        scanner_type: str | None,
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
        return query.order_by(ScannerEvent.event_date.asc(), ScannerEvent.id.asc()).all()

    def _group_rows(
        self,
        rows: list[tuple[ScannerEvent, ScannerOutcomeSummary]],
    ) -> list["_ArchetypeGroup"]:
        groups: dict[tuple[str, ...], _ArchetypeGroup] = {}
        for event, summary in rows:
            traits = _traits_for_event(event)
            signature = tuple(sorted(trait.key for trait in traits))
            group = groups.get(signature)
            if group is None:
                group = _ArchetypeGroup(traits=traits)
                groups[signature] = group
            group.add(event, summary)
        return list(groups.values())

    def _rank_groups(
        self,
        groups: list["_ArchetypeGroup"],
    ) -> list["_ArchetypeGroup"]:
        return sorted(
            groups,
            key=lambda group: (
                -group.win_rate(),
                -group.avg_mfe(),
                group.driver_label_text(),
            ),
        )


@dataclass(frozen=True)
class _Trait:
    key: str
    label: str
    priority: int


@dataclass
class _ArchetypeGroup:
    traits: list[_Trait]
    events: list[ScannerEvent] = field(default_factory=list)
    summaries: list[ScannerOutcomeSummary] = field(default_factory=list)

    @property
    def event_ids(self) -> list[int]:
        return [event.id for event in self.events]

    def add(self, event: ScannerEvent, summary: ScannerOutcomeSummary) -> None:
        self.events.append(event)
        self.summaries.append(summary)

    def driver_traits(self) -> list[_Trait]:
        return sorted(self.traits, key=lambda trait: (trait.priority, trait.label))[:2]

    def driver_label_text(self) -> str:
        return " + ".join(trait.label for trait in self.driver_traits()) or "Signals"

    def label(self) -> str:
        suffix = "Positive Outcomes" if self.win_rate() >= 50 else "Weak Outcomes"
        return f"{self.driver_label_text()} / {suffix}"

    def avg_mfe(self) -> float:
        return _mean(_float_values(summary.mfe_pct for summary in self.summaries)) or 0.0

    def win_rate(self) -> float:
        eod_values = _float_values(summary.eod_pct_change for summary in self.summaries)
        if not eod_values:
            return 0.0
        return round(sum(1 for value in eod_values if value > 0) / len(eod_values) * 100, 2)

    def return_profile(self) -> dict[str, Any]:
        eod_values = _float_values(summary.eod_pct_change for summary in self.summaries)
        follow_values = [
            bool(summary.follow_through)
            for summary in self.summaries
            if summary.follow_through is not None
        ]
        return {
            "sample_size": len(self.events),
            "win_rate_pct": self.win_rate(),
            "follow_through_rate_pct": _pct(
                sum(1 for value in follow_values if value),
                len(follow_values),
            ),
            "avg_mfe_pct": self.avg_mfe(),
            "avg_mae_pct": _mean(
                _float_values(summary.mae_pct for summary in self.summaries)
            ),
            "avg_eod_pct_change": _mean(eod_values),
        }

    def centroid(self) -> dict[str, Any]:
        return {
            "traits": {trait.key: 1.0 for trait in self.traits},
            "trait_labels": {trait.key: trait.label for trait in self.traits},
            "sample_size": len(self.events),
        }

    def payload(
        self,
        cluster: SignalCluster,
        cluster_index: int,
        label: str,
    ) -> dict[str, Any]:
        return {
            "cluster_id": cluster.id,
            "cluster_index": cluster_index,
            "label": label,
            "sample_size": len(self.events),
            "event_ids": sorted(self.event_ids),
            "trait_drivers": [trait.key for trait in self.driver_traits()],
            "centroid": cluster.centroid,
            "return_profile": cluster.return_profile,
        }


def _traits_for_event(event: ScannerEvent) -> list[_Trait]:
    explanation = event.explanation or {}
    traits: list[_Trait] = []
    for criterion_id, criterion in (explanation.get("criteria_passed") or {}).items():
        traits.append(
            _Trait(
                key=criterion_id,
                label=str(criterion.get("label") or criterion_id),
                priority=10,
            )
        )
    for criterion_id, criterion in (explanation.get("criteria_failed") or {}).items():
        traits.append(
            _Trait(
                key=criterion_id,
                label=str(criterion.get("label") or criterion_id),
                priority=20,
            )
        )
    for warning in explanation.get("data_quality_warnings") or []:
        code = str(warning.get("code") or "quality_gate_warning")
        traits.append(_Trait(key=f"warning:{code}", label=_title_from_key(code), priority=15))
    for name, value in (explanation.get("confidence_inputs") or {}).items():
        bucket = _confidence_bucket(value)
        if bucket:
            traits.append(
                _Trait(
                    key=f"confidence:{name}:{bucket}",
                    label=f"{name} {bucket}",
                    priority=30,
                )
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


def _title_from_key(value: str) -> str:
    return value.replace("_", " ").replace(".", " ").title()


def _float_values(values) -> list[float]:
    return [converted for value in values if (converted := _to_float(value)) is not None]


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(mean(values), 4)


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator * 100, 2)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int | float | Decimal):
        return float(value)
    return None
