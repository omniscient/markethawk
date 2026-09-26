"""
Degraded-feed assessment for pre-market scans (#388, ADR-0013).

Pure functions (no DB, no Redis) that map a ProviderHealthSnapshot and the
pre-market scan's per-day ingestion diagnostics to provider_gap findings, plus
apply_provider_gaps(), which folds findings into ScannerRun.quality_gate and
ScannerRun.data_degraded. Posture per failure class (ADR-0013):

  breaker open / error rate over threshold -> blocker, stop the scan
  elevated latency                         -> warning, continue
  no fresh pre-market minute bars          -> blocker, complete + mark (+ page)
  partial pre-market coverage              -> warning, complete + mark

Live findings carry detail.subtype == "live_degradation" so they are
distinguishable from the historical provider_gap evidence (absent / partial /
structural) that QualityGateService already emits from UniverseQualityReport.
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Set
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.provider_health import ProviderHealthSnapshot
from app.schemas.quality_gate import (
    QualityGateAssessment,
    QualityGateIssue,
    QualityGatePolicy,
    QualityGateScope,
    QualityGateVerdict,
    QualityIssueCode,
)
from app.services.quality_gate import _derive_verdict
from app.utils.time import ensure_utc, utc_now

_ET = ZoneInfo("America/New_York")
_PREMARKET_OPEN = time(4, 0)
_REGULAR_OPEN = time(9, 30)
LIVE_SUBTYPE = "live_degradation"


@dataclass(frozen=True)
class ProviderGapFinding:
    severity: str  # "blocker" | "warning"
    reason: str
    message: str
    abort: bool = False
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_issue(self, provider: str, worker: Optional[str]) -> QualityGateIssue:
        return QualityGateIssue(
            code=QualityIssueCode.provider_gap,
            severity=self.severity,
            message=self.message,
            detail={
                "subtype": LIVE_SUBTYPE,
                "provider": provider,
                "reason": self.reason,
                "worker": worker,
                **self.detail,
            },
        )


def is_live_session_day(
    event_date: date,
    now_utc: datetime,
    market_holidays: Optional[Set[date]] = None,
) -> bool:
    """True when event_date is today's ET *trading* session and pre-market has opened.

    ``market_holidays`` is the NYSE full-close date set. It must be supplied by
    callers that act on the result: _run_universe_scan_logic builds
    ``trading_days`` with a ``weekday() < 5`` filter only, so a weekday NYSE
    holiday reaches here. On such a day there are legitimately no pre-market
    minute bars, and without this guard assess_premarket_ingestion would emit a
    blocker `no_fresh_premarket_bars` finding and page (#388 review finding A1).
    """
    now_et = ensure_utc(now_utc).astimezone(_ET)
    if event_date != now_et.date() or now_et.time() < _PREMARKET_OPEN:
        return False
    return event_date not in (market_holidays or set())


def assess_provider_health(
    snapshot: ProviderHealthSnapshot,
) -> List[ProviderGapFinding]:
    findings: List[ProviderGapFinding] = []
    if snapshot.breaker_state == "open":
        where = ", ".join(snapshot.breaker_open_workers) or "a worker"
        findings.append(
            ProviderGapFinding(
                severity="blocker",
                reason="breaker_open",
                message=f"Polygon circuit breaker open ({where}) — provider unavailable",
                abort=True,
                detail={"breaker_open_workers": list(snapshot.breaker_open_workers)},
            )
        )
    if (
        snapshot.calls_error_window >= settings.PROVIDER_HEALTH_MIN_CALLS
        and snapshot.error_rate >= settings.POLYGON_HEALTH_ERROR_RATE_THRESHOLD
    ):
        findings.append(
            ProviderGapFinding(
                severity="blocker",
                reason="error_rate",
                message=(
                    f"Polygon error rate {snapshot.error_rate:.0%} over the last "
                    f"{settings.PROVIDER_HEALTH_ERROR_WINDOW_SECONDS // 60} min "
                    f"({snapshot.errors_error_window}/{snapshot.calls_error_window} calls)"
                ),
                abort=True,
                detail={
                    "error_rate": round(snapshot.error_rate, 4),
                    "calls": snapshot.calls_error_window,
                },
            )
        )
    # Strictly greater, not >=: latency_p95_seconds is quantised to the upper
    # bound of the LATENCY_BUCKETS bucket the p95 falls in, so a real p95
    # anywhere in (2.5s, 5.0s] is reported as exactly 5.0. With >= that marked
    # every ordinary slow-but-healthy window degraded. > means "p95 landed in a
    # bucket above the threshold", and matches the Grafana rule's `$B > 5`.
    if (
        snapshot.latency_p95_seconds is not None
        and snapshot.latency_p95_seconds
        > settings.POLYGON_HEALTH_LATENCY_P95_THRESHOLD_SECONDS
    ):
        findings.append(
            ProviderGapFinding(
                severity="warning",
                reason="latency",
                message=(
                    f"Polygon p95 latency {snapshot.latency_p95_seconds:.1f}s is "
                    "elevated — data may be arriving late"
                ),
                detail={"latency_p95_seconds": snapshot.latency_p95_seconds},
            )
        )
    return findings


def assess_premarket_ingestion(
    diagnostics: Dict[str, Any],
    event_date: date,
    now_utc: datetime,
    market_holidays: Optional[Set[date]] = None,
) -> List[ProviderGapFinding]:
    """Universe-wide ingestion health from run_pre_market_scan diagnostics_out."""
    if not is_live_session_day(event_date, now_utc, market_holidays):
        return []
    now_aware = ensure_utc(now_utc)
    now_et = now_aware.astimezone(_ET)
    staleness = timedelta(minutes=settings.PREMARKET_BAR_STALENESS_MINUTES)
    pm_open_et = datetime.combine(event_date, _PREMARKET_OPEN, tzinfo=_ET)
    if now_et < pm_open_et + staleness:
        return []  # too early in the session to judge ingestion

    findings: List[ProviderGapFinding] = []
    if diagnostics.get("tickers") == 0:
        # An empty universe has no pre-market bars by construction. Reporting it
        # as a Polygon ingestion stall would page on a misconfigured universe.
        return findings
    max_bar_iso = diagnostics.get("max_premarket_bar_ts")
    if max_bar_iso is None:
        findings.append(
            ProviderGapFinding(
                severity="blocker",
                reason="no_fresh_premarket_bars",
                message=(
                    f"No pre-market minute bars ingested for {event_date.isoformat()} "
                    "— Polygon ingestion appears stalled"
                ),
            )
        )
    else:
        max_bar = ensure_utc(datetime.fromisoformat(max_bar_iso))
        regular_open_et = datetime.combine(event_date, _REGULAR_OPEN, tzinfo=_ET)
        age = now_aware - max_bar
        if now_et < regular_open_et and age > staleness:
            minutes = round(age.total_seconds() / 60, 1)
            findings.append(
                ProviderGapFinding(
                    severity="blocker",
                    reason="stale_premarket_bars",
                    message=(
                        f"Freshest pre-market minute bar is {minutes:g} min old "
                        "— Polygon ingestion appears stalled"
                    ),
                    detail={
                        "max_premarket_bar_ts": max_bar_iso,
                        "minutes_since_last_bar": minutes,
                    },
                )
            )

    evaluated = int(diagnostics.get("evaluated", 0))
    no_pm = int(diagnostics.get("no_premarket_data", 0))
    evaluable = evaluated + no_pm
    if max_bar_iso is not None and evaluable > 0:
        coverage_ratio = round(evaluated / evaluable, 4)
        if coverage_ratio < settings.PREMARKET_MIN_COVERAGE_RATIO:
            findings.append(
                ProviderGapFinding(
                    severity="warning",
                    reason="partial_coverage",
                    message=(
                        f"Only {coverage_ratio:.0%} of tickers have pre-market data "
                        f"({evaluated}/{evaluable})"
                    ),
                    detail={
                        "coverage_ratio": coverage_ratio,
                        "tickers_with_premarket_data": evaluated,
                        "evaluable_tickers": evaluable,
                        "no_history": int(diagnostics.get("no_history", 0)),
                    },
                )
            )
    return findings


def severity_level(findings: List[ProviderGapFinding]) -> int:
    """0 = none, 1 = warning, 2 = blocker (scan_provider_gap_severity gauge)."""
    if any(f.severity == "blocker" for f in findings):
        return 2
    return 1 if findings else 0


def _is_live_issue(issue: QualityGateIssue) -> bool:
    return (
        issue.code == QualityIssueCode.provider_gap
        and issue.detail.get("subtype") == LIVE_SUBTYPE
    )


def apply_provider_gaps(
    run: Any,
    findings: List[ProviderGapFinding],
    *,
    universe_id: Optional[int],
    scanner_type: str,
    worker: Optional[str],
    provider: str = "polygon",
) -> None:
    """Fold live findings into run.quality_gate (re-deriving verdict) and set data_degraded.

    Re-applying replaces earlier live issues, so the call is idempotent.
    """
    if not findings:
        return
    existing = run.quality_gate if isinstance(run.quality_gate, dict) else None
    if existing is not None:
        assessment = QualityGateAssessment.model_validate(existing)
    else:
        assessment = QualityGateAssessment(
            policy=QualityGatePolicy.advisory,
            verdict=QualityGateVerdict.trusted,
            trusted=True,
            scope=QualityGateScope(universe_id=universe_id, scanner_type=scanner_type),
            generated_at=utc_now(),
        )
    issues = [i for i in assessment.issues if not _is_live_issue(i)]
    issues += [f.to_issue(provider, worker) for f in findings]
    verdict = _derive_verdict(issues, assessment.policy)
    updated = assessment.model_copy(
        update={
            "issues": issues,
            "warnings": [i for i in issues if i.severity == "warning"],
            "verdict": verdict,
            "trusted": verdict == QualityGateVerdict.trusted,
        }
    )
    # Same serialisation as the scan-start assessment in tasks/scanning.py.
    run.quality_gate = json.loads(json.dumps(updated.model_dump(), default=str))
    run.data_degraded = True


def live_provider_gaps(quality_gate: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """API projection: the live-degradation provider_gap issues of a stored gate."""
    if not isinstance(quality_gate, dict):
        return []
    return [
        issue
        for issue in quality_gate.get("issues") or []
        if issue.get("code") == QualityIssueCode.provider_gap.value
        and (issue.get("detail") or {}).get("subtype") == LIVE_SUBTYPE
    ]
