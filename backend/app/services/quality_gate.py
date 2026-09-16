"""
QualityGateService — converts UniverseQualityReport data into a versioned quality_gate.v1
assessment. Split into a pure builder (no DB) and a thin DB-aware wrapper.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.schemas.quality_gate import (
    QualityGateAssessment,
    QualityGateIssue,
    QualityGatePolicy,
    QualityGateScope,
    QualityGateServiceProtocol,
    QualityGateVerdict,
    QualityIssueCode,
)
from app.utils.time import to_utc_naive, utc_now

# Reuse the freshness window used elsewhere (system_service): a quality report
# snapshot older than this can no longer certify per-ticker freshness.
STALE_REPORT_MAX_AGE_HOURS = 4
# Intraday timespans tolerate far less staleness than daily+ resolutions.
INTRADAY_TIMESPANS = ("minute", "hour")


def _parse_iso_datetime(value) -> Optional[datetime]:
    """Parse an ISO timestamp (tz-aware or naive) to naive UTC; None on failure."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    return to_utc_naive(parsed)


def _parse_iso_date(value) -> Optional[date]:
    """Parse the date portion of an ISO string; None on failure."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _median(values: List[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _trading_days_stale(
    last_bar: date,
    reference: date,
    holidays: Set[date],
    cap: int,
) -> int:
    """
    Count trading days (weekday and not a full-close holiday) strictly after
    ``last_bar`` up to and including ``reference``. Returns 0 when the data
    already covers ``reference``. Stops counting once the result exceeds
    ``cap`` (the verdict only needs to know it crossed the threshold), so the
    loop stays bounded even for very old data.
    """
    if reference <= last_bar:
        return 0
    count = 0
    day = last_bar + timedelta(days=1)
    while day <= reference:
        if day.weekday() < 5 and day not in holidays:
            count += 1
            if count > cap:
                return count
        day += timedelta(days=1)
    return count


def _stale_threshold(policy: QualityGatePolicy, timespan) -> Tuple[int, str]:
    """Return (max acceptable trading-day staleness, issue severity)."""
    if policy == QualityGatePolicy.strict:
        return 1, "blocker"
    # advisory: looser tolerances, warning severity
    if timespan in INTRADAY_TIMESPANS:
        return 5, "warning"
    return 7, "warning"


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
    market_holidays: Optional[Set[date]] = None,
    survivorship_scope: bool = False,
) -> QualityGateAssessment:
    """
    Build a quality_gate.v1 assessment from report data dicts (no DB access).

    ``survivorship_scope`` is a derived boolean threaded in from
    ``QualityGateService.assess()`` — True only for historical-analysis consumers
    (backtesting/scorecard). It exists because MarketHawk has **no delisted-symbol
    tracking today**: neither ``StockUniverse`` nor ``StockUniverseTicker`` carries
    a ``delisted_date`` / ``survivorship_safe`` field, so a universe assembled
    "as of today" silently excludes symbols delisted before the run. Current
    metadata therefore **cannot prove** any universe is survivorship-safe, so every
    historical-analysis scope is flagged as potentially biased. We keep this as a
    pure-function boolean (not a DB query) so ``_build_assessment`` stays DB-free,
    mirroring the ``market_holidays`` threading pattern (#499).
    """
    now = utc_now()
    holidays: Set[date] = market_holidays if market_holidays is not None else set()

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

    # survivorship_bias (#501): historical-analysis scopes (backtesting/scorecard)
    # cannot prove their universe is free of survivorship bias — see the function
    # docstring for the metadata gap. Severity is policy-driven so the *policy*
    # doubles as the trusted-vs-exploratory toggle: strict → blocker (a trusted
    # backtest/scorecard refuses biased data), advisory → warning (exploratory:
    # proceeds but is visibly not-trusted). policy=off already short-circuited
    # above. No DB query lives here; the bool is derived in assess().
    #
    # FUTURE UNBLOCK: once delisted-symbol tracking exists (e.g. a
    # StockUniverseTicker.delisted_date column + a universe-level survivorship_safe
    # marker), assess() can pass survivorship_scope=False for proven-safe universes
    # and this issue stops firing.
    if survivorship_scope:
        sev = "blocker" if policy == QualityGatePolicy.strict else "warning"
        issues.append(
            QualityGateIssue(
                code=QualityIssueCode.survivorship_bias,
                severity=sev,
                message=(
                    "Universe survivorship safety is unproven — MarketHawk has no"
                    " delisted-symbol tracking, so this historical-analysis scope"
                    " may exclude symbols delisted before the run"
                ),
                detail={
                    "reason": (
                        "universe survivorship safety unproven — no delisted-symbol"
                        " tracking"
                    ),
                    "consumer_scope": "historical",
                },
            )
        )

    if report_data is None:
        sev = "blocker" if policy == QualityGatePolicy.strict else "warning"
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

    # missing_bars: gate on overall_score.
    # NOTE: missing_bars is intentionally overloaded here for coverage checks
    # (no completed report vs. coverage below threshold). Both conditions signal
    # that bar data is insufficient; callers should inspect the message/detail
    # for the specific reason. This is a documented overload of the stable code.
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

    # stale_quote: report-freshness guard, then per-ticker staleness.
    # The report-freshness guard fires a single scope-level issue when the
    # snapshot itself is too old to certify per-ticker freshness; when it fires
    # the per-ticker loop is skipped (the scope issue already covers everything).
    # An optional ``as_of_date`` in data_requirements shifts the reference date
    # for historical/backtest consumers (and disables the freshness guard, which
    # only makes sense for live "now" consumers).
    as_of_date = _parse_iso_date((data_requirements or {}).get("as_of_date"))
    reference_date = as_of_date or now.date()
    report_stale_emitted = False

    if as_of_date is None:
        generated_at = _parse_iso_datetime(report_data.get("generated_at"))
        if generated_at is not None:
            age_hours = (now - generated_at).total_seconds() / 3600.0
            if age_hours > STALE_REPORT_MAX_AGE_HOURS:
                sev = "blocker" if policy == QualityGatePolicy.strict else "warning"
                issues.append(
                    QualityGateIssue(
                        code=QualityIssueCode.stale_quote,
                        severity=sev,
                        message=(
                            "Quality report is stale (generated"
                            f" {generated_at.isoformat()}, {age_hours:.1f}h ago,"
                            f" exceeds {STALE_REPORT_MAX_AGE_HOURS}h)"
                        ),
                        detail={
                            "subtype": "report_stale",
                            "ticker": None,
                            "generated_at": report_data.get("generated_at"),
                            "age_hours": round(age_hours, 1),
                            "threshold_hours": STALE_REPORT_MAX_AGE_HOURS,
                            "as_of_date": None,
                            "source": None,
                        },
                    )
                )
                report_stale_emitted = True

    if not report_stale_emitted:
        for t in tickers:
            last_bar_date = _parse_iso_date(t.get("last_bar"))
            if last_bar_date is None:
                # Total absence is handled by the provider_gap "absent" subtype.
                continue
            if as_of_date is not None and last_bar_date >= as_of_date:
                # Data already covers the requested historical date → fresh.
                continue
            threshold, sev = _stale_threshold(policy, t.get("timespan"))
            stale_days = _trading_days_stale(
                last_bar_date, reference_date, holidays, threshold
            )
            if stale_days > threshold:
                issues.append(
                    QualityGateIssue(
                        code=QualityIssueCode.stale_quote,
                        severity=sev,
                        message=(
                            f"{t.get('ticker')} last bar"
                            f" {last_bar_date.isoformat()} is {stale_days} trading"
                            f" day(s) stale (threshold {threshold})"
                        ),
                        detail={
                            "subtype": "ticker_stale",
                            "ticker": t.get("ticker"),
                            "timespan": t.get("timespan"),
                            "multiplier": t.get("multiplier"),
                            "last_bar": t.get("last_bar"),
                            "trading_days_stale": stale_days,
                            "threshold_trading_days": threshold,
                            "as_of_date": (
                                as_of_date.isoformat() if as_of_date else None
                            ),
                            "source": None,
                        },
                    )
                )

    # provider_gap: absent (zero bars) + partial (low coverage) + structural.
    # absent/partial are per-ticker and only apply to reports that carry the
    # coverage fields (real reports always do; legacy/synthetic entries without
    # an ``actual_bars`` key fall through to the retained structural check).
    coverages = [
        t["coverage_pct"]
        for t in tickers
        if (t.get("actual_bars") or 0) > 0 and t.get("coverage_pct") is not None
    ]
    universe_median_coverage = _median(coverages) if coverages else None

    for t in tickers:
        actual_bars = t.get("actual_bars")
        if actual_bars is None:
            continue
        if actual_bars == 0:
            # Provider returned nothing for a ticker that was asked for. Never
            # acceptable, so severity=blocker regardless of policy (advisory
            # still downgrades the verdict via _derive_verdict).
            issues.append(
                QualityGateIssue(
                    code=QualityIssueCode.provider_gap,
                    severity="blocker",
                    message=f"{t.get('ticker')} returned zero bars from the provider",
                    detail={
                        "subtype": "absent",
                        "ticker": t.get("ticker"),
                        "timespan": t.get("timespan"),
                        "multiplier": t.get("multiplier"),
                        "actual_bars": 0,
                        "expected_bars": t.get("expected_bars"),
                        "source": None,
                    },
                )
            )
            continue
        coverage_pct = t.get("coverage_pct")
        if coverage_pct is None:
            continue
        is_partial = coverage_pct < 50 or (
            universe_median_coverage is not None
            and coverage_pct < 80
            and coverage_pct < universe_median_coverage - 30
        )
        if is_partial:
            sev = "blocker" if policy == QualityGatePolicy.strict else "warning"
            issues.append(
                QualityGateIssue(
                    code=QualityIssueCode.provider_gap,
                    severity=sev,
                    message=(
                        f"{t.get('ticker')} coverage {coverage_pct:.1f}% indicates"
                        " a partial provider return"
                    ),
                    detail={
                        "subtype": "partial",
                        "ticker": t.get("ticker"),
                        "timespan": t.get("timespan"),
                        "multiplier": t.get("multiplier"),
                        "coverage_pct": coverage_pct,
                        "universe_median_coverage": universe_median_coverage,
                        "actual_bars": actual_bars,
                        "expected_bars": t.get("expected_bars"),
                        "source": None,
                    },
                )
            )

    # structural: retained #492 gap-based detection (universe-level worst case).
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
                detail={
                    "subtype": "structural",
                    "worst_continuity_score": worst_continuity,
                },
            )
        )
    elif has_gap:
        issues.append(
            QualityGateIssue(
                code=QualityIssueCode.provider_gap,
                severity="warning",
                message="One or more tickers have provider data gaps",
                detail={
                    "subtype": "structural",
                    "worst_continuity_score": worst_continuity,
                },
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

            parse_failures = len(tickers) - len(first_bars)
            if parse_failures > 0:
                import logging

                logging.getLogger(__name__).warning(
                    "quality_gate: %d ticker(s) had unparseable first_bar values"
                    " and were excluded from lookback check",
                    parse_failures,
                )

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
                today = now.date()
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
    def assess(
        self,
        db: Session,
        request,
    ) -> QualityGateAssessment:
        from app.models.market_holiday import MarketHoliday
        from app.models.scanner_config import ScannerConfig
        from app.models.universe_quality_report import UniverseQualityReport

        try:
            policy = QualityGatePolicy(request.policy)
        except ValueError:
            scope = QualityGateScope(
                universe_id=request.universe_id,
                ticker=getattr(request, "ticker", None),
                scanner_type=getattr(request, "scanner_type", None),
            )
            now = utc_now()
            return QualityGateAssessment(
                policy=QualityGatePolicy.off,
                verdict=QualityGateVerdict.blocked,
                trusted=False,
                scope=scope,
                score=None,
                grade=None,
                issues=[
                    QualityGateIssue(
                        code=QualityIssueCode.missing_bars,
                        severity="blocker",
                        message=f"Unknown policy value: {request.policy!r}",
                    )
                ],
                warnings=[],
                generated_at=now,
            )
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

        # If the caller supplied explicit requirements and the scanner_type lookup
        # produced nothing, use the caller's requirements as a fallback so they
        # are not silently ignored.
        if (
            data_requirements is None
            and getattr(request, "requirements", None) is not None
        ):
            data_requirements = request.requirements.model_dump()

        # Trading-day staleness thresholds respect the NYSE full-close calendar.
        # We resolve it here (where a DB session exists) into a plain date set so
        # _build_assessment stays a pure, DB-free function (no MAX(timestamp) or
        # per-ticker live queries). Only needed when a report is present, since
        # the stale-quote checks run against report_data tickers.
        market_holidays: Optional[Set[date]] = None
        if report_data is not None:
            holiday_rows = (
                db.query(MarketHoliday.date)
                .filter(
                    MarketHoliday.exchange == "NYSE",
                    MarketHoliday.event_type == "full_close",
                )
                .all()
            )
            market_holidays = {row.date for row in holiday_rows}

        # Survivorship bias only applies to historical-analysis consumers; live /
        # forward consumers (scanner, auto_trading, ui) are exempt. The policy then
        # selects strict (blocker) vs advisory (warning) inside _build_assessment.
        survivorship_scope = getattr(request, "consumer", None) in (
            "backtesting",
            "scorecard",
        )

        return _build_assessment(
            report_data,
            data_requirements,
            scope,
            policy,
            market_holidays=market_holidays,
            survivorship_scope=survivorship_scope,
        )


quality_gate_service: QualityGateServiceProtocol = QualityGateService()
