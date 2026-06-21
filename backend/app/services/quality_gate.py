"""
QualityGateService — converts UniverseQualityReport data into a versioned quality_gate.v1
assessment. Split into a pure builder (no DB) and a thin DB-aware wrapper.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from app.schemas.quality_gate import (
    QualityGateAssessment,
    QualityGateIssue,
    QualityGatePolicy,
    QualityGateScope,
    QualityGateVerdict,
    QualityIssueCode,
)
from app.utils.time import utc_now


def _derive_verdict(
    issues: List[QualityGateIssue],
    policy: QualityGatePolicy,
) -> QualityGateVerdict:
    has_blocker = any(i.severity == "blocker" for i in issues)
    has_warning = any(i.severity == "warning" for i in issues)
    if has_blocker:
        return (
            QualityGateVerdict.blocked
            if policy == QualityGatePolicy.strict
            else QualityGateVerdict.warning
        )
    if has_warning:
        return QualityGateVerdict.warning
    return QualityGateVerdict.trusted


def _build_assessment(
    report_data: Optional[dict],
    data_requirements: Optional[dict],
    scope: QualityGateScope,
    policy: QualityGatePolicy,
) -> QualityGateAssessment:
    now = utc_now()

    if policy == QualityGatePolicy.off:
        return QualityGateAssessment(
            policy=policy,
            verdict=QualityGateVerdict.skipped,
            trusted=False,
            scope=scope,
            score=None,
            grade=None,
            issues=[],
            warnings=[],
            generated_at=now,
        )

    issues: List[QualityGateIssue] = []

    if report_data is None:
        sev: str = "blocker" if policy == QualityGatePolicy.strict else "warning"
        issues.append(
            QualityGateIssue(
                code=QualityIssueCode.missing_bars,
                severity=sev,
                message="No completed quality report found",
            )
        )
        verdict = _derive_verdict(issues, policy)
        return QualityGateAssessment(
            policy=policy,
            verdict=verdict,
            trusted=(verdict == QualityGateVerdict.trusted),
            scope=scope,
            score=None,
            grade=None,
            issues=issues,
            warnings=[i for i in issues if i.severity == "warning"],
            generated_at=now,
        )

    score = float(report_data.get("overall_score", 0.0))
    grade: Optional[str] = report_data.get("overall_grade")
    tickers = report_data.get("tickers", [])

    # missing_bars: gate on overall_score
    if score < 70:
        issues.append(
            QualityGateIssue(
                code=QualityIssueCode.missing_bars,
                severity="blocker",
                message=f"Coverage {score:.1f}% is below the 70% minimum threshold",
                detail={"coverage_pct": score},
            )
        )
    elif score < 85:
        issues.append(
            QualityGateIssue(
                code=QualityIssueCode.missing_bars,
                severity="warning",
                message=f"Coverage {score:.1f}% is below the 85% target threshold",
                detail={"coverage_pct": score},
            )
        )

    # provider_gap: gate on worst ticker continuity_score and any gap_count
    has_gap = any(t.get("gap_count", 0) >= 1 for t in tickers)
    worst_continuity = min(
        (t.get("continuity_score", 100.0) for t in tickers), default=100.0
    )
    if worst_continuity < 70:
        issues.append(
            QualityGateIssue(
                code=QualityIssueCode.provider_gap,
                severity="blocker",
                message=(
                    f"Worst ticker continuity {worst_continuity:.1f}% is below"
                    " the 70% threshold (>6 gaps)"
                ),
                detail={"worst_continuity_score": worst_continuity},
            )
        )
    elif has_gap:
        issues.append(
            QualityGateIssue(
                code=QualityIssueCode.provider_gap,
                severity="warning",
                message="One or more tickers have provider data gaps",
                detail={"worst_continuity_score": worst_continuity},
            )
        )

    # insufficient_lookback: only when data_requirements provided
    if data_requirements:
        timespans = data_requirements.get("timespans", [])
        if timespans:
            first_bars: List[date] = []
            for t in tickers:
                fb = t.get("first_bar")
                if fb:
                    try:
                        first_bars.append(date.fromisoformat(str(fb)[:10]))
                    except (ValueError, TypeError):
                        pass

            if not first_bars:
                issues.append(
                    QualityGateIssue(
                        code=QualityIssueCode.insufficient_lookback,
                        severity="blocker",
                        message="No first_bar data available to verify lookback coverage",
                    )
                )
            else:
                earliest = min(first_bars)
                today = utc_now().date()
                max_lookback = max(req.get("lookback_days", 0) for req in timespans)
                required_from = today - timedelta(days=max_lookback)
                if earliest > required_from:
                    issues.append(
                        QualityGateIssue(
                            code=QualityIssueCode.insufficient_lookback,
                            severity="blocker",
                            message=(
                                f"Earliest data ({earliest}) does not cover the"
                                f" {max_lookback}-day lookback window"
                                f" (need data from {required_from})"
                            ),
                            detail={
                                "earliest_first_bar": earliest.isoformat(),
                                "required_from": required_from.isoformat(),
                                "lookback_days": max_lookback,
                            },
                        )
                    )

    verdict = _derive_verdict(issues, policy)
    return QualityGateAssessment(
        policy=policy,
        verdict=verdict,
        trusted=(verdict == QualityGateVerdict.trusted),
        scope=scope,
        score=score,
        grade=grade,
        issues=issues,
        warnings=[i for i in issues if i.severity == "warning"],
        generated_at=now,
    )


class QualityGateService:
    @staticmethod
    def assess(
        db: Session,
        request,
    ) -> QualityGateAssessment:
        from app.models.scanner_config import ScannerConfig
        from app.models.universe_quality_report import UniverseQualityReport

        policy = QualityGatePolicy(request.policy)
        scope = QualityGateScope(
            universe_id=request.universe_id,
            ticker=getattr(request, "ticker", None),
            scanner_type=getattr(request, "scanner_type", None),
        )

        report = (
            db.query(UniverseQualityReport)
            .filter(UniverseQualityReport.universe_id == request.universe_id)
            .first()
        )
        report_data: Optional[dict] = (
            report.report_data if report and report.status == "complete" else None
        )

        data_requirements: Optional[dict] = None
        if scope.scanner_type:
            config = (
                db.query(ScannerConfig)
                .filter(ScannerConfig.scanner_type == scope.scanner_type)
                .first()
            )
            if config:
                data_requirements = config.data_requirements

        return _build_assessment(report_data, data_requirements, scope, policy)
