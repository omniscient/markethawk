from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
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

    def latest_performance(
        self,
        db: Session,
        *,
        scanner_type: str,
        start_date: date | None = None,
        end_date: date | None = None,
        severity: str | None = None,
        min_sample_size: int = 5,
    ) -> dict[str, Any]:
        run = (
            db.query(SignalAnalysisRun)
            .filter(
                SignalAnalysisRun.status == "completed",
                SignalAnalysisRun.scanner_type == scanner_type,
            )
            .order_by(SignalAnalysisRun.completed_at.desc(), SignalAnalysisRun.id.desc())
            .first()
        )
        filters = {
            "scanner_type": scanner_type,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "severity": severity,
            "min_sample_size": min_sample_size,
        }
        if not run:
            return {
                "analysis_run_id": None,
                "scanner_type": scanner_type,
                "event_count": 0,
                "filters": filters,
                "warnings": [
                    {
                        "code": "no_explanation_archetypes",
                        "message": "No completed explanation archetype run is available.",
                    }
                ],
                "archetypes": [],
            }

        clusters = (
            db.query(SignalCluster)
            .filter(SignalCluster.analysis_run_id == run.id)
            .order_by(SignalCluster.cluster_index)
            .all()
        )
        archetypes = [
            self._cluster_payload(
                db,
                cluster,
                scanner_type=scanner_type,
                start_date=start_date,
                end_date=end_date,
                severity=severity,
                min_sample_size=min_sample_size,
            )
            for cluster in clusters
        ]
        return {
            "analysis_run_id": run.id,
            "scanner_type": scanner_type,
            "event_count": sum(item["sample_size"] for item in archetypes),
            "filters": filters,
            "warnings": [],
            "archetypes": archetypes,
        }

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

    def _cluster_payload(
        self,
        db: Session,
        cluster: SignalCluster,
        *,
        scanner_type: str,
        start_date: date | None,
        end_date: date | None,
        severity: str | None,
        min_sample_size: int,
    ) -> dict[str, Any]:
        rows = self._cluster_rows(
            db,
            cluster.id,
            scanner_type=scanner_type,
            start_date=start_date,
            end_date=end_date,
            severity=severity,
        )
        return_profile = _return_profile([summary for _, summary in rows])
        sample_size = len(rows)
        return {
            "cluster_id": cluster.id,
            "cluster_index": cluster.cluster_index,
            "label": cluster.label,
            "sample_size": sample_size,
            "event_ids": sorted(event.id for event, _ in rows),
            "centroid": cluster.centroid or {},
            "return_profile": return_profile,
            "warnings": _sample_warnings(sample_size, min_sample_size),
        }

    def _cluster_rows(
        self,
        db: Session,
        cluster_id: int,
        *,
        scanner_type: str,
        start_date: date | None,
        end_date: date | None,
        severity: str | None,
    ) -> list[tuple[ScannerEvent, ScannerOutcomeSummary]]:
        query = (
            db.query(ScannerEvent, ScannerOutcomeSummary)
            .join(
                ScannerOutcomeSummary,
                ScannerOutcomeSummary.scanner_event_id == ScannerEvent.id,
            )
            .filter(
                ScannerEvent.signal_cluster_id == cluster_id,
                ScannerEvent.scanner_type == scanner_type,
                ScannerOutcomeSummary.is_complete.is_(True),
            )
        )
        if start_date:
            query = query.filter(ScannerEvent.event_date >= start_date)
        if end_date:
            query = query.filter(ScannerEvent.event_date <= end_date)
        if severity:
            query = query.filter(ScannerEvent.severity == severity)
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


def _return_profile(summaries: list[ScannerOutcomeSummary]) -> dict[str, Any]:
    eod_values = _float_values(summary.eod_pct_change for summary in summaries)
    follow_values = [
        bool(summary.follow_through)
        for summary in summaries
        if summary.follow_through is not None
    ]
    wins = sum(1 for value in eod_values if value > 0)
    return {
        "sample_size": len(summaries),
        "win_rate_pct": _pct(wins, len(eod_values)),
        "follow_through_rate_pct": _pct(
            sum(1 for value in follow_values if value),
            len(follow_values),
        ),
        "avg_mfe_pct": _mean(_float_values(summary.mfe_pct for summary in summaries)),
        "avg_mae_pct": _mean(_float_values(summary.mae_pct for summary in summaries)),
        "avg_eod_pct_change": _mean(eod_values),
    }


def _sample_warnings(sample_size: int, min_sample_size: int) -> list[dict[str, str]]:
    if sample_size >= min_sample_size:
        return []
    return [
        {
            "code": "weak_archetype_sample",
            "message": (
                f"Only {sample_size} events matched this archetype; "
                f"minimum recommended sample is {min_sample_size}."
            ),
        }
    ]


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
