"""
Tests for dark-factory/scripts/dedupe_oos.py.

classify_entry and classify_all are tested directly with synthetic inputs.
No subprocess or gh calls needed — the script is pure Python with JSON I/O.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import dedupe_oos  # noqa: E402


def test_suppress_ruff_reformat_class():
    """Findings with ruff/reformat keywords are suppressed before key creation."""
    entries = ["[OOS] backend/app/services/scanner.py — cosmetic ruff reformatting applied by formatter"]
    results = dedupe_oos.classify_all(entries, [])
    assert len(results) == 1
    assert results[0]["action"] == "suppress"
    assert results[0]["key"].endswith("|ruff-reformat")


def test_within_run_dedup():
    """Two entries sharing the same (file, finding-type) key: first creates, second suppresses."""
    entries = [
        "[OOS] frontend/src/components/Chart.tsx — TypeScript TS2322 type mismatch on line 42",
        "[OOS] frontend/src/components/Chart.tsx — TypeScript TS2322 type error at prop assignment",
    ]
    results = dedupe_oos.classify_all(entries, [])
    assert len(results) == 2
    assert results[0]["action"] == "create"
    assert results[1]["action"] == "suppress"
    assert results[0]["key"] == results[1]["key"]


def test_cross_run_dedup_via_embedded_key():
    """Entry matching an open issue's embedded dedup-key gets comment action, not create."""
    entries = [
        "[OOS] frontend/src/components/Chart.tsx — TypeScript TS2322 type mismatch",
    ]
    spillovers = [
        {
            "number": 305,
            "title": "Add frontend test coverage for Chart.tsx",
            "body": (
                "## Scope spillover from #250\n\n"
                "**File/area:** frontend/src/components/Chart.tsx\n"
                "**Defect:** TypeScript TS2322 type error\n\n"
                "<!-- dedup-key: frontend/src/components/chart.tsx|ts-type-error -->\n\n"
                "---\n*Automatically triaged by MarketHawk Dark Factory scope enforcement.*"
            ),
        }
    ]
    results = dedupe_oos.classify_all(entries, spillovers)
    assert len(results) == 1
    assert results[0]["action"] == "comment:305"
    assert results[0]["key"] == "frontend/src/components/chart.tsx|ts-type-error"


def test_genuinely_new_finding_returns_create():
    """Entry with no matching key in existing issues produces create action."""
    entries = [
        "[OOS] backend/app/models/trade.py — missing Alembic migration for new nullable column",
    ]
    spillovers = [
        {
            "number": 99,
            "title": "Unrelated old issue",
            "body": (
                "Some body\n"
                "<!-- dedup-key: frontend/src/other.tsx|missing-test -->\n"
            ),
        }
    ]
    results = dedupe_oos.classify_all(entries, spillovers)
    assert len(results) == 1
    assert results[0]["action"] == "create"
    assert results[0]["key"] == "backend/app/models/trade.py|missing-migration"
